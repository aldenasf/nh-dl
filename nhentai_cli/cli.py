import argparse
import re
from pathlib import Path
from colorama import Fore, Style, init

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
    print(f"{Fore.CYAN}--- nhentai-cli setup ---{Style.RESET_ALL}")
    
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

    parsed = parser.parse_args()

    if parsed.input is None:
        return prompt_interactive()

    return {
        "input": parsed.input,
        "output": parsed.output,
        "folder_name": parsed.folder_name,
        "concurrency": parsed.concurrency,
        "save_info": not parsed.no_info
    }
