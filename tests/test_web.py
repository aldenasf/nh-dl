import asyncio
import json
import sys
from pathlib import Path
from PIL import Image
import pytest
from aiohttp.test_utils import TestClient, TestServer

from nh_dl.cli import get_args
from nh_dl.web.library import LibraryIndex
from nh_dl.web.server import create_app
from nh_dl.web.state import load_web_state, update_web_state


def _make_img(path: Path, color: tuple[int, int, int] = (200, 30, 80)) -> None:
    Image.new("RGB", (40, 60), color).save(path)


def test_library_index_variants(tmp_path):
    # 1. Standard gallery with info.json + cover + pages + pdf
    g1 = tmp_path / "[135653] Sample One"
    g1.mkdir()
    _make_img(g1 / "cover.jpg")
    _make_img(g1 / "001.jpg")
    _make_img(g1 / "002.webp")
    (g1 / "[135653] Sample One.pdf").write_bytes(b"%PDF-1.4\n")
    (g1 / "info.json").write_text(
        json.dumps(
            {
                "id": 135653,
                "title": {"english": "Sample One", "japanese": "サンプル", "pretty": "Sample One"},
                "artists": ["artist_a"],
                "tags": ["yuri", "schoolgirl uniform"],
                "languages": ["english"],
                "pages": 2,
                "cover": "cover.jpg",
                "downloaded_at": "2026-11-26T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    # 2. Missing info.json & missing cover.jpg -> falls back to folder name & first page
    g2 = tmp_path / "[228922] No Info Gallery"
    g2.mkdir()
    _make_img(g2 / "001.png")
    _make_img(g2 / "002.png")

    # 3. Corrupt info.json fallback
    g3 = tmp_path / "[333333] Corrupt Info"
    g3.mkdir()
    (g3 / "info.json").write_text("{bad json", encoding="utf-8")
    _make_img(g3 / "001.jpg")

    # 4. Flat PDF
    (tmp_path / "[999999] Flat Doc.pdf").write_bytes(b"%PDF-1.4\n")

    index = LibraryIndex(tmp_path)
    assert len(index.entries) == 4

    e1 = index.get("135653")
    assert e1 is not None
    assert e1.display_title == "Sample One"
    assert e1.page_count == 2
    assert e1.cover_name == "cover.jpg"
    assert e1.pdf_name == "[135653] Sample One.pdf"
    assert "info.json" not in e1.allowed_files

    e2 = index.get("228922")
    assert e2 is not None
    assert e2.display_title == "No Info Gallery"
    assert e2.cover_name == "001.png"
    assert e2.page_count == 2

    e3 = index.get("333333")
    assert e3 is not None
    assert e3.display_title == "Corrupt Info"

    e4 = index.get("999999")
    assert e4 is not None
    assert e4.pdf_name == "[999999] Flat Doc.pdf"
    assert e4.cover_name is None


def test_library_missing_dir(tmp_path):
    index = LibraryIndex(tmp_path / "does_not_exist")
    assert index.list_summaries() == []


def test_web_state_persistence_and_validation(tmp_path):
    sf = tmp_path / ".nh_dl_web.json"
    assert load_web_state(sf) == {
        "library_dir": None,
        "bookmarks": [],
        "progress": {},
        "reader_prefs": {"mode": "vertical", "fit": "width"},
        "search_history": [],
    }

    s1 = update_web_state({"toggle_bookmark": "135653"}, sf)
    assert s1["bookmarks"] == ["135653"]
    s2 = update_web_state({"toggle_bookmark": "135653"}, sf)
    assert s2["bookmarks"] == []

    # Reject bool page, accept int >= 1, update prefs, and manage search_history
    s3 = update_web_state(
        {
            "toggle_bookmark": 228922,
            "progress": {"228922": {"page": 5}, "bad": {"page": True}},
            "reader_prefs": {"mode": "single", "fit": "height"},
            "add_search": 'tag:"yuri" -tag:"females only"',
        },
        sf,
    )
    assert s3["bookmarks"] == ["228922"]
    assert s3["progress"]["228922"]["page"] == 5
    assert "bad" not in s3["progress"]
    assert s3["reader_prefs"] == {"mode": "single", "fit": "height"}
    assert len(s3["search_history"]) == 1
    assert s3["search_history"][0]["query"] == 'tag:"yuri" -tag:"females only"'
    assert s3["search_history"][0]["starred"] is False

    s4 = update_web_state({"toggle_star_search": 'tag:"yuri" -tag:"females only"'}, sf)
    assert s4["search_history"][0]["starred"] is True

    s5 = update_web_state({"remove_search": 'tag:"yuri" -tag:"females only"'}, sf)
    assert s5["search_history"] == []

    # Corrupt file falls back cleanly
    sf.write_text("{corrupt", encoding="utf-8")
    assert load_web_state(sf)["bookmarks"] == []


def test_server_api_and_security(tmp_path):
    gdir = tmp_path / "[135653] Test Gallery"
    gdir.mkdir()
    _make_img(gdir / "cover.jpg")
    _make_img(gdir / "001.jpg")
    (gdir / "info.json").write_text(
        json.dumps({"id": 135653, "title": {"pretty": "Test Gallery"}, "pages": 1}),
        encoding="utf-8",
    )
    state_file = tmp_path / ".nh_dl_web.json"

    async def _run():
        app = create_app(output_dir=tmp_path, state_path=state_file)
        async with TestClient(TestServer(app)) as client:
            r_index = await client.get("/")
            assert r_index.status == 200
            assert "nh-dl" in await r_index.text()

            r_css = await client.get("/static/styles.css")
            assert r_css.status == 200

            r_list = await client.get("/api/galleries")
            assert r_list.status == 200
            body = await r_list.json()
            assert len(body["galleries"]) == 1
            assert body["galleries"][0]["key"] == "135653"

            r_detail = await client.get("/api/galleries/135653")
            assert r_detail.status == 200
            detail = await r_detail.json()
            assert detail["pages"][0]["url"] == "/media/135653/001.jpg"

            r_missing = await client.get("/api/galleries/999999")
            assert r_missing.status == 404

            r_img = await client.get("/media/135653/001.jpg")
            assert r_img.status == 200
            assert len(await r_img.read()) > 0

            # Disallow info.json and path traversal
            assert (await client.get("/media/135653/info.json")).status == 404
            assert (await client.get("/media/135653/..%2Finfo.json")).status in (403, 404)
            assert (await client.get("/static/..%2Fserver.py")).status in (403, 404)

            # Patch state & verify persistence
            r_patch = await client.patch(
                "/api/state",
                json={
                    "toggle_bookmark": "135653",
                    "progress": {"135653": {"page": 1}},
                    "add_search": "tag:yuri",
                },
            )
            assert r_patch.status == 200
            patched = await r_patch.json()
            assert patched["bookmarks"] == ["135653"]
            assert patched["progress"]["135653"]["page"] == 1
            assert patched["search_history"][0]["query"] == "tag:yuri"

            r_bad = await client.patch("/api/state", data="not-json")
            assert r_bad.status == 400

            # Rescan picks up a newly added folder
            g2 = tmp_path / "[444444] Added Later"
            g2.mkdir()
            _make_img(g2 / "001.jpg")
            r_rescan = await client.post("/api/rescan")
            assert r_rescan.status == 200
            rescan_data = await r_rescan.json()
            assert rescan_data["count"] == 2

            # Change library folder via /api/library-dir
            alt_dir = tmp_path / "alt_library"
            alt_dir.mkdir()
            g_alt = alt_dir / "[777777] Alt Gallery"
            g_alt.mkdir()
            _make_img(g_alt / "001.jpg")

            r_bad_dir = await client.post("/api/library-dir", json={"path": str(tmp_path / "missing_dir")})
            assert r_bad_dir.status == 400

            r_set_dir = await client.post("/api/library-dir", json={"path": str(alt_dir)})
            assert r_set_dir.status == 200
            dir_data = await r_set_dir.json()
            assert dir_data["count"] == 1
            assert dir_data["galleries"][0]["key"] == "777777"
            assert dir_data["state"]["library_dir"] == str(alt_dir.resolve())

        # Restarting with use_saved_library_dir=True honors saved library_dir
        app2 = create_app(output_dir=tmp_path, state_path=state_file, use_saved_library_dir=True)
        async with TestClient(TestServer(app2)) as client2:
            r_list2 = await client2.get("/api/galleries")
            assert r_list2.status == 200
            body2 = await r_list2.json()
            assert len(body2["galleries"]) == 1
            assert body2["galleries"][0]["key"] == "777777"

    asyncio.run(_run())


def test_cli_serve_args(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["main.py", "--serve", "-o", str(tmp_path), "--port", "9090"])
    cfg = get_args()
    assert cfg["mode"] == "serve"
    assert cfg["output"] == tmp_path
    assert cfg["output_explicit"] is True
    assert cfg["port"] == 9090

    monkeypatch.setattr(sys, "argv", ["main.py", "--serve"])
    cfg2 = get_args()
    assert cfg2["output_explicit"] is False

    monkeypatch.setattr(sys, "argv", ["main.py", "--serve", "--port", "70000"])
    with pytest.raises(ValueError):
        get_args()
