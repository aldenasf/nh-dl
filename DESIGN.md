# nh-dl Design Specification & Decision Log

## 1. Overview & Goals
A lightweight, non-bloated, offline-first Python CLI tool to batch download nhentai galleries from a text file list of codes/URLs.

### Key Highlights
- **Clean CLI**: Non-bloated, emoji-free, styled with `colorama` ANSI colors and clean ASCII `tqdm` progress bars.
- **Flexible execution**: Fully headless via CLI flags or interactive prompt fallback when executed without flags.
- **Offline Archival & Local Reader Ready**: Downloads all pages, dedicated `cover.jpg`, and structured `info.json` so galleries remain 100% readable even if nhentai goes down, ready for a future local web reader.
- **Git Discipline**: Initialized Git repository with small, clear atomic commits per change.

---

## 2. CLI Specification
- **Command**: `python main.py [FLAGS]`
- **Arguments**:
  - `-i`, `--input`, `-c`, `--codes`: Path to text file containing codes/URLs.
  - `-o`, `--output`: Destination directory for downloads (default: `./downloads`).
  - `-n`, `--folder-name`: Naming format: `both` (default, e.g. `[123456] Title`), `title`, or `code`.
  - `-j`, `--concurrency`: Max concurrent page downloads per gallery (default: `5`).
  - `--no-info`: Skip saving `info.json`.
- **Interactive Fallback**: If `--input` is not provided, interactively prompts user for inputs with clean defaults.

---

## 3. Directory & Metadata Structure
```text
downloads/
└── [123456] Clean Sanitized Title/
    ├── cover.jpg
    ├── 001.jpg
    ├── 002.jpg
    ├── ...
    ├── 045.jpg
    └── info.json
```

### `info.json` Schema
```json
{
  "id": 123456,
  "media_id": "987654",
  "title": {
    "english": "English Title",
    "japanese": "Japanese Title",
    "pretty": "Short Title"
  },
  "artists": ["Artist Name"],
  "parodies": ["Original"],
  "tags": ["tag1", "tag2"],
  "pages": 45,
  "cover": "cover.jpg",
  "downloaded_at": "2026-11-24T23:24:00"
}
```

---

## 4. Error Handling & Recovery
- Safe Windows filename sanitization (removes forbidden characters: `\ / : * ? " < > |`).
- Non-blocking: individual code failures do not abort the batch.
- Generates `failed_codes.txt` containing any failed codes for easy re-runs.
- Resume capability: skips galleries where all pages already exist.

---

## 5. Decision Log
1. **CLI Mode**: Flags-first with interactive prompts fallback when required flags are omitted.
2. **Library**: `nhentaipy-v2` for nhentai API communication.
3. **Architecture**: Modular async architecture (`nh_dl/` package + `main.py`).
4. **Coloring**: `colorama` for cross-platform, zero-bloat ANSI terminal coloring.
5. **Naming**: `--folder-name both` (`[code] title`) as default.
6. **Archival Integrity**: Downloads `cover.jpg` locally alongside pages for 100% offline self-containment.
7. **Future Scope**: Offline web reader backend.

---

## 6. Phase 2 Design: PDF Export, State Persistence, and Flexible Input

### Understanding Summary
- **Goal**: Add PDF export (`--format image|pdf|both`), remembered CLI/interactive settings (`.nhentai_cli.json` and `--last`), and mixed newline/comma/inline input parsing.
- **Non-Goals**: Offline web viewer (deferred to a separate phase), PDF OCR or custom layouts.

### Assumptions & Non-Functional Requirements
- **PDF Engine**: Single-dependency `Pillow` (`PIL.Image`) converts `.webp`/`.png`/`.jpg`/`.gif` pages to `RGB` and writes `<folder_name>.pdf` atomically via `.pdf.tmp`.
- **Security**: `.nhentai_cli.json` is gitignored and never stores `NHENTAI_TOKEN` or `NHENTAI_API_KEY`.
- **Reliability**: Resume logic checks format-specific completion; existing local images are reused to build PDFs without re-downloading.

### Final Design
1. **CLI (`nh_dl/cli.py`)**:
   - `-f, --format {image,pdf,both}` (default `image`).
   - `--last` flag to replay the last saved settings (overridable by explicit flags).
   - `parse_codes(raw_input)`: reads file if path exists, otherwise parses inline string; strips `#` comments, splits by `,` and `\n`, extracts numeric IDs/URLs, deduplicates in order.
2. **State (`nh_dl/state.py`)**:
   - Persists `input`, `output`, `folder_name`, `format`, and `concurrency` to `.nhentai_cli.json`.
   - Pre-fills interactive prompts with saved values.
3. **PDF & Storage (`nh_dl/pdf.py`, `storage.py`, `downloader.py`)**:
   - Saves `<folder_name>.pdf` inside `downloads/<folder_name>/`.
   - Keeps `cover.*` and `info.json` in all modes (`image`, `pdf`, `both`).
   - Deletes page images (`001.*`..`N.*`) after PDF creation only in `pdf` mode.

### Phase 2 Decision Log
1. **Scope**: Implement TODO items 1-3 now; defer offline web viewer to a future phase.
2. **PDF Location**: Store PDF inside the gallery folder alongside `cover.*` and `info.json`.
3. **PDF Library**: Use `Pillow` alone instead of `img2pdf` + `Pillow`, since nhentai serves `.webp` and `Pillow` handles all formats with one dependency.
4. **State Persistence**: Save recent non-sensitive settings to `.nhentai_cli.json` for interactive defaults and `--last` CLI replay.
5. **Input Parsing**: Support mixed newlines, commas, `#` comments, URLs, and inline comma-separated strings.

---

## 7. Phase 3 Design: Reliability, Speed, and Smart Sync

### Understanding Summary
- **Goal**: Speed up large batches and repeat `--download-favorites` runs while improving CDN resilience.
- **Non-Goals**: Offline web viewer, multi-gallery parallel downloads.

### Assumptions & Non-Functional Requirements
- **Performance**: Scan `output_dir` once per batch; skip already-complete galleries locally in <1ms with zero API calls.
- **Scale**: Support 100s-1000s of galleries/favorites without hitting rate limits on incremental syncs.
- **Reliability**: DoH resolves any `*.nhentai.net` subdomain with thread-safe caching; fast-skip verifies completeness against `info.json` or non-empty `.pdf`.

### Final Design
1. **Local Fast-Skip (`nh_dl/storage.py`)**:
   - `scan_completed_ids(output_dir, output_format, flat) -> set[int]` scans `output_dir` once at startup.
2. **Incremental Favorites (`nh_dl/favorites.py`, `cli.py`, `main.py`)**:
   - Stop fetching favorite pages once a full page is already in `completed_ids`; `--full-sync` overrides this.
3. **Shared Clients & CDN Mirrors (`nh_dl/dns.py`, `downloader.py`)**:
   - Reuse one `nhentaipy.NHentai` client (via `asyncio.to_thread`) and one `aiohttp.ClientSession` per batch.
   - Rotate across `i`, `i2`, `i3`, `i5`, `i7.nhentai.net` on network/5xx errors; try alternate extensions once on 404.
4. **Tests (`tests/`)**:
   - Unit tests for local index, incremental sync, mirror rotation, parsing, and PDF export.

### Phase 3 Decision Log
1. **Fast-Skip Strategy**: Single-pass disk scan instead of persistent SQLite/JSON cache, so local deletions or format changes are always respected.
2. **Incremental Sync**: Early-stop on first full page of already-downloaded favorites, with `--full-sync` escape hatch.
3. **CDN Fallback**: Mirror rotation + smart 404 extension fallback instead of retrying the same failing URL.


---

## 7. Phase 4 Design: Resize-Aware Log Redraw

### Understanding Summary
- **Goal**: Dynamically re-render previously printed batch log lines (completed, skipped, failed) alongside the live `Batch` and active doujin progress bars when the terminal is resized horizontally.
- **Mode**: Main terminal buffer (normal scrollback preserved; no alternate screen or TUI).
- **Performance Constraint**: Redraws must not slow down or block concurrent `asyncio` downloads.
- **Non-TTY Fallback**: Disabled automatically when stdout is piped or redirected.
- **Explicit Non-Goals**: Full-screen TUI (`textual`), keyboard scrolling, or preserving pre-run terminal output on resize.

### Assumptions
- **Debounce**: Resize redraws trigger only after terminal width stabilizes for ~150 ms to avoid flicker and redundant writes while dragging.
- **Scale**: Storing structured `LogEntry` records for hundreds or thousands of galleries has negligible memory overhead; a single buffered write takes ~1–2 ms.

### Final Design
1. **`BatchLogBuffer` (`nh_dl/ui.py`)**:
   - Stores header metadata (queued count, output path) and structured `LogEntry(kind, index, total, code, detail)` records.
   - Formats each entry to fit `max(40, cols) - 2` characters, truncating with `…` when narrow and expanding to full detail when wide.
2. **Debounced Redraw in `_ResizableProgress` (`nh_dl/ui.py`)**:
   - Monitors `_get_terminal_width()` on `make_tasks_table()`.
   - When `cols != _last_cols` stabilizes for >= 150 ms (and `console.is_terminal` is `True`), renders the banner, header, divider, and all formatted `LogEntry` lines into an off-screen `Console(file=StringIO(), ...)` buffer, clears the screen (`\x1b[2J\x1b[3J\x1b[H` or `console.clear()` fallback), and flushes in one write before `Progress` draws the 2 live bars.
3. **Batch Integration (`main.py`)**:
   - `download_codes_list()` records entries in `BatchLogBuffer` and attaches it to `create_download_progress()`.
4. **Tests (`tests/`)**:
   - Unit tests for `BatchLogBuffer` width-fitting (truncation/expansion) and debounce state transitions.

### Phase 4 Decision Log
1. **Main-Buffer Redraw vs. Alternate Screen**: Chose main-buffer clear-and-redraw so mouse-wheel scrollback and post-exit history work like standard CLI tools (similar to Claude Code / Antigravity CLI).
2. **Full History Redraw vs. Rolling Viewport**: Chose full structured `LogEntry` redraw so older completed lines also re-fit on resize.
3. **Debounced Single-Write Buffer**: Chose 150 ms debounce + single `StringIO` write to guarantee zero impact on `asyncio` download throughput.
