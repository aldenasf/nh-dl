# nh-dl

A lightweight CLI batch downloader and offline local web reader for nhentai galleries.

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

### 2. Download from Codes File or Inline List
Supports codes/URLs split by newlines, commas, or both:
```bash
python main.py -i codes.txt -o ./downloads -f both
python main.py -i "123456, 234567" -f pdf
python main.py --last
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

### 4. Local Web Reader

Browse, search, and read downloaded galleries completely offline in a dark nhentai-styled local web UI (`127.0.0.1`, read-only on your gallery files):
```bash
python main.py --serve
python main.py --serve -o ./downloads --port 8080
```

- **Search & Autocomplete**: Filter by tags, artists, parodies, characters, groups, languages, titles (`title:"..."` / `jtitle:"..."`), page count (`pages:N`), or download date (`uploaded:Nd`), with `-` exclusion, search history, and cursor parameter actions.
- **Library & Cards**: Language flags, full-title hover expansion, separate field + ascending/descending sort, and Tags/Artists directories.
- **Reader**: Vertical scroll and single-page modes, fit options (`width` / `height` / `original`), keyboard shortcuts (`←`/`→`, `A`/`D`, `M`, `F`, `Esc`), and local bookmarks/progress saved to `.nh_dl_web.json`.
- **Settings**: Switch or browse library folders and rescan on demand without restarting.

## Options

- `-i, --input, -c, --codes`: Path to codes file or comma-separated codes/URLs
- `-o, --output`: Output directory (default: `./downloads`)
- `-n, --folder-name`: Folder naming scheme (`both`, `title`, `code`) (default: `both`)
- `-f, --format`: Output format (`image`, `pdf`, `both`) (default: `image`)
- `--flat`: Save PDF directly in output directory without creating subfolders
- `-j, --concurrency`: Concurrent page downloads (default: `5`)
- `--last`: Reuse last saved settings from `.nh_dl.json`
- `--no-info`: Do not save info.json metadata
- `--export-favorites FILE`: Export user favorite IDs to specified file
- `--download-favorites`: Fetch user favorites and download them directly
- `--full-sync`: Check all favorite pages instead of stopping at already-downloaded ones
- `--token`: nhentai access_token
- `--api-key`: nhentai API key
- `--serve`: Launch local offline web reader for downloaded galleries
- `--port`: Port for local web reader (default: `8080`)
