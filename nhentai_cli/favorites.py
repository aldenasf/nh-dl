import time
from pathlib import Path
from typing import Generator
import nhentaipy
from nhentaipy.errors import NHentaiError, Unauthorized

from .dns import enable_doh_resolver

enable_doh_resolver()

def create_authenticated_client(
    token: str | None = None,
    api_key: str | None = None
) -> nhentaipy.NHentai:
    raw = (token or api_key or "").strip()
    if raw.startswith("User "):
        raw = raw[5:].strip()
    elif raw.startswith("Key "):
        raw = raw[4:].strip()

    if api_key and not token:
        return nhentaipy.NHentai(key=raw)
    return nhentaipy.NHentai(token=raw)

def fetch_all_favorite_ids(
    client: nhentaipy.NHentai,
    max_pages: int | None = None,
    delay: float = 1.0
) -> Generator[list[int], None, None]:
    page = 1
    while True:
        try:
            res = client.user.get_favorites(page=page)
        except Unauthorized:
            raise RuntimeError("Authentication failed. Please check your sessionid or API token.")
        except NHentaiError as e:
            raise RuntimeError(f"Failed to fetch favorites (page {page}): {e}")

        if not res.data:
            break

        page_ids = [g.id for g in res.data]
        yield page_ids

        if not res.has_next or (res.last_page and page >= res.last_page) or (res.per_page and len(res.data) < res.per_page):
            break

        if max_pages and page >= max_pages:
            break

        page += 1
        time.sleep(delay)

def export_favorites_to_file(codes: list[int], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for code in codes:
            f.write(f"{code}\n")
