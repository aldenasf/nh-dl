from __future__ import annotations

import asyncio
from pathlib import Path
from aiohttp import web

from ..ui import print_info, print_success
from .library import LibraryIndex
from .state import WEB_STATE_FILE, load_web_state, update_web_state

STATIC_DIR = Path(__file__).parent / "static"

LIBRARY_KEY: web.AppKey[LibraryIndex] = web.AppKey("library", LibraryIndex)
STATE_PATH_KEY: web.AppKey[Path] = web.AppKey("state_path", Path)
STATE_LOCK_KEY: web.AppKey[asyncio.Lock] = web.AppKey("state_lock", asyncio.Lock)


def _library(request: web.Request) -> LibraryIndex:
    return request.app[LIBRARY_KEY]


async def handle_index(request: web.Request) -> web.Response:
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        return web.Response(status=404, text="Frontend assets missing.")
    return web.FileResponse(index_file, headers={"Cache-Control": "no-cache"})


async def handle_static(request: web.Request) -> web.Response:
    filename = request.match_info.get("filename", "")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return web.Response(status=403, text="Forbidden")

    static_root = STATIC_DIR.resolve()
    target = (static_root / filename).resolve()
    if not target.is_relative_to(static_root) or not target.is_file():
        return web.Response(status=404, text="Not found")

    return web.FileResponse(target, headers={"Cache-Control": "no-cache"})


async def handle_list_galleries(request: web.Request) -> web.Response:
    lib = _library(request)
    async with request.app[STATE_LOCK_KEY]:
        state = load_web_state(request.app[STATE_PATH_KEY])
    resolved_dir = lib.output_dir.resolve() if lib.output_dir.exists() else lib.output_dir
    return web.json_response(
        {
            "galleries": lib.list_summaries(),
            "state": state,
            "output_dir": str(resolved_dir),
        }
    )


async def handle_get_gallery(request: web.Request) -> web.Response:
    key = request.match_info.get("key", "")
    entry = _library(request).get(key)
    if entry is None:
        return web.json_response({"error": "Gallery not found"}, status=404)
    return web.json_response(entry.to_detail())


async def handle_rescan(request: web.Request) -> web.Response:
    lib = _library(request)
    count = await asyncio.to_thread(lib.rescan)
    resolved_dir = lib.output_dir.resolve() if lib.output_dir.exists() else lib.output_dir
    return web.json_response(
        {
            "count": count,
            "output_dir": str(resolved_dir),
            "galleries": lib.list_summaries(),
        }
    )


def _pick_folder_dialog(initial_dir: str) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(initialdir=initial_dir or None, title="Select library folder")
        return selected or None
    finally:
        root.destroy()


async def handle_browse_folder(request: web.Request) -> web.Response:
    lib = _library(request)
    initial = str(lib.output_dir.resolve()) if lib.output_dir.is_dir() else ""
    try:
        chosen = await asyncio.to_thread(_pick_folder_dialog, initial)
    except Exception as exc:
        return web.json_response({"error": f"Folder dialog unavailable: {exc}"}, status=501)
    return web.json_response({"path": chosen})


async def handle_set_library_dir(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        return web.json_response({"error": "Missing 'path' string"}, status=400)

    raw_path = payload["path"].strip().strip('"\'')
    if not raw_path:
        return web.json_response({"error": "Folder path cannot be empty"}, status=400)

    target = Path(raw_path).expanduser().resolve()
    if not target.is_dir():
        return web.json_response({"error": f"Directory not found: {target}"}, status=400)

    lib = _library(request)
    lib.output_dir = target
    count = await asyncio.to_thread(lib.rescan)
    async with request.app[STATE_LOCK_KEY]:
        state = update_web_state({"library_dir": str(target)}, request.app[STATE_PATH_KEY])

    return web.json_response(
        {
            "count": count,
            "output_dir": str(target),
            "galleries": lib.list_summaries(),
            "state": state,
        }
    )


async def handle_get_state(request: web.Request) -> web.Response:
    async with request.app[STATE_LOCK_KEY]:
        state = load_web_state(request.app[STATE_PATH_KEY])
    return web.json_response(state)


async def handle_patch_state(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"error": "JSON object expected"}, status=400)

    async with request.app[STATE_LOCK_KEY]:
        state = update_web_state(payload, request.app[STATE_PATH_KEY])
    return web.json_response(state)


async def handle_media(request: web.Request) -> web.Response:
    key = request.match_info.get("key", "")
    filename = request.match_info.get("filename", "")

    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return web.Response(status=403, text="Forbidden")

    entry = _library(request).get(key)
    if entry is None:
        return web.Response(status=404, text="Gallery not found")

    target = entry.allowed_files.get(filename)
    if target is None:
        return web.Response(status=404, text="File not found")

    resolved = target.resolve()
    if not resolved.is_relative_to(entry.root_dir):
        return web.Response(status=403, text="Forbidden")
    if not resolved.is_file():
        return web.Response(status=404, text="File not found")

    return web.FileResponse(resolved, headers={"Cache-Control": "public, max-age=86400"})


def create_app(
    output_dir: Path,
    state_path: Path = WEB_STATE_FILE,
    use_saved_library_dir: bool = False,
) -> web.Application:
    effective_dir = Path(output_dir)
    if use_saved_library_dir:
        saved_dir = load_web_state(Path(state_path)).get("library_dir")
        if saved_dir and Path(saved_dir).is_dir():
            effective_dir = Path(saved_dir)

    app = web.Application()
    app[LIBRARY_KEY] = LibraryIndex(effective_dir)
    app[STATE_PATH_KEY] = Path(state_path)
    app[STATE_LOCK_KEY] = asyncio.Lock()

    app.router.add_get("/", handle_index)
    app.router.add_get("/static/{filename}", handle_static)
    app.router.add_get("/api/galleries", handle_list_galleries)
    app.router.add_get("/api/galleries/{key}", handle_get_gallery)
    app.router.add_post("/api/rescan", handle_rescan)
    app.router.add_post("/api/browse-folder", handle_browse_folder)
    app.router.add_post("/api/library-dir", handle_set_library_dir)
    app.router.add_get("/api/state", handle_get_state)
    app.router.add_patch("/api/state", handle_patch_state)
    app.router.add_get("/media/{key}/{filename}", handle_media)
    return app


async def serve_web_ui(
    output_dir: Path,
    port: int = 8080,
    host: str = "127.0.0.1",
    state_path: Path = WEB_STATE_FILE,
    use_saved_library_dir: bool = False,
) -> None:
    app = create_app(
        output_dir=output_dir,
        state_path=state_path,
        use_saved_library_dir=use_saved_library_dir,
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()

    site = web.TCPSite(runner, host=host, port=port)
    try:
        await site.start()
    except OSError as exc:
        await runner.cleanup()
        raise RuntimeError(
            f"Could not bind http://{host}:{port} ({exc}). Try passing --port <other_port>."
        ) from exc

    lib = app[LIBRARY_KEY]
    count = len(lib.entries)
    resolved_dir = lib.output_dir.resolve() if lib.output_dir.exists() else lib.output_dir
    print_info(f"Indexed [bold]{count}[/bold] galleries from [dim]{resolved_dir}[/dim]")
    print_success(f"Web reader running at [bold underline]http://{host}:{port}[/bold underline] [dim](Press Ctrl+C to stop)[/dim]")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
