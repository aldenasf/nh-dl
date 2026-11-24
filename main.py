import asyncio
import sys
from pathlib import Path
from colorama import Fore, Style

from nhentai_cli.cli import (
    get_args,
    load_codes_from_file,
    print_info,
    print_success,
    print_error,
)
from nhentai_cli.downloader import download_gallery

async def run_batch():
    try:
        config = get_args()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)

    try:
        codes = load_codes_from_file(config["input"])
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

    if not codes:
        print_info("No codes found in file.")
        sys.exit(0)

    total = len(codes)
    print_info(f"Loaded {total} codes from {config['input']}")
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

def main():
    try:
        asyncio.run(run_batch())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
