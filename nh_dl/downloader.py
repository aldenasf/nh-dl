import asyncio
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
import aiohttp
import nhentaipy
from nhentaipy.errors import NotFound, NHentaiError
from rich.markup import escape
from rich.progress import Progress

from .dns import enable_doh_resolver
from .pdf import build_pdf_from_images
from .storage import (
    get_folder_name,
    create_gallery_dir,
    save_info_json,
    is_gallery_complete,
    get_page_images,
    get_pdf_path,
    remove_page_images,
)
from .ui import create_download_progress

enable_doh_resolver()

MEDIA_TYPE_EXT = {
    'j': '.jpg',
    'p': '.png',
    'g': '.gif',
    'w': '.webp',
}

IMAGE_MIRRORS = [
    "i.nhentai.net",
    "i2.nhentai.net",
    "i3.nhentai.net",
    "i5.nhentai.net",
    "i7.nhentai.net",
]

THUMB_MIRRORS = [
    "t.nhentai.net",
    "t2.nhentai.net",
    "t3.nhentai.net",
]

ALT_IMAGE_EXTS = ('.jpg', '.png', '.webp')

def extract_metadata(gallery, cover_filename: str = "cover.jpg") -> dict:
    artists = []
    tags = []
    parodies = []
    characters = []
    groups = []
    languages = []
    categories = []

    if hasattr(gallery, 'tags') and gallery.tags:
        for t in gallery.tags:
            tag_name = getattr(t, 'name', '')
            tag_type = getattr(t, 'type', '')
            if tag_type == 'artist':
                artists.append(tag_name)
            elif tag_type == 'tag':
                tags.append(tag_name)
            elif tag_type == 'parody':
                parodies.append(tag_name)
            elif tag_type == 'character':
                characters.append(tag_name)
            elif tag_type == 'group':
                groups.append(tag_name)
            elif tag_type == 'language':
                languages.append(tag_name)
            elif tag_type == 'category':
                categories.append(tag_name)

    return {
        "id": gallery.id,
        "media_id": str(gallery.media_id),
        "title": {
            "english": getattr(gallery.title, "english", ""),
            "japanese": getattr(gallery.title, "japanese", ""),
            "pretty": getattr(gallery.title, "pretty", "") or getattr(gallery.title, "english", "") or str(gallery.id)
        },
        "artists": artists,
        "parodies": parodies,
        "characters": characters,
        "groups": groups,
        "languages": languages,
        "categories": categories,
        "tags": tags,
        "pages": len(gallery.images.pages),
        "cover": cover_filename,
        "downloaded_at": datetime.now(timezone.utc).isoformat()
    }

def _truncate_title(title: str, max_len: int = 34) -> str:
    clean = " ".join(title.split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"

def _replace_host(url: str, new_host: str) -> str:
    scheme, rest = url.split("://", 1)
    _, path = rest.split("/", 1)
    return f"{scheme}://{new_host}/{path}"


async def _fetch_to_file(
    session: aiohttp.ClientSession,
    url: str,
    dest_path: Path,
    headers: dict[str, str],
) -> tuple[str, int]:
    temp_path = dest_path.with_suffix(dest_path.suffix + '.tmp')
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 200:
                bytes_count = 0
                with open(temp_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        bytes_count += len(chunk)
                temp_path.replace(dest_path)
                return "ok", bytes_count
            if response.status == 404:
                return "not_found", 0
            return "retry", 0
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        return "retry", 0


async def download_file(
    session: aiohttp.ClientSession,
    url: str,
    dest_path: Path,
    semaphore: asyncio.Semaphore,
    mirrors: list[str] | None = None,
    try_alt_exts: bool = False,
) -> tuple[bool, int]:
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return True, dest_path.stat().st_size

    headers = {'User-Agent': 'Mozilla/5.0'}
    candidate_urls = [_replace_host(url, host) for host in mirrors] if mirrors else [url]

    async with semaphore:
        for idx, target_url in enumerate(candidate_urls):
            status, bytes_count = await _fetch_to_file(session, target_url, dest_path, headers)
            if status == "ok":
                return True, bytes_count
            if status == "not_found":
                if try_alt_exts:
                    orig_ext = dest_path.suffix.lower()
                    base_url = url.rsplit(".", 1)[0]
                    for alt_ext in ALT_IMAGE_EXTS:
                        if alt_ext == orig_ext:
                            continue
                        alt_status, alt_bytes = await _fetch_to_file(
                            session, f"{base_url}{alt_ext}", dest_path.with_suffix(alt_ext), headers
                        )
                        if alt_status == "ok":
                            return True, alt_bytes
                return False, 0
            if idx < len(candidate_urls) - 1:
                await asyncio.sleep(0.5 * (idx + 1))

    return False, 0

def get_page_extension(page) -> str:
    t = getattr(page, 't', '')
    if t in MEDIA_TYPE_EXT:
        return MEDIA_TYPE_EXT[t]
    path = getattr(page, 'path', '')
    if '.' in path:
        return '.' + path.split('.')[-1]
    return '.jpg'

async def _download_pages(
    gallery,
    gallery_id: int,
    media_id: str,
    target_dir: Path,
    concurrency: int,
    session: aiohttp.ClientSession,
    cover_dest: Path | None = None,
    cover_ext: str = ".jpg",
    title: str = "",
    progress: Progress | None = None,
) -> tuple[bool, int]:
    total_pages = len(gallery.images.pages)
    semaphore = asyncio.Semaphore(concurrency)
    pad_width = max(3, len(str(total_pages)))
    tasks = []

    if cover_dest is not None:
        cover_path_attr = getattr(gallery.images.cover, 'path', '')
        if cover_path_attr:
            cover_url = f"https://t.nhentai.net/{cover_path_attr}"
        else:
            cover_url = f"https://t.nhentai.net/galleries/{media_id}/cover{cover_ext}"
        cover_task = download_file(session, cover_url, cover_dest, semaphore, mirrors=THUMB_MIRRORS)
    else:
        cover_task = None

    short_title = escape(_truncate_title(title)) if title else ""
    desc = f"[cyan][{gallery_id}][/cyan] {short_title}" if short_title else f"[cyan][{gallery_id}][/cyan]"

    own_progress = progress is None
    active_progress = create_download_progress() if own_progress else progress

    async def _run_tasks(prog: Progress):
        page_task_id = prog.add_task(desc, total=total_pages, speed="0.0 MB/s")
        total_bytes = 0
        start_time = time.monotonic()

        async def track_download(url: str, path: Path):
            nonlocal total_bytes
            ok, b_count = await download_file(
                session, url, path, semaphore, mirrors=IMAGE_MIRRORS, try_alt_exts=True
            )
            if ok:
                total_bytes += b_count
            elapsed = max(0.001, time.monotonic() - start_time)
            mb_rate = (total_bytes / (1024 * 1024)) / elapsed
            prog.update(page_task_id, advance=1, speed=f"{mb_rate:.1f} MB/s")
            return ok

        for idx, page in enumerate(gallery.images.pages, start=1):
            ext = get_page_extension(page)
            page_url = f"https://i.nhentai.net/galleries/{media_id}/{idx}{ext}"
            filename = f"{str(idx).zfill(pad_width)}{ext}"
            dest = target_dir / filename
            tasks.append(track_download(page_url, dest))

        try:
            if cover_task is not None:
                results = await asyncio.gather(*tasks, cover_task)
                return results[:-1]
            return await asyncio.gather(*tasks)
        finally:
            prog.remove_task(page_task_id)

    if own_progress:
        with active_progress:
            page_results = await _run_tasks(active_progress)
    else:
        page_results = await _run_tasks(active_progress)

    success_pages = sum(1 for r in page_results if r)
    return success_pages == total_pages, success_pages


async def download_gallery(
    gallery_id: int,
    output_dir: Path,
    naming_scheme: str = 'both',
    concurrency: int = 5,
    save_info: bool = True,
    output_format: str = 'image',
    flat: bool = False,
    client: nhentaipy.NHentai | None = None,
    session: aiohttp.ClientSession | None = None,
    progress: Progress | None = None,
) -> tuple[bool, str]:
    api_client = client or nhentaipy.NHentai()
    try:
        gallery = await asyncio.to_thread(api_client.galleries.get_gallery, gallery_id)
    except NotFound:
        return False, f"Gallery {gallery_id} not found (404)"
    except Exception as e:
        return False, f"Failed to fetch metadata: {e}"

    cover_ext = get_page_extension(gallery.images.cover)
    cover_filename = f"cover{cover_ext}"
    meta = extract_metadata(gallery, cover_filename)
    title = meta["title"]["pretty"] or meta["title"]["english"] or str(gallery_id)
    folder_name = get_folder_name(gallery_id, title, naming_scheme)
    total_pages = meta["pages"]
    media_id = meta["media_id"]

    async def _run_with_session(http_session: aiohttp.ClientSession) -> tuple[bool, str]:
        if flat and output_format == 'pdf':
            output_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = output_dir / f"{folder_name}.pdf"
            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                return True, f"Already completed: {pdf_path.name}"

            with tempfile.TemporaryDirectory(dir=output_dir, prefix=f".tmp_{gallery_id}_") as tmp:
                tmp_dir = Path(tmp)
                ok, success_pages = await _download_pages(
                    gallery, gallery_id, media_id, tmp_dir, concurrency, http_session,
                    title=title, progress=progress,
                )
                if not ok:
                    return False, f"Incomplete: {success_pages}/{total_pages} pages downloaded"
                try:
                    build_pdf_from_images(get_page_images(tmp_dir), pdf_path)
                except Exception as e:
                    return False, f"PDF export failed: {e}"
            return True, f"Saved PDF ({total_pages}p) -> {pdf_path.name}"

        gallery_dir = create_gallery_dir(output_dir, folder_name)
        pdf_path = (output_dir / f"{folder_name}.pdf") if flat else get_pdf_path(gallery_dir, folder_name)
        has_pdf = pdf_path.exists() and pdf_path.stat().st_size > 0
        has_images = len(get_page_images(gallery_dir)) >= total_pages

        if (output_format == 'image' and has_images) or (output_format == 'pdf' and has_pdf) or (output_format == 'both' and has_images and has_pdf):
            return True, f"Already completed: {folder_name}"

        if save_info:
            save_info_json(gallery_dir, meta)

        cover_dest = gallery_dir / cover_filename
        if not has_images or not cover_dest.exists():
            ok, success_pages = await _download_pages(
                gallery, gallery_id, media_id, gallery_dir, concurrency, http_session,
                cover_dest, cover_ext, title=title, progress=progress,
            )
            if not ok:
                return False, f"Incomplete: {success_pages}/{total_pages} pages downloaded"

        if output_format in ('pdf', 'both'):
            if not has_pdf:
                try:
                    build_pdf_from_images(get_page_images(gallery_dir), pdf_path)
                except Exception as e:
                    return False, f"PDF export failed: {e}"

            if output_format == 'pdf':
                remove_page_images(gallery_dir)
                return True, f"Saved PDF ({total_pages}p) -> {folder_name}/{pdf_path.name}"
            return True, f"Saved {total_pages} pages + PDF -> {folder_name}"

        return True, f"Downloaded {total_pages} pages -> {folder_name}"

    if session is not None:
        return await _run_with_session(session)

    async with aiohttp.ClientSession() as own_session:
        return await _run_with_session(own_session)
