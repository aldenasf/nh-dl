import asyncio
import sys
from pathlib import Path
import aiohttp
import nhentaipy
from colorama import Fore, Style

from nhentai_cli.cli import (
    get_args,
    parse_codes,
    print_info,
    print_success,
    print_warning,
    print_error,
)
from nhentai_cli.downloader import download_gallery
from nhentai_cli.favorites import (
    create_authenticated_client,
    fetch_all_favorite_ids,
    export_favorites_to_file,
)
from nhentai_cli.state import save_state
from nhentai_cli.storage import scan_completed_ids


async def download_codes_list(codes: list[int], config: dict, completed_ids: set[int] | None = None):
    total = len(codes)
    output_dir = config["output"]
    output_format = config.get("format", "image")
    flat = config.get("flat", False)

    if completed_ids is None:
        completed_ids = scan_completed_ids(output_dir, output_format, flat)

    print_info(f"Queued {total} codes for download.")
    print_info(f"Output folder: {output_dir.resolve()}")
    print("-" * 50)

    succeeded = 0
    skipped = 0
    failed = []

    api_client = nhentaipy.NHentai()
    async with aiohttp.ClientSession() as http_session:
        for index, code in enumerate(codes, start=1):
            if code in completed_ids:
                print(f"{Fore.MAGENTA}[{index}/{total}]{Style.RESET_ALL} {Fore.CYAN}{code}{Style.RESET_ALL} already completed locally, skipping.")
                succeeded += 1
                skipped += 1
                continue

            print(f"{Fore.MAGENTA}[{index}/{total}]{Style.RESET_ALL} Processing {Fore.CYAN}{code}{Style.RESET_ALL}...")
            ok, message = await download_gallery(
                gallery_id=code,
                output_dir=output_dir,
                naming_scheme=config["folder_name"],
                concurrency=config["concurrency"],
                save_info=config["save_info"],
                output_format=output_format,
                flat=flat,
                client=api_client,
                session=http_session,
            )

            if ok:
                print_success(message)
                succeeded += 1
            else:
                print_error(f"[{code}] {message}")
                failed.append(code)

    print("=" * 50)
    print(f"Batch completed: {succeeded}/{total} succeeded ({skipped} skipped locally).")
    
    if failed:
        failed_file = Path("failed_codes.txt")
        with open(failed_file, "w", encoding="utf-8") as f:
            for c in failed:
                f.write(f"{c}\n")
        print_error(f"{len(failed)} failed. Saved list to {failed_file}")
    else:
        print_success("All downloads finished without errors.")
    print("=" * 50)

def handle_export_favorites(config: dict):
    token = config.get("token")
    api_key = config.get("api_key")
    if not token and not api_key:
        print_error("Missing credentials. Provide via --token, --api-key, or .env (NHENTAI_TOKEN / NHENTAI_API_KEY).")
        sys.exit(1)

    print_info("Connecting to nhentai with credentials...")
    try:
        client = create_authenticated_client(token=token, api_key=api_key)
        me = client.user.get_me()
        print_info(f"Authenticated as user: {Fore.GREEN}{me.username}{Style.RESET_ALL} (ID: {me.id})")
    except Exception as e:
        print_error(f"Authentication failed: {e}")
        sys.exit(1)

    all_ids = []
    print_info("Fetching favorite galleries...")
    try:
        for page_num, batch in enumerate(fetch_all_favorite_ids(client), start=1):
            all_ids.extend(batch)
            print_info(f"Page {page_num}: retrieved {len(batch)} favorites (Total: {len(all_ids)})")
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

    export_path = config["export_file"]
    export_favorites_to_file(all_ids, export_path)
    print_success(f"Exported {len(all_ids)} favorites to {export_path.resolve()}")

async def handle_download_favorites(config: dict):
    token = config.get("token")
    api_key = config.get("api_key")
    if not token and not api_key:
        print_error("Missing credentials. Provide via --token, --api-key, or .env (NHENTAI_TOKEN / NHENTAI_API_KEY).")
        sys.exit(1)

    print_info("Connecting to nhentai with credentials...")
    try:
        client = create_authenticated_client(token=token, api_key=api_key)
        me = client.user.get_me()
        print_info(f"Authenticated as user: {Fore.GREEN}{me.username}{Style.RESET_ALL} (ID: {me.id})")
    except Exception as e:
        print_error(f"Authentication failed: {e}")
        sys.exit(1)

    completed_ids = scan_completed_ids(
        config["output"], config.get("format", "image"), config.get("flat", False)
    )
    full_sync = config.get("full_sync", False)

    all_ids = []
    print_info("Fetching favorite galleries...")
    try:
        for page_num, batch in enumerate(fetch_all_favorite_ids(client), start=1):
            all_ids.extend(batch)
            print_info(f"Page {page_num}: retrieved {len(batch)} favorites (Total: {len(all_ids)})")
            if not full_sync and batch and all(gid in completed_ids for gid in batch):
                print_info("All favorites on this page are already downloaded locally. Stopping sync (use --full-sync to check all pages).")
                break
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

    if not all_ids:
        print_warning("No favorites found on your account.")
        return

    await download_codes_list(all_ids, config, completed_ids=completed_ids)

async def run_batch():
    try:
        config = get_args()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

    mode = config.get("mode")

    if mode == "export_favorites":
        handle_export_favorites(config)
        return

    if mode == "download_favorites":
        save_state(config)
        await handle_download_favorites(config)
        return

    try:
        codes = parse_codes(str(config["input"]))
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

    if not codes:
        print_info("No codes found in input.")
        sys.exit(0)

    save_state(config)
    await download_codes_list(codes, config)

def main():
    try:
        asyncio.run(run_batch())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
