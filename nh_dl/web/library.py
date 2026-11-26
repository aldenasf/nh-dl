from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ..storage import (
    IMAGE_EXTS,
    _extract_id_from_name,
    get_page_images,
    get_pdf_path,
)

_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9._-]+")
_PREFIX_ID_RE = re.compile(r"^\[\d+\]\s*")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _mtime_iso(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


def _fallback_title(name: str) -> str:
    stripped = _PREFIX_ID_RE.sub("", name).strip()
    return stripped or name


def _make_unique_key(base_id: int | None, fallback_name: str, used_keys: set[str]) -> str:
    if base_id is not None:
        base = str(base_id)
    else:
        base = _SAFE_KEY_RE.sub("-", fallback_name).strip("-") or "gallery"

    candidate = base
    suffix = 2
    while candidate in used_keys:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_keys.add(candidate)
    return candidate


def _find_cover_file(gallery_dir: Path, info: dict, pages: list[Path]) -> Path | None:
    cover_hint = info.get("cover")
    if isinstance(cover_hint, str) and cover_hint:
        hint_path = gallery_dir / cover_hint
        if hint_path.is_file() and hint_path.suffix.lower() in IMAGE_EXTS:
            return hint_path

    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        candidate = gallery_dir / f"cover{ext}"
        if candidate.is_file():
            return candidate

    return pages[0] if pages else None


def _find_pdf_file(gallery_dir: Path) -> Path | None:
    preferred = get_pdf_path(gallery_dir, gallery_dir.name)
    if preferred.is_file() and preferred.stat().st_size > 0:
        return preferred

    for pdf_path in sorted(gallery_dir.glob("*.pdf"), key=lambda p: p.name):
        if pdf_path.is_file() and pdf_path.stat().st_size > 0:
            return pdf_path
    return None


@dataclass
class GalleryEntry:
    """Indexed representation of a downloaded gallery or flat PDF."""

    key: str
    gallery_id: int | None
    title: dict[str, str]
    display_title: str
    artists: list[str]
    parodies: list[str]
    characters: list[str]
    groups: list[str]
    languages: list[str]
    categories: list[str]
    tags: list[str]
    page_count: int
    downloaded_at: str
    pages: list[str]
    cover_name: str | None
    pdf_name: str | None
    root_dir: Path
    allowed_files: dict[str, Path] = field(default_factory=dict)

    def media_url(self, filename: str | None) -> str | None:
        if not filename:
            return None
        return f"/media/{quote(self.key, safe='')}/{quote(filename, safe='')}"

    def to_summary(self) -> dict:
        return {
            "key": self.key,
            "id": self.gallery_id,
            "title": self.title,
            "display_title": self.display_title,
            "artists": self.artists,
            "parodies": self.parodies,
            "characters": self.characters,
            "groups": self.groups,
            "languages": self.languages,
            "categories": self.categories,
            "tags": self.tags,
            "page_count": self.page_count,
            "downloaded_at": self.downloaded_at,
            "cover_url": self.media_url(self.cover_name),
            "pdf_url": self.media_url(self.pdf_name),
            "has_images": len(self.pages) > 0,
            "has_pdf": self.pdf_name is not None,
        }

    def to_detail(self) -> dict:
        detail = self.to_summary()
        detail["pages"] = [
            {"num": idx + 1, "name": name, "url": self.media_url(name)}
            for idx, name in enumerate(self.pages)
        ]
        return detail


class LibraryIndex:
    """In-memory read-only index of downloaded galleries in output_dir."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.entries: dict[str, GalleryEntry] = {}
        self.ordered_keys: list[str] = []
        self.rescan()

    def rescan(self) -> int:
        entries: dict[str, GalleryEntry] = {}
        used_keys: set[str] = set()

        if self.output_dir.is_dir():
            root_resolved = self.output_dir.resolve()
            folder_pdf_names: set[str] = set()

            for item in sorted(self.output_dir.iterdir(), key=lambda p: p.name.lower()):
                if item.is_dir():
                    entry = self._scan_folder(item, used_keys)
                    if entry is not None:
                        entries[entry.key] = entry
                        if entry.pdf_name:
                            folder_pdf_names.add(entry.pdf_name)
                elif item.is_file() and item.suffix.lower() == ".pdf" and item.stat().st_size > 0:
                    if item.name in folder_pdf_names:
                        continue
                    entry = self._scan_flat_pdf(item, root_resolved, used_keys)
                    if entry is not None:
                        entries[entry.key] = entry

        ordered = sorted(
            entries.values(),
            key=lambda e: (e.downloaded_at, e.gallery_id or 0, e.display_title.lower()),
            reverse=True,
        )
        self.entries = entries
        self.ordered_keys = [e.key for e in ordered]
        return len(self.entries)

    def _scan_folder(self, gallery_dir: Path, used_keys: set[str]) -> GalleryEntry | None:
        info: dict = {}
        info_path = gallery_dir / "info.json"
        if info_path.is_file():
            try:
                loaded = json.loads(info_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    info = loaded
            except Exception:
                info = {}

        pages = get_page_images(gallery_dir)
        pdf_file = _find_pdf_file(gallery_dir)
        if not pages and pdf_file is None:
            return None

        gid = info.get("id") if _is_int(info.get("id")) else _extract_id_from_name(gallery_dir.name)
        key = _make_unique_key(gid, gallery_dir.name, used_keys)

        raw_title = info.get("title") if isinstance(info.get("title"), dict) else {}
        fallback = _fallback_title(gallery_dir.name)
        title = {
            "english": str(raw_title.get("english") or "").strip(),
            "japanese": str(raw_title.get("japanese") or "").strip(),
            "pretty": str(raw_title.get("pretty") or "").strip(),
        }
        display_title = title["pretty"] or title["english"] or title["japanese"] or fallback
        if not title["english"] and not title["pretty"]:
            title["english"] = fallback

        cover_file = _find_cover_file(gallery_dir, info, pages)
        downloaded_at = str(info.get("downloaded_at") or "").strip() or _mtime_iso(gallery_dir)

        root_resolved = gallery_dir.resolve()
        allowed_files: dict[str, Path] = {}
        for p in pages:
            allowed_files[p.name] = p.resolve()
        if cover_file is not None:
            allowed_files[cover_file.name] = cover_file.resolve()
        if pdf_file is not None:
            allowed_files[pdf_file.name] = pdf_file.resolve()

        page_count = len(pages) if pages else (info.get("pages") if _is_int(info.get("pages")) else 0)

        return GalleryEntry(
            key=key,
            gallery_id=gid,
            title=title,
            display_title=display_title,
            artists=_str_list(info.get("artists")),
            parodies=_str_list(info.get("parodies")),
            characters=_str_list(info.get("characters")),
            groups=_str_list(info.get("groups")),
            languages=_str_list(info.get("languages")),
            categories=_str_list(info.get("categories")),
            tags=_str_list(info.get("tags")),
            page_count=page_count,
            downloaded_at=downloaded_at,
            pages=[p.name for p in pages],
            cover_name=cover_file.name if cover_file else None,
            pdf_name=pdf_file.name if pdf_file else None,
            root_dir=root_resolved,
            allowed_files=allowed_files,
        )

    def _scan_flat_pdf(
        self, pdf_file: Path, root_resolved: Path, used_keys: set[str]
    ) -> GalleryEntry:
        gid = _extract_id_from_name(pdf_file.stem)
        key = _make_unique_key(gid, pdf_file.stem, used_keys)
        display_title = _fallback_title(pdf_file.stem)
        return GalleryEntry(
            key=key,
            gallery_id=gid,
            title={"english": display_title, "japanese": "", "pretty": display_title},
            display_title=display_title,
            artists=[],
            parodies=[],
            characters=[],
            groups=[],
            languages=[],
            categories=["pdf"],
            tags=[],
            page_count=0,
            downloaded_at=_mtime_iso(pdf_file),
            pages=[],
            cover_name=None,
            pdf_name=pdf_file.name,
            root_dir=root_resolved,
            allowed_files={pdf_file.name: pdf_file.resolve()},
        )

    def list_summaries(self) -> list[dict]:
        return [self.entries[k].to_summary() for k in self.ordered_keys]

    def get(self, key: str) -> GalleryEntry | None:
        return self.entries.get(key)
