import asyncio
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import aiohttp
from tqdm import tqdm
import nhentaipy
from nhentaipy.errors import NotFound, NHentaiError

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

enable_doh_resolver()

MEDIA_TYPE_EXT = {
    'j': '.jpg',
    'p': '.png',
    'g': '.gif',
    'w': '.webp',
}

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

class GalleryProgressBar(tqdm):
    total_bytes: int = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dynamic_ncols = False

    @property
    def format_dict(self):
        d = super().format_dict
        elapsed = max(0.001, d['elapsed'])
        mb = self.total_bytes / (1024 * 1024)
        mb_rate = mb / elapsed
        d['speed'] = f"{mb_rate:.1f} MB/s"
        cols = shutil.get_terminal_size((80, 20)).columns
        self.ncols = cols
        d['ncols'] = cols
        return d

async def download_file(session: aiohttp.ClientSession, url: str, dest_path: Path, semaphore: asyncio.Semaphore) -> tuple[bool, int]:
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return True, dest_path.stat().st_size
    
    temp_path = dest_path.with_suffix(dest_path.suffix + '.tmp')
    async with semaphore:
        for attempt in range(3):
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        bytes_count = 0
                        with open(temp_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(64 * 1024):
                                f.write(chunk)
                                bytes_count += len(chunk)
                        temp_path.replace(dest_path)
                        return True, bytes_count
            except Exception:
                if attempt == 2:
                    if temp_path.exists():
                        temp_path.unlink()
                    return False, 0
                await asyncio.sleep(1)
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
    cover_dest: Path | None = None,
    cover_ext: str = ".jpg",
) -> tuple[bool, int]:
    total_pages = len(gallery.images.pages)
    semaphore = asyncio.Semaphore(concurrency)
    pad_width = max(3, len(str(total_pages)))
    tasks = []

    async with aiohttp.ClientSession() as session:
        if cover_dest is not None:
            cover_path_attr = getattr(gallery.images.cover, 'path', '')
            if cover_path_attr:
                cover_url = f"https://t.nhentai.net/{cover_path_attr}"
            else:
                cover_url = f"https://t.nhentai.net/galleries/{media_id}/cover{cover_ext}"
            cover_task = download_file(session, cover_url, cover_dest, semaphore)
        else:
            cover_task = None

        pbar = GalleryProgressBar(
            total=total_pages,
            desc=f"[{gallery_id}]",
            bar_format="{desc} [{bar}] {n_fmt}/{total_fmt} ({percentage:3.0f}%) {speed}",
            ascii=" =",
            leave=False
        )

        async def track_download(url: str, path: Path):
            ok, b_count = await download_file(session, url, path, semaphore)
            if ok:
                pbar.total_bytes += b_count
            pbar.update(1)
            return ok

        for idx, page in enumerate(gallery.images.pages, start=1):
            ext = get_page_extension(page)
            page_url = f"https://i.nhentai.net/galleries/{media_id}/{idx}{ext}"
            filename = f"{str(idx).zfill(pad_width)}{ext}"
            dest = target_dir / filename
            tasks.append(track_download(page_url, dest))

        if cover_task is not None:
            results = await asyncio.gather(*tasks, cover_task)
            page_results = results[:-1]
        else:
            page_results = await asyncio.gather(*tasks)
        pbar.close()

    success_pages = sum(1 for r in page_results if r)
    return success_pages == total_pages, success_pages


async def download_gallery(
    gallery_id: int,
    output_dir: Path,
    naming_scheme: str = 'both',
    concurrency: int = 5,
    save_info: bool = True,
    output_format: str = 'image',
    flat: bool = False
) -> tuple[bool, str]:
    try:
        client = nhentaipy.NHentai()
        gallery = client.galleries.get_gallery(gallery_id)
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

    if flat and output_format == 'pdf':
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{folder_name}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, f"Already completed: {pdf_path.name}"

        with tempfile.TemporaryDirectory(dir=output_dir, prefix=f".tmp_{gallery_id}_") as tmp:
            tmp_dir = Path(tmp)
            ok, success_pages = await _download_pages(
                gallery, gallery_id, media_id, tmp_dir, concurrency
            )
            if not ok:
                return False, f"Incomplete: {success_pages}/{total_pages} pages downloaded"
            try:
                build_pdf_from_images(get_page_images(tmp_dir), pdf_path)
            except Exception as e:
                return False, f"PDF export failed: {e}"
        return True, f"Saved PDF -> {pdf_path.name}"

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
            gallery, gallery_id, media_id, gallery_dir, concurrency, cover_dest, cover_ext
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
            return True, f"Saved PDF -> {folder_name}/{pdf_path.name}"
        return True, f"Saved {total_pages} pages + PDF -> {folder_name}"

    return True, f"Downloaded {total_pages} pages -> {folder_name}"
