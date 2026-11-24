import asyncio
from datetime import datetime, timezone
from pathlib import Path
import aiohttp
from tqdm import tqdm
import nhentaipy
from nhentaipy.errors import NotFound, NHentaiError

from .dns import enable_doh_resolver
from .storage import (
    get_folder_name,
    create_gallery_dir,
    save_info_json,
    is_gallery_complete,
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

async def download_file(session: aiohttp.ClientSession, url: str, dest_path: Path, semaphore: asyncio.Semaphore) -> bool:
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return True
    
    temp_path = dest_path.with_suffix(dest_path.suffix + '.tmp')
    async with semaphore:
        for attempt in range(3):
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        with open(temp_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(64 * 1024):
                                f.write(chunk)
                        temp_path.replace(dest_path)
                        return True
            except Exception:
                if attempt == 2:
                    if temp_path.exists():
                        temp_path.unlink()
                    return False
                await asyncio.sleep(1)
    return False

def get_page_extension(page) -> str:
    t = getattr(page, 't', '')
    if t in MEDIA_TYPE_EXT:
        return MEDIA_TYPE_EXT[t]
    path = getattr(page, 'path', '')
    if '.' in path:
        return '.' + path.split('.')[-1]
    return '.jpg'

async def download_gallery(
    gallery_id: int,
    output_dir: Path,
    naming_scheme: str = 'both',
    concurrency: int = 5,
    save_info: bool = True
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
    gallery_dir = create_gallery_dir(output_dir, folder_name)

    total_pages = meta["pages"]
    if is_gallery_complete(gallery_dir, total_pages):
        return True, f"Already completed: {folder_name}"

    if save_info:
        save_info_json(gallery_dir, meta)

    media_id = meta["media_id"]
    semaphore = asyncio.Semaphore(concurrency)
    
    pad_width = max(3, len(str(total_pages)))
    tasks = []

    async with aiohttp.ClientSession() as session:
        cover_path_attr = getattr(gallery.images.cover, 'path', '')
        if cover_path_attr:
            cover_url = f"https://t.nhentai.net/{cover_path_attr}"
        else:
            cover_url = f"https://t.nhentai.net/galleries/{media_id}/cover{cover_ext}"
            
        cover_dest = gallery_dir / cover_filename
        cover_task = download_file(session, cover_url, cover_dest, semaphore)

        pbar = tqdm(
            total=total_pages,
            desc=f"[{gallery_id}] Pages",
            unit="p",
            ascii=True,
            leave=False
        )

        async def track_download(url: str, path: Path):
            res = await download_file(session, url, path, semaphore)
            pbar.update(1)
            return res

        for idx, page in enumerate(gallery.images.pages, start=1):
            ext = get_page_extension(page)
            page_url = f"https://i.nhentai.net/galleries/{media_id}/{idx}{ext}"
            filename = f"{str(idx).zfill(pad_width)}{ext}"
            dest = gallery_dir / filename
            tasks.append(track_download(page_url, dest))

        results = await asyncio.gather(*tasks, cover_task)
        pbar.close()

    success_pages = sum(1 for r in results[:-1] if r)
    if success_pages == total_pages:
        return True, f"Downloaded {total_pages} pages -> {folder_name}"
    else:
        return False, f"Incomplete: {success_pages}/{total_pages} pages downloaded"
