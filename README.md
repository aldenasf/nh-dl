# nhentai-cli

A simple CLI to batch download nhentai galleries from a list of codes or your account favorites.

## Requirements

- Python 3.9+
- Dependencies in `requirements.txt`

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### 1. Interactive Mode
Run without arguments to access the interactive menu:
```bash
python main.py
```

### 2. Download from Codes File
```bash
python main.py -i codes.txt -o ./downloads
```

### 3. User Favorites

You can authenticate using either your `access_token` or an `api_key`. Set it in `.env`:
```bash
NHENTAI_TOKEN=your_access_token_here
# or
NHENTAI_API_KEY=your_api_key_here
```
Or pass directly with `--token` or `--api-key`.

#### Export favorites to a text file:
```bash
python main.py --export-favorites my_favorites.txt
```

#### Download all favorites directly:
```bash
python main.py --download-favorites -o ./downloads
```

## Options

- `-i, --input, -c, --codes`: Path to codes file
- `-o, --output`: Output directory (default: `./downloads`)
- `-n, --folder-name`: Folder naming scheme (`both`, `title`, `code`) (default: `both`)
- `-j, --concurrency`: Concurrent page downloads (default: `5`)
- `--no-info`: Do not save info.json metadata
- `--export-favorites FILE`: Export user favorite IDs to specified file
- `--download-favorites`: Fetch user favorites and download them directly
- `--sessionid SESSIONID`: nhentai sessionid cookie
