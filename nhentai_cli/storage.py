import json
import re
from pathlib import Path

WINDOWS_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')

def sanitize_filename(name: str, max_length: int = 150) -> str:
    cleaned = WINDOWS_FORBIDDEN.sub('_', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('. ')
    if not cleaned:
        cleaned = "untitled"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip('. ')
    return cleaned

def get_folder_name(gallery_id: int, title: str, scheme: str = 'both') -> str:
    clean_title = sanitize_filename(title)
    if scheme == 'code':
        return str(gallery_id)
    elif scheme == 'title':
        return clean_title
    return f"[{gallery_id}] {clean_title}"

def create_gallery_dir(output_base: Path, folder_name: str) -> Path:
    target_dir = output_base / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir

def save_info_json(gallery_dir: Path, data: dict) -> None:
    path = gallery_dir / "info.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}


def get_page_images(gallery_dir: Path) -> list[Path]:
    if not gallery_dir.exists():
        return []
    pages = [
        p for p in gallery_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.stem.lower() != 'cover'
    ]
    return sorted(pages, key=lambda p: p.name)


def get_pdf_path(gallery_dir: Path, folder_name: str | None = None) -> Path:
    name = folder_name or gallery_dir.name
    return gallery_dir / f"{name}.pdf"


def remove_page_images(gallery_dir: Path) -> None:
    for page_path in get_page_images(gallery_dir):
        page_path.unlink(missing_ok=True)


def is_gallery_complete(
    gallery_dir: Path,
    total_pages: int,
    output_format: str = 'image',
    folder_name: str | None = None
) -> bool:
    if not gallery_dir.exists():
        return False

    has_images = len(get_page_images(gallery_dir)) >= total_pages
    pdf_path = get_pdf_path(gallery_dir, folder_name)
    has_pdf = pdf_path.exists() and pdf_path.stat().st_size > 0

    if output_format == 'pdf':
        return has_pdf
    if output_format == 'both':
        return has_images and has_pdf
    return has_images
