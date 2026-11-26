import argparse
import os
import re
from pathlib import Path
from colorama import Fore, Style, init
from dotenv import load_dotenv

from .state import DEFAULT_STATE, load_state

load_dotenv()
init(autoreset=True)


def print_info(text: str) -> None:
    print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} {text}")


def print_success(text: str) -> None:
    print(f"{Fore.GREEN}[SUCCESS]{Style.RESET_ALL} {text}")


def print_warning(text: str) -> None:
    print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL} {text}")


def print_error(text: str) -> None:
    print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {text}")


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


def _prompt_choice(label: str, valid: tuple[str, ...], default: str) -> str:
    val = input(f"{Fore.YELLOW}{label} [{default}]: {Style.RESET_ALL}").strip().lower()
    return val if val in valid else default


def _prompt_bool(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"{Fore.YELLOW}{label} ({hint}): {Style.RESET_ALL}").strip().lower()
    if val in ('y', 'yes'):
        return True
    if val in ('n', 'no'):
        return False
    return default


def prompt_interactive() -> dict:
    state = load_state()

    print(f"{Fore.CYAN}--- nhentai-cli ---{Style.RESET_ALL}")
    print("1. Download from codes file or list")
    print("2. Download all user favorites directly")
    print("3. Export user favorites to a .txt file")

    choice = input(f"{Fore.YELLOW}Select mode (1/2/3) [1]: {Style.RESET_ALL}").strip()

    if choice in ('2', '3'):
        env_token = os.environ.get("NHENTAI_TOKEN") or os.environ.get("NHENTAI_SESSION_ID", "")
        prompt_text = f"Enter nhentai access_token [{env_token}]: " if env_token else "Enter nhentai access_token: "
        token = input(f"{Fore.YELLOW}{prompt_text}{Style.RESET_ALL}").strip(' "\'') or env_token

        if choice == '2':
            out_str = input(f"{Fore.YELLOW}Output directory [{state['output']}]: {Style.RESET_ALL}").strip(' "\'')
            fmt = _prompt_choice("Output format (image/pdf/both)", ('image', 'pdf', 'both'), state['format'])
            flat = _prompt_bool("Flat PDF output (no subfolders)", state['flat']) if fmt in ('pdf', 'both') else False
            return {
                "mode": "download_favorites",
                "token": token,
                "output": Path(out_str) if out_str else Path(state['output']),
                "folder_name": state['folder_name'],
                "format": fmt,
                "flat": flat,
                "concurrency": state['concurrency'],
                "save_info": True,
            }
        else:
            out_txt = input(f"{Fore.YELLOW}Save favorites to [favorites.txt]: {Style.RESET_ALL}").strip(' "\'')
            return {
                "mode": "export_favorites",
                "token": token,
                "export_file": Path(out_txt) if out_txt else Path("favorites.txt"),
            }

    last_input = state["input"]
    while True:
        prompt_label = f"Enter codes file or list [{last_input}]: " if last_input else "Enter codes file or list: "
        raw = input(f"{Fore.YELLOW}{prompt_label}{Style.RESET_ALL}").strip(' "\'') or last_input
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

    out_str = input(f"{Fore.YELLOW}Output directory [{state['output']}]: {Style.RESET_ALL}").strip(' "\'')
    output_dir = Path(out_str) if out_str else Path(state['output'])

    scheme = _prompt_choice("Folder naming (both/title/code)", ('both', 'title', 'code'), state['folder_name'])
    fmt = _prompt_choice("Output format (image/pdf/both)", ('image', 'pdf', 'both'), state['format'])
    flat = _prompt_bool("Flat PDF output (no subfolders)", state['flat']) if fmt in ('pdf', 'both') else False

    conc_str = input(f"{Fore.YELLOW}Concurrent downloads [{state['concurrency']}]: {Style.RESET_ALL}").strip()
    concurrency = int(conc_str) if conc_str.isdigit() and int(conc_str) > 0 else state['concurrency']

    return {
        "mode": "download_file",
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
        description="Simple CLI to batch download nhentai galleries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-i', '--input', '-c', '--codes', type=str, help="Path to codes file or comma-separated codes/URLs")
    parser.add_argument('-o', '--output', type=Path, default=None, help="Output directory (default: ./downloads)")
    parser.add_argument('-n', '--folder-name', choices=['both', 'title', 'code'], default=None, help="Folder naming strategy (default: both)")
    parser.add_argument('-f', '--format', choices=['image', 'pdf', 'both'], default=None, help="Output format (default: image)")
    parser.add_argument('--flat', action='store_true', default=None, help="Save PDF directly in output directory without subfolders")
    parser.add_argument('-j', '--concurrency', type=int, default=None, help="Number of concurrent page downloads (default: 5)")
    parser.add_argument('--last', action='store_true', help="Reuse last saved settings")
    parser.add_argument('--no-info', action='store_true', help="Skip saving info.json")

    group = parser.add_argument_group("favorites options")
    group.add_argument('--export-favorites', type=Path, metavar="FILE", help="Fetch favorites and export codes to a .txt file")
    group.add_argument('--download-favorites', action='store_true', help="Fetch favorites and immediately download all of them")
    group.add_argument('--full-sync', action='store_true', help="Fetch all favorite pages instead of stopping at already-downloaded ones")
    group.add_argument('--token', '--sessionid', type=str, default=os.environ.get("NHENTAI_TOKEN") or os.environ.get("NHENTAI_SESSION_ID"), help="nhentai access_token")
    group.add_argument('--api-key', '--key', type=str, default=os.environ.get("NHENTAI_API_KEY"), help="nhentai API key")

    parsed = parser.parse_args()
    base = load_state() if parsed.last else dict(DEFAULT_STATE)

    output_dir = parsed.output if parsed.output is not None else Path(base["output"])
    folder_name = parsed.folder_name if parsed.folder_name is not None else base["folder_name"]
    output_format = parsed.format if parsed.format is not None else base["format"]
    flat = parsed.flat if parsed.flat is not None else base["flat"]
    concurrency = parsed.concurrency if parsed.concurrency is not None else base["concurrency"]

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
            raise ValueError("No saved input found in .nhentai_cli.json. Pass -i/--input at least once.")
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
