import asyncio
import sys
from pathlib import Path
from colorama import Fore, Style

from nhentai_cli.cli import (
    get_args,
    load_codes_from_file,
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

async def download_codes_list(codes: list[int], config: dict):
    total = len(codes)
    print_info(f"Queued {total} codes for download.")
    print_info(f"Output folder: {config['output'].resolve()}")
    print("-" * 50)

    succeeded = 0
    failed = []

    for index, code in enumerate(codes, start=1):
        print(f"{Fore.MAGENTA}[{index}/{total}]{Style.RESET_ALL} Processing {Fore.CYAN}{code}{Style.RESET_ALL}...")
        ok, message = await download_gallery(
            gallery_id=code,
            output_dir=config["output"],
            naming_scheme=config["folder_name"],
            concurrency=config["concurrency"],
            save_info=config["save_info"]
        )

        if ok:
            print_success(message)
            succeeded += 1
        else:
            print_error(f"[{code}] {message}")
            failed.append(code)

    print("=" * 50)
    print(f"Batch completed: {succeeded}/{total} succeeded.")
    
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

    all_ids = []
    print_info("Fetching favorite galleries...")
    try:
        for page_num, batch in enumerate(fetch_all_favorite_ids(client), start=1):
            all_ids.extend(batch)
            print_info(f"Page {page_num}: retrieved {len(batch)} favorites (Total: {len(all_ids)})")
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

    if not all_ids:
        print_warning("No favorites found on your account.")
        return

    await download_codes_list(all_ids, config)

async def run_batch():
    try:
        config = get_args()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)

    mode = config.get("mode")

    if mode == "export_favorites":
        handle_export_favorites(config)
        return

    if mode == "download_favorites":
        await handle_download_favorites(config)
        return

    try:
        codes = load_codes_from_file(config["input"])
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

    if not codes:
        print_info("No codes found in file.")
        sys.exit(0)

    await download_codes_list(codes, config)

def main():
    try:
        asyncio.run(run_batch())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
