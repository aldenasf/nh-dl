import asyncio
import sys
from pathlib import Path
import aiohttp
import nhentaipy

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
from nhentai_cli.ui import (
    BatchLogBuffer,
    console,
    create_download_progress,
    print_banner,
    print_batch_summary,
    print_rule,
)


async def download_codes_list(codes: list[int], config: dict, completed_ids: set[int] | None = None):
    total = len(codes)
    output_dir = config["output"]
    output_format = config.get("format", "image")
    flat = config.get("flat", False)

    if completed_ids is None:
        completed_ids = scan_completed_ids(output_dir, output_format, flat)

    print_info(f"Queued [bold]{total}[/bold] codes for download.")
    print_info(f"Output folder: [dim]{output_dir.resolve()}[/dim]")
    print_rule()

    log_buffer = BatchLogBuffer(total=total, output_dir=output_dir)
    succeeded = 0
    skipped = 0
    failed = []

    api_client = nhentaipy.NHentai()
    async with aiohttp.ClientSession() as http_session:
        with create_download_progress(log_buffer=log_buffer) as progress:
            batch_task = progress.add_task("[bold magenta]Batch[/bold magenta]", total=total, speed="")

            for index, code in enumerate(codes, start=1):
                if code in completed_ids:
                    entry = log_buffer.add("skip", index, total, code, "already completed locally, skipping.")
                    progress.console.print(log_buffer.format_entry(entry))
                    succeeded += 1
                    skipped += 1
                    progress.advance(batch_task)
                    continue

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
                    progress=progress,
                )

                if ok:
                    entry = log_buffer.add("success", index, total, code, message)
                    progress.console.print(log_buffer.format_entry(entry))
                    succeeded += 1
                else:
                    entry = log_buffer.add("error", index, total, code, message)
                    progress.console.print(log_buffer.format_entry(entry))
                    failed.append(code)

                progress.advance(batch_task)

    failed_file: Path | None = None
    if failed:
        failed_file = Path("failed_codes.txt")
        with open(failed_file, "w", encoding="utf-8") as f:
            for c in failed:
                f.write(f"{c}\n")

    print_batch_summary(
        total=total,
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        output_dir=output_dir,
        failed_file=failed_file,
    )


def handle_export_favorites(config: dict):
    token = config.get("token")
    api_key = config.get("api_key")
    if not token and not api_key:
        print_error("Missing credentials. Provide via --token, --api-key, or .env (NHENTAI_TOKEN / NHENTAI_API_KEY).")
        sys.exit(1)

    try:
        with console.status("[cyan]Connecting to nhentai...[/cyan]", spinner="dots"):
            client = create_authenticated_client(token=token, api_key=api_key)
            me = client.user.get_me()
        print_info(f"Authenticated as [bold green]{me.username}[/bold green] [dim](ID: {me.id})[/dim]")
    except Exception as e:
        print_error(f"Authentication failed: {e}")
        sys.exit(1)

    all_ids = []
    try:
        with console.status("[cyan]Fetching favorite galleries...[/cyan]", spinner="dots") as status:
            for page_num, batch in enumerate(fetch_all_favorite_ids(client), start=1):
                all_ids.extend(batch)
                status.update(f"[cyan]Fetching favorites... Page {page_num} ({len(all_ids)} total)[/cyan]")
        print_info(f"Retrieved [bold]{len(all_ids)}[/bold] favorite galleries.")
    except Exception as e:
        print_error(str(e))
        sys.exit(1)

    export_path = config["export_file"]
    export_favorites_to_file(all_ids, export_path)
    print_success(f"Exported {len(all_ids)} favorites to [dim]{export_path.resolve()}[/dim]")


async def handle_download_favorites(config: dict):
    token = config.get("token")
    api_key = config.get("api_key")
    if not token and not api_key:
        print_error("Missing credentials. Provide via --token, --api-key, or .env (NHENTAI_TOKEN / NHENTAI_API_KEY).")
        sys.exit(1)

    try:
        with console.status("[cyan]Connecting to nhentai...[/cyan]", spinner="dots"):
            client = create_authenticated_client(token=token, api_key=api_key)
            me = client.user.get_me()
        print_info(f"Authenticated as [bold green]{me.username}[/bold green] [dim](ID: {me.id})[/dim]")
    except Exception as e:
        print_error(f"Authentication failed: {e}")
        sys.exit(1)

    completed_ids = scan_completed_ids(
        config["output"], config.get("format", "image"), config.get("flat", False)
    )
    full_sync = config.get("full_sync", False)

    all_ids = []
    try:
        with console.status("[cyan]Fetching favorite galleries...[/cyan]", spinner="dots") as status:
            for page_num, batch in enumerate(fetch_all_favorite_ids(client), start=1):
                all_ids.extend(batch)
                status.update(f"[cyan]Fetching favorites... Page {page_num} ({len(all_ids)} total)[/cyan]")
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


async def run_batch(config: dict | None = None):
    if config is None:
        config = get_args()

    mode = config.get("mode")
    if not config.pop("_interactive", False):
        print_banner()

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
        config = get_args()
        asyncio.run(run_batch(config))
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Aborted.[/yellow]")
        sys.exit(0)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
