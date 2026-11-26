import io
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from questionary import Style as QStyle
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Column, Table
from rich.text import Text

console = Console()

QUESTIONARY_STYLE = QStyle(
    [
        ("qmark", "fg:#ff5fd7 bold"),
        ("question", "bold"),
        ("answer", "fg:#5fffff bold"),
        ("pointer", "fg:#ff5fd7 bold"),
        ("highlighted", "fg:#5fffff bold"),
        ("selected", "fg:#5fff87"),
        ("instruction", "fg:#808080"),
    ]
)


def print_banner(subtitle: str | None = None) -> None:
    title = Text("nhentai-cli", style="bold bright_magenta")
    if subtitle:
        title.append(f"  •  {subtitle}", style="dim")
    console.print(Panel.fit(title, border_style="cyan", padding=(0, 2)))


def print_info(text: str) -> None:
    console.print(f"[cyan]ℹ[/cyan] {text}")


def print_success(text: str) -> None:
    console.print(f"[green]✔[/green] {text}")


def print_warning(text: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {text}")


def print_error(text: str) -> None:
    console.print(f"[bold red]✖[/bold red] {text}")


def print_rule(title: str = "") -> None:
    console.rule(title, style="dim")


def _get_terminal_width() -> int:
    for stream in (sys.__stdout__, sys.stdout, sys.__stderr__):
        if stream is not None:
            try:
                return os.get_terminal_size(stream.fileno()).columns
            except OSError:
                pass
    return shutil.get_terminal_size((80, 20)).columns


@dataclass(frozen=True)
class LogEntry:
    kind: str  # "success" | "skip" | "error"
    index: int
    total: int
    code: int
    detail: str


@dataclass
class BatchLogBuffer:
    total: int
    output_dir: Path
    entries: list[LogEntry] = field(default_factory=list)

    def add(self, kind: str, index: int, total: int, code: int, detail: str) -> LogEntry:
        entry = LogEntry(kind=kind, index=index, total=total, code=code, detail=detail)
        self.entries.append(entry)
        return entry

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        clean = " ".join(text.split())
        if len(clean) <= max_len:
            return clean
        return clean[: max(1, max_len - 1)].rstrip() + "…"

    def format_entry(self, entry: LogEntry, cols: int | None = None) -> str:
        width = _get_terminal_width() if cols is None else cols
        max_width = max(40, width) - 2

        if entry.kind == "skip":
            plain_prefix = f"↷ [{entry.index}/{entry.total}] {entry.code} "
            avail = max(8, max_width - len(plain_prefix))
            detail = escape(self._truncate(entry.detail, avail))
            return f"[dim]↷ [{entry.index}/{entry.total}][/dim] [cyan]{entry.code}[/cyan] [dim]{detail}[/dim]"

        if entry.kind == "error":
            plain_prefix = f"✖ [{entry.index}/{entry.total}] [{entry.code}] "
            avail = max(8, max_width - len(plain_prefix))
            detail = escape(self._truncate(entry.detail, avail))
            return f"[bold red]✖[/bold red] [dim][{entry.index}/{entry.total}][/dim] [red][{entry.code}][/red] {detail}"

        plain_prefix = f"✔ [{entry.index}/{entry.total}] {entry.code} "
        avail = max(8, max_width - len(plain_prefix))
        detail = escape(self._truncate(entry.detail, avail))
        return f"[green]✔[/green] [dim][{entry.index}/{entry.total}][/dim] [cyan]{entry.code}[/cyan] {detail}"

    def render_to_ansi(self, cols: int) -> str:
        buf = io.StringIO()
        offscreen = Console(
            file=buf,
            width=max(40, cols),
            force_terminal=True,
            color_system=console.color_system,
            legacy_windows=False,
        )
        offscreen.print(Panel.fit(Text("nhentai-cli", style="bold bright_magenta"), border_style="cyan", padding=(0, 2)))
        offscreen.print(f"[cyan]ℹ[/cyan] Queued [bold]{self.total}[/bold] codes for download.")
        offscreen.print(f"[cyan]ℹ[/cyan] Output folder: [dim]{escape(str(self.output_dir.resolve()))}[/dim]")
        offscreen.rule("", style="dim")
        for entry in self.entries:
            offscreen.print(self.format_entry(entry, cols))
        return buf.getvalue()


class _ResizableProgress(Progress):
    """Progress bar that scales to terminal width and redraws batch logs on resize."""

    def __init__(
        self,
        *columns,
        log_buffer: BatchLogBuffer | None = None,
        debounce_seconds: float = 0.15,
        **kwargs,
    ):
        self._log_buffer = log_buffer
        self._debounce_seconds = debounce_seconds
        self._last_cols = _get_terminal_width()
        self._pending_cols: int | None = None
        self._last_resize_at = 0.0
        self._redrawing = False
        super().__init__(*columns, **kwargs)

    def _should_redraw_on_resize(self, cols: int, now: float | None = None) -> bool:
        if self._log_buffer is None or self._redrawing:
            return False
        current_time = time.monotonic() if now is None else now
        if cols == self._last_cols:
            self._pending_cols = None
            return False
        if self._pending_cols != cols:
            self._pending_cols = cols
            self._last_resize_at = current_time
            return False
        if current_time - self._last_resize_at < self._debounce_seconds:
            return False
        self._last_cols = cols
        self._pending_cols = None
        return True

    def _perform_redraw(self, cols: int) -> None:
        if not self.console.is_terminal or self._log_buffer is None:
            return
        self._redrawing = True
        try:
            rendered = self._log_buffer.render_to_ansi(cols)
            if self.console.legacy_windows:
                self.console.clear()
                self.console.file.write(rendered)
            else:
                self.console.file.write("\x1b[2J\x1b[3J\x1b[H" + rendered)
            self.console.file.flush()
            if hasattr(self, "live") and hasattr(self.live, "_live_render"):
                self.live._live_render._shape = None
        finally:
            self._redrawing = False

    def make_tasks_table(self, tasks):
        cols = _get_terminal_width()
        if self._should_redraw_on_resize(cols):
            self._perform_redraw(cols)
        desc_width = max(10, min(40, cols // 3, cols - 46))
        bar_width = max(6, cols - (40 + desc_width))
        for col in self.columns:
            if isinstance(col, BarColumn):
                col.bar_width = bar_width
        table = super().make_tasks_table(tasks)
        if len(table.columns) > 1:
            table.columns[1].max_width = desc_width
        return table


def create_download_progress(log_buffer: BatchLogBuffer | None = None) -> Progress:
    return _ResizableProgress(
        SpinnerColumn(style="cyan"),
        TextColumn(
            "[progress.description]{task.description}",
            table_column=Column(no_wrap=True, overflow="ellipsis", max_width=26),
        ),
        BarColumn(
            bar_width=28,
            complete_style="cyan",
            finished_style="green",
        ),
        MofNCompleteColumn(table_column=Column(no_wrap=True)),
        TaskProgressColumn(table_column=Column(no_wrap=True)),
        TextColumn("[dim]{task.fields[speed]}[/dim]", table_column=Column(no_wrap=True)),
        TimeRemainingColumn(compact=True, table_column=Column(no_wrap=True)),
        log_buffer=log_buffer,
        console=console,
        expand=False,
        refresh_per_second=10,
    )


def print_batch_summary(
    total: int,
    succeeded: int,
    skipped: int,
    failed: list[int],
    output_dir: Path,
    failed_file: Path | None = None,
) -> None:
    downloaded = succeeded - skipped

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold")

    table.add_row("Total queued", str(total))
    table.add_row("Downloaded", f"[green]{downloaded}[/green]")
    table.add_row("Skipped (local)", f"[cyan]{skipped}[/cyan]")
    if failed:
        table.add_row("Failed", f"[bold red]{len(failed)}[/bold red]")
    else:
        table.add_row("Failed", "[green]0[/green]")
    table.add_row("Output folder", str(output_dir.resolve()))
    if failed_file is not None:
        table.add_row("Failed list", f"[red]{failed_file}[/red]")

    border = "red" if failed else "green"
    title = "[bold red]Batch Finished with Errors[/bold red]" if failed else "[bold green]Batch Complete[/bold green]"
    console.print()
    console.print(Panel.fit(table, title=title, border_style=border, padding=(0, 2)))
