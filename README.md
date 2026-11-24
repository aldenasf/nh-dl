# nhentai-cli

A simple CLI to batch download nhentai galleries from a list of codes.

## Requirements

- Python 3.9+
- Dependencies in `requirements.txt`

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Interactive mode:
```bash
python main.py
```

Flag mode:
```bash
python main.py -i codes.txt -o ./downloads
```

Options:
- `-i, --input, -c, --codes`: Path to codes file
- `-o, --output`: Output directory (default: `./downloads`)
- `-n, --folder-name`: Folder naming scheme (`both`, `title`, `code`) (default: `both`)
- `-j, --concurrency`: Concurrent page downloads (default: `5`)
- `--no-info`: Do not save info.json metadata
