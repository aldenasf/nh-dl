# nhentai-cli Design Specification & Decision Log

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
3. **Architecture**: Modular async architecture (`nhentai_cli/` package + `main.py`).
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
1. **CLI (`nhentai_cli/cli.py`)**:
   - `-f, --format {image,pdf,both}` (default `image`).
   - `--last` flag to replay the last saved settings (overridable by explicit flags).
   - `parse_codes(raw_input)`: reads file if path exists, otherwise parses inline string; strips `#` comments, splits by `,` and `\n`, extracts numeric IDs/URLs, deduplicates in order.
2. **State (`nhentai_cli/state.py`)**:
   - Persists `input`, `output`, `folder_name`, `format`, and `concurrency` to `.nhentai_cli.json`.
   - Pre-fills interactive prompts with saved values.
3. **PDF & Storage (`nhentai_cli/pdf.py`, `storage.py`, `downloader.py`)**:
   - Saves `<folder_name>.pdf` inside `downloads/<folder_name>/`.
   - Keeps `cover.*` and `info.json` in all modes (`image`, `pdf`, `both`).
   - Deletes page images (`001.*`..`N.*`) after PDF creation only in `pdf` mode.

### Phase 2 Decision Log
1. **Scope**: Implement TODO items 1-3 now; defer offline web viewer to a future phase.
2. **PDF Location**: Store PDF inside the gallery folder alongside `cover.*` and `info.json`.
3. **PDF Library**: Use `Pillow` alone instead of `img2pdf` + `Pillow`, since nhentai serves `.webp` and `Pillow` handles all formats with one dependency.
4. **State Persistence**: Save recent non-sensitive settings to `.nhentai_cli.json` for interactive defaults and `--last` CLI replay.
5. **Input Parsing**: Support mixed newlines, commas, `#` comments, URLs, and inline comma-separated strings.
