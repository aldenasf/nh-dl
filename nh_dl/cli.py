import argparse
import os
import re
from pathlib import Path
from dotenv import load_dotenv
import questionary

from .state import DEFAULT_STATE, load_state
from .ui import (
    QUESTIONARY_STYLE,
    print_banner,
    print_error,
    print_info,
    print_success,
    print_warning,
)

load_dotenv()


def parse_code_token(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    match = re.search(r'(\d+)', token)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def parse_codes_text(text: str) -> list[int]:
    codes = []
    seen = set()
    for raw_line in text.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line:
            continue
        for token in line.split(','):
            code = parse_code_token(token)
            if code is not None and code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def parse_codes(raw_input: str) -> list[int]:
    cleaned = raw_input.strip(' "\'')
    if not cleaned:
        return []

    candidate = Path(cleaned)
    if candidate.is_file():
        with open(candidate, 'r', encoding='utf-8') as f:
            return parse_codes_text(f.read())

    is_inline_list = ',' in cleaned or '\n' in cleaned
    is_url = bool(re.match(r'^https?://', cleaned, re.IGNORECASE))
    if not is_inline_list and not is_url and (cleaned.lower().endswith('.txt') or '/' in cleaned or '\\' in cleaned):
        raise FileNotFoundError(f"File not found: {cleaned}")

    return parse_codes_text(cleaned)


def load_codes_from_file(file_path: Path) -> list[int]:
    return parse_codes(str(file_path))


def _ask_or_abort(prompt_obj):
    result = prompt_obj.ask()
    if result is None:
        raise KeyboardInterrupt
    return result


def prompt_interactive() -> dict:
    state = load_state()

    print_banner("Interactive Mode")

    mode = _ask_or_abort(
        questionary.select(
            "Select mode:",
            choices=[
                questionary.Choice("Download from codes file or list", value="download_file"),
                questionary.Choice("Download all user favorites directly", value="download_favorites"),
                questionary.Choice("Export user favorites to a .txt file", value="export_favorites"),
                questionary.Choice("Launch local web reader", value="serve"),
            ],
            style=QUESTIONARY_STYLE,
        )
    )

    if mode == "serve":
        out_str = _ask_or_abort(
            questionary.path(
                "Downloads directory:",
                default=state["output"],
                only_directories=True,
                style=QUESTIONARY_STYLE,
            )
        ).strip(' "\'')
        port_str = _ask_or_abort(
            questionary.text(
                "Port:",
                default="8080",
                validate=lambda val: (val.isdigit() and 1 <= int(val) <= 65535) or "Enter a port between 1 and 65535",
                style=QUESTIONARY_STYLE,
            )
        ).strip()
        return {
            "mode": "serve",
            "_interactive": True,
            "output": Path(out_str) if out_str else Path(state["output"]),
            "output_explicit": True,
            "port": int(port_str),
        }

    if mode in ("download_favorites", "export_favorites"):
        env_token = os.environ.get("NHENTAI_TOKEN") or os.environ.get("NHENTAI_SESSION_ID", "")
        token_label = (
            "Enter nhentai access_token (leave blank to use .env):"
            if env_token
            else "Enter nhentai access_token:"
        )
        raw_token = _ask_or_abort(
            questionary.password(token_label, style=QUESTIONARY_STYLE)
        ).strip(' "\'')
        token = raw_token or env_token

        if mode == "download_favorites":
            out_str = _ask_or_abort(
                questionary.path(
                    "Output directory:",
                    default=state["output"],
                    only_directories=True,
                    style=QUESTIONARY_STYLE,
                )
            ).strip(' "\'')
            fmt = _ask_or_abort(
                questionary.select(
                    "Output format:",
                    choices=["image", "pdf", "both"],
                    default=state["format"],
                    style=QUESTIONARY_STYLE,
                )
            )
            flat = (
                _ask_or_abort(
                    questionary.confirm(
                        "Flat PDF output (no subfolders)?",
                        default=state["flat"],
                        style=QUESTIONARY_STYLE,
                    )
                )
                if fmt in ("pdf", "both")
                else False
            )
            return {
                "mode": "download_favorites",
                "_interactive": True,
                "token": token,
                "output": Path(out_str) if out_str else Path(state["output"]),
                "folder_name": state["folder_name"],
                "format": fmt,
                "flat": flat,
                "concurrency": state["concurrency"],
                "save_info": True,
            }

        out_txt = _ask_or_abort(
            questionary.path(
                "Save favorites to:",
                default="favorites.txt",
                style=QUESTIONARY_STYLE,
            )
        ).strip(' "\'')
        return {
            "mode": "export_favorites",
            "_interactive": True,
            "token": token,
            "export_file": Path(out_txt) if out_txt else Path("favorites.txt"),
        }

    last_input = state["input"]
    while True:
        raw = _ask_or_abort(
            questionary.path(
                "Codes file or comma-separated codes/URLs:",
                default=last_input,
                style=QUESTIONARY_STYLE,
            )
        ).strip(' "\'')
        if not raw:
            print_error("Input cannot be empty.")
            continue
        try:
            codes = parse_codes(raw)
        except FileNotFoundError as e:
            print_error(str(e))
            continue
        if not codes:
            print_error("No valid codes found in input.")
            continue
        codes_input = raw
        break

    out_str = _ask_or_abort(
        questionary.path(
            "Output directory:",
            default=state["output"],
            only_directories=True,
            style=QUESTIONARY_STYLE,
        )
    ).strip(' "\'')
    output_dir = Path(out_str) if out_str else Path(state["output"])

    scheme = _ask_or_abort(
        questionary.select(
            "Folder naming strategy:",
            choices=["both", "title", "code"],
            default=state["folder_name"],
            style=QUESTIONARY_STYLE,
        )
    )
    fmt = _ask_or_abort(
        questionary.select(
            "Output format:",
            choices=["image", "pdf", "both"],
            default=state["format"],
            style=QUESTIONARY_STYLE,
        )
    )
    flat = (
        _ask_or_abort(
            questionary.confirm(
                "Flat PDF output (no subfolders)?",
                default=state["flat"],
                style=QUESTIONARY_STYLE,
            )
        )
        if fmt in ("pdf", "both")
        else False
    )

    conc_str = _ask_or_abort(
        questionary.text(
            "Concurrent page downloads:",
            default=str(state["concurrency"]),
            validate=lambda val: (val.isdigit() and int(val) > 0) or "Enter a positive integer",
            style=QUESTIONARY_STYLE,
        )
    ).strip()
    concurrency = int(conc_str)

    return {
        "mode": "download_file",
        "_interactive": True,
        "input": codes_input,
        "output": output_dir,
        "folder_name": scheme,
        "format": fmt,
        "flat": flat,
        "concurrency": concurrency,
        "save_info": True,
    }


def get_args() -> dict:
    parser = argparse.ArgumentParser(
        prog="nh-dl",
        description="Batch download nhentai galleries as images or PDFs.",
        epilog=(
            "examples:\n"
            "  python main.py                          # interactive setup\n"
            "  python main.py -i codes.txt -f pdf      # batch export to PDF\n"
            "  python main.py -i 177013,228922 -j 8    # inline codes with 8 workers\n"
            "  python main.py --download-favorites     # sync account favorites\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    io_group = parser.add_argument_group("input & output")
    io_group.add_argument('-i', '--input', '-c', '--codes', type=str, help="path to codes file or comma-separated codes/URLs")
    io_group.add_argument('-o', '--output', type=Path, default=None, help="output directory (default: ./downloads)")
    io_group.add_argument('--last', action='store_true', help="reuse last saved settings")

    fmt_group = parser.add_argument_group("download & formatting")
    fmt_group.add_argument('-n', '--folder-name', choices=['both', 'title', 'code'], default=None, help="folder naming strategy (default: both)")
    fmt_group.add_argument('-f', '--format', choices=['image', 'pdf', 'both'], default=None, help="output format (default: image)")
    fmt_group.add_argument('--flat', action='store_true', default=None, help="save PDF directly in output directory without subfolders")
    fmt_group.add_argument('-j', '--concurrency', type=int, default=None, help="number of concurrent page downloads (default: 5)")
    fmt_group.add_argument('--no-info', action='store_true', help="skip saving info.json")

    fav_group = parser.add_argument_group("favorites & authentication")
    fav_group.add_argument('--export-favorites', type=Path, metavar="FILE", help="fetch favorites and export codes to a .txt file")
    fav_group.add_argument('--download-favorites', action='store_true', help="fetch favorites and immediately download all of them")
    fav_group.add_argument('--full-sync', action='store_true', help="fetch all favorite pages instead of stopping at already-downloaded ones")
    fav_group.add_argument('--token', '--sessionid', type=str, default=os.environ.get("NHENTAI_TOKEN") or os.environ.get("NHENTAI_SESSION_ID"), help="nhentai access_token")
    fav_group.add_argument('--api-key', '--key', type=str, default=os.environ.get("NHENTAI_API_KEY"), help="nhentai API key")

    web_group = parser.add_argument_group("local web reader")
    web_group.add_argument('--serve', action='store_true', help="launch local offline web reader for downloaded galleries")
    web_group.add_argument('--port', type=int, default=8080, help="port for local web reader (default: 8080)")

    parsed = parser.parse_args()
    if not (1 <= parsed.port <= 65535):
        raise ValueError("Port must be between 1 and 65535.")

    base = load_state() if parsed.last else dict(DEFAULT_STATE)

    output_dir = parsed.output if parsed.output is not None else Path(base["output"])
    folder_name = parsed.folder_name if parsed.folder_name is not None else base["folder_name"]
    output_format = parsed.format if parsed.format is not None else base["format"]
    flat = parsed.flat if parsed.flat is not None else base["flat"]
    concurrency = parsed.concurrency if parsed.concurrency is not None else base["concurrency"]

    if parsed.serve:
        return {
            "mode": "serve",
            "output": output_dir,
            "output_explicit": parsed.output is not None,
            "port": parsed.port,
        }

    auth_kwargs = {"token": parsed.token, "api_key": parsed.api_key}

    if parsed.export_favorites:
        return {
            "mode": "export_favorites",
            **auth_kwargs,
            "export_file": parsed.export_favorites,
        }

    if parsed.download_favorites:
        return {
            "mode": "download_favorites",
            **auth_kwargs,
            "output": output_dir,
            "folder_name": folder_name,
            "format": output_format,
            "flat": flat,
            "full_sync": parsed.full_sync,
            "concurrency": concurrency,
            "save_info": not parsed.no_info,
        }

    raw_input = parsed.input if parsed.input is not None else (base["input"] if parsed.last else None)
    if not raw_input:
        if parsed.last:
            raise ValueError("No saved input found in .nh_dl.json. Pass -i/--input at least once.")
        return prompt_interactive()

    return {
        "mode": "download_file",
        "input": raw_input,
        "output": output_dir,
        "folder_name": folder_name,
        "format": output_format,
        "flat": flat,
        "concurrency": concurrency,
        "save_info": not parsed.no_info,
    }
