import argparse
import os
import re
from pathlib import Path
from colorama import Fore, Style, init
from dotenv import load_dotenv

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

def parse_code_line(line: str) -> int | None:
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    match = re.search(r'(\d+)', line)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None

def load_codes_from_file(file_path: Path) -> list[int]:
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    codes = []
    seen = set()
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            code = parse_code_line(line)
            if code is not None and code not in seen:
                seen.add(code)
                codes.append(code)
    return codes

def prompt_interactive() -> dict:
    print(f"{Fore.CYAN}--- nhentai-cli ---{Style.RESET_ALL}")
    print("1. Download from codes file")
    print("2. Download all user favorites directly")
    print("3. Export user favorites to a .txt file")
    
    choice = input(f"{Fore.YELLOW}Select mode (1/2/3) [1]: {Style.RESET_ALL}").strip()
    
    if choice in ('2', '3'):
        env_token = os.environ.get("NHENTAI_TOKEN") or os.environ.get("NHENTAI_SESSION_ID", "")
        prompt_text = f"Enter nhentai access_token [{env_token}]: " if env_token else "Enter nhentai access_token: "
        token = input(f"{Fore.YELLOW}{prompt_text}{Style.RESET_ALL}").strip(' "\'') or env_token
        
        if choice == '2':
            out_str = input(f"{Fore.YELLOW}Output directory [./downloads]: {Style.RESET_ALL}").strip(' "\'')
            return {
                "mode": "download_favorites",
                "token": token,
                "output": Path(out_str) if out_str else Path("./downloads"),
                "folder_name": "both",
                "concurrency": 5,
                "save_info": True
            }
        else:
            out_txt = input(f"{Fore.YELLOW}Save favorites to [favorites.txt]: {Style.RESET_ALL}").strip(' "\'')
            return {
                "mode": "export_favorites",
                "token": token,
                "export_file": Path(out_txt) if out_txt else Path("favorites.txt")
            }

    while True:
        input_str = input(f"{Fore.YELLOW}Enter codes file path: {Style.RESET_ALL}").strip(' "\'')
        if not input_str:
            print_error("File path cannot be empty.")
            continue
        p = Path(input_str)
        if not p.exists():
            print_error(f"File does not exist: {p}")
            continue
        codes_path = p
        break

    out_str = input(f"{Fore.YELLOW}Output directory [./downloads]: {Style.RESET_ALL}").strip(' "\'')
    output_dir = Path(out_str) if out_str else Path("./downloads")

    scheme = input(f"{Fore.YELLOW}Folder naming (both/title/code) [both]: {Style.RESET_ALL}").strip().lower()
    if scheme not in ('both', 'title', 'code'):
        scheme = 'both'

    conc_str = input(f"{Fore.YELLOW}Concurrent downloads [5]: {Style.RESET_ALL}").strip()
    concurrency = int(conc_str) if conc_str.isdigit() and int(conc_str) > 0 else 5

    return {
        "mode": "download_file",
        "input": codes_path,
        "output": output_dir,
        "folder_name": scheme,
        "concurrency": concurrency,
        "save_info": True
    }

def get_args() -> dict:
    parser = argparse.ArgumentParser(
        description="Simple CLI to batch download nhentai galleries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-i', '--input', '-c', '--codes', type=Path, help="Path to text file containing codes/URLs")
    parser.add_argument('-o', '--output', type=Path, default=Path("./downloads"), help="Output directory")
    parser.add_argument('-n', '--folder-name', choices=['both', 'title', 'code'], default='both', help="Folder naming strategy")
    parser.add_argument('-j', '--concurrency', type=int, default=5, help="Number of concurrent page downloads")
    parser.add_argument('--no-info', action='store_true', help="Skip saving info.json")

    # Favorites options
    group = parser.add_argument_group("favorites options")
    group.add_argument('--export-favorites', type=Path, metavar="FILE", help="Fetch favorites and export codes to a .txt file")
    group.add_argument('--download-favorites', action='store_true', help="Fetch favorites and immediately download all of them")
    group.add_argument('--token', '--sessionid', type=str, default=os.environ.get("NHENTAI_TOKEN") or os.environ.get("NHENTAI_SESSION_ID"), help="nhentai access_token")
    group.add_argument('--api-key', '--key', type=str, default=os.environ.get("NHENTAI_API_KEY"), help="nhentai API key")

    parsed = parser.parse_args()

    auth_kwargs = {"token": parsed.token, "api_key": parsed.api_key}

    if parsed.export_favorites:
        return {
            "mode": "export_favorites",
            **auth_kwargs,
            "export_file": parsed.export_favorites
        }

    if parsed.download_favorites:
        return {
            "mode": "download_favorites",
            **auth_kwargs,
            "output": parsed.output,
            "folder_name": parsed.folder_name,
            "concurrency": parsed.concurrency,
            "save_info": not parsed.no_info
        }

    if parsed.input is None:
        return prompt_interactive()

    return {
        "mode": "download_file",
        "input": parsed.input,
        "output": parsed.output,
        "folder_name": parsed.folder_name,
        "concurrency": parsed.concurrency,
        "save_info": not parsed.no_info
    }
