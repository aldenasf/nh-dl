import asyncio
import json
from pathlib import Path
from PIL import Image

from nh_dl.cli import parse_codes, parse_codes_text
from nh_dl.dns import is_nhentai_host
from nh_dl.downloader import download_file
from nh_dl.pdf import build_pdf_from_images
from nh_dl.state import load_state, save_state
from nh_dl.storage import get_page_images, remove_page_images, scan_completed_ids


def test_is_nhentai_host():
    assert is_nhentai_host("nhentai.net") is True
    assert is_nhentai_host("i.nhentai.net") is True
    assert is_nhentai_host("i7.nhentai.net") is True
    assert is_nhentai_host("t2.nhentai.net") is True
    assert is_nhentai_host("evil-nhentai.net") is False
    assert is_nhentai_host("example.com") is False


def test_parse_codes_mixed_delimiters(tmp_path):
    raw = """
    # header comment
    111111, 222222
    https://nhentai.net/g/333333/, 444444 # inline comment
    555555,
    111111
    """
    assert parse_codes_text(raw) == [111111, 222222, 333333, 444444, 555555]
    assert parse_codes("123456, https://nhentai.net/g/654321/") == [123456, 654321]

    f = tmp_path / "codes.txt"
    f.write_text("100001, 100002\n100003\n", encoding="utf-8")
    assert parse_codes(str(f)) == [100001, 100002, 100003]


def test_state_roundtrip(tmp_path):
    sf = tmp_path / ".nh_dl.json"
    save_state(
        {
            "input": "codes.txt",
            "output": "./out",
            "folder_name": "code",
            "format": "pdf",
            "flat": True,
            "concurrency": 8,
        },
        sf,
    )
    assert load_state(sf) == {
        "input": "codes.txt",
        "output": "./out",
        "folder_name": "code",
        "format": "pdf",
        "flat": True,
        "concurrency": 8,
    }


def test_scan_completed_ids_and_pdf(tmp_path):
    gdir = tmp_path / "[123456] Sample"
    gdir.mkdir()
    Image.new("RGB", (60, 80), (255, 0, 0)).save(gdir / "001.webp")
    Image.new("RGBA", (60, 80), (0, 255, 0, 128)).save(gdir / "002.png")
    Image.new("RGB", (30, 40), (0, 0, 255)).save(gdir / "cover.webp")
    (gdir / "info.json").write_text(json.dumps({"id": 123456, "pages": 2}), encoding="utf-8")

    assert scan_completed_ids(tmp_path, "image", False) == {123456}
    assert scan_completed_ids(tmp_path, "both", False) == set()

    pdf_path = gdir / "[123456] Sample.pdf"
    build_pdf_from_images(get_page_images(gdir), pdf_path)
    assert scan_completed_ids(tmp_path, "both", False) == {123456}

    remove_page_images(gdir)
    assert scan_completed_ids(tmp_path, "image", False) == set()
    assert scan_completed_ids(tmp_path, "pdf", False) == {123456}

    flat_pdf = tmp_path / "[999999] Flat.pdf"
    flat_pdf.write_bytes(b"%PDF-1.4\n")
    assert scan_completed_ids(tmp_path, "pdf", True) == {999999}


class _FakeContent:
    def __init__(self, data: bytes):
        self._data = data

    async def iter_chunked(self, size: int):
        yield self._data


class _FakeResponse:
    def __init__(self, status: int, data: bytes = b""):
        self.status = status
        self.content = _FakeContent(data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, routes: dict[str, tuple[int, bytes]]):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):
        self.calls.append(url)
        status, data = self.routes.get(url, (404, b""))
        return _FakeResponse(status, data)


def test_download_file_mirror_rotation(tmp_path):
    session = _FakeSession(
        {
            "https://i.nhentai.net/galleries/1/1.webp": (503, b""),
            "https://i2.nhentai.net/galleries/1/1.webp": (200, b"imgdata"),
        }
    )
    dest = tmp_path / "001.webp"
    ok, size = asyncio.run(
        download_file(
            session,
            "https://i.nhentai.net/galleries/1/1.webp",
            dest,
            asyncio.Semaphore(1),
            mirrors=["i.nhentai.net", "i2.nhentai.net"],
        )
    )
    assert ok is True
    assert size == 7
    assert dest.read_bytes() == b"imgdata"


def test_download_file_404_alt_extension(tmp_path):
    session = _FakeSession(
        {
            "https://i.nhentai.net/galleries/1/2.webp": (404, b""),
            "https://i.nhentai.net/galleries/1/2.jpg": (200, b"jpgdata"),
        }
    )
    dest = tmp_path / "002.webp"
    ok, size = asyncio.run(
        download_file(
            session,
            "https://i.nhentai.net/galleries/1/2.webp",
            dest,
            asyncio.Semaphore(1),
            mirrors=["i.nhentai.net", "i2.nhentai.net"],
            try_alt_exts=True,
        )
    )
    assert ok is True
    assert size == 7
    assert (tmp_path / "002.jpg").read_bytes() == b"jpgdata"
    assert session.calls == [
        "https://i.nhentai.net/galleries/1/2.webp",
        "https://i.nhentai.net/galleries/1/2.jpg",
    ]



def test_batch_log_buffer_width_fitting(tmp_path):
    from rich.text import Text
    from nh_dl.ui import BatchLogBuffer

    buf = BatchLogBuffer(total=10, output_dir=tmp_path)
    long_msg = "Downloaded 38 pages -> [537235] A Very Long Gallery Title That Should Truncate When Narrow"
    entry = buf.add("success", 1, 10, 537235, long_msg)
    buf.add("skip", 2, 10, 478120, "already completed locally, skipping.")
    buf.add("error", 3, 10, 999999, "Not found")

    narrow = Text.from_markup(buf.format_entry(entry, cols=60)).plain
    wide = Text.from_markup(buf.format_entry(entry, cols=140)).plain

    assert len(narrow) <= 58
    assert narrow.endswith("…")
    assert len(wide) > len(narrow)
    assert "Truncate When Narrow" in wide

    rendered = buf.render_to_ansi(cols=80)
    assert "nh-dl" in rendered
    assert "537235" in rendered
    assert "478120" in rendered


def test_progress_resize_debounce(tmp_path):
    from nh_dl.ui import BatchLogBuffer, create_download_progress

    buf = BatchLogBuffer(total=5, output_dir=tmp_path)
    progress = create_download_progress(log_buffer=buf)
    initial_cols = progress._last_cols

    # Same width never triggers redraw
    assert progress._should_redraw_on_resize(initial_cols, now=1.0) is False

    # New width starts debounce timer
    new_cols = initial_cols + 20
    assert progress._should_redraw_on_resize(new_cols, now=1.0) is False
    # Before 150ms: still False
    assert progress._should_redraw_on_resize(new_cols, now=1.10) is False
    # Different width mid-drag resets timer
    new_cols_2 = new_cols + 10
    assert progress._should_redraw_on_resize(new_cols_2, now=1.12) is False
    assert progress._should_redraw_on_resize(new_cols_2, now=1.20) is False
    # After >= 150ms stable: triggers redraw and updates _last_cols
    assert progress._should_redraw_on_resize(new_cols_2, now=1.30) is True
    assert progress._last_cols == new_cols_2
    assert progress._should_redraw_on_resize(new_cols_2, now=1.50) is False
