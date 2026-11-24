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

def is_gallery_complete(gallery_dir: Path, total_pages: int) -> bool:
    if not gallery_dir.exists():
        return False
    images = [p for p in gallery_dir.iterdir() if p.suffix.lower() in ('.jpg', '.png', '.webp', '.gif') and p.name != 'cover.jpg']
    return len(images) >= total_pages
