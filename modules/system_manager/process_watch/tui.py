"""Textual interactive process explorer for proc-stats and sm proc watch."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)
from textual.widgets.option_list import Option

from .exporter import format_cell_value
from .filters import (
    COLUMN_DEFS,
    COLUMN_PRESETS,
    GROUP_MODES,
    SORT_FIELDS,
    ProcessFilter,
    filter_processes,
    group_processes,
    sort_processes,
)
from .models import (
    MonitoringSnapshot,
    ProcessIdentity,
    ProcessSample,
    format_bytes_iec,
    format_duration,
    format_percent,
    format_rate_iec,
    format_sanitized_summary,
    make_sparkline,
)
from .sampler import ProcessSampler, get_ancestry_chain

THEMES = ("dark", "light", "high-contrast")

APP_CSS = """
Screen {
    background: #0f1419;
    color: #e6edf3;
}
Screen.theme-light {
    background: #f6f8fa;
    color: #1f2328;
}
Screen.theme-high-contrast {
    background: #000000;
    color: #ffffff;
}
#host-header {
    height: auto;
    padding: 0 1;
    background: #161b22;
    border-bottom: solid #30363d;
    color: #c9d1d9;
}
Screen.theme-light #host-header {
    background: #eaeef2;
    border-bottom: solid #d0d7de;
    color: #1f2328;
}
#filter-bar {
    height: auto;
    padding: 0 1;
    display: none;
    background: #161b22;
}
#filter-bar.visible {
    display: block;
}
#filter-input {
    width: 100%;
}
#main-tabs {
    height: 1fr;
}
DataTable {
    height: 1fr;
}
DataTable > .datatable--cursor {
    background: #1f6feb;
    color: #ffffff;
}
#proc-tree {
    height: 1fr;
}
#quick-details {
    height: 3;
    padding: 0 1;
    background: #161b22;
    border-top: solid #30363d;
    color: #8b949e;
}
Screen.theme-light #quick-details {
    background: #eaeef2;
    border-top: solid #d0d7de;
    color: #57606a;
}
Screen.theme-light #pinned-summary,
Screen.theme-light #history-summary,
Screen.theme-light #filter-bar {
    background: #eaeef2;
    border-bottom: solid #d0d7de;
    color: #1f2328;
}
Screen.theme-light DataTable,
Screen.theme-light Tree {
    background: #ffffff;
    color: #1f2328;
}
#pinned-summary, #history-summary {
    height: auto;
    padding: 0 1;
    background: #161b22;
    border-bottom: solid #30363d;
}
.modal-dialog {
    align: center middle;
    background: rgba(0, 0, 0, 0.72);
}
.modal-box {
    width: 72%;
    max-width: 96;
    height: auto;
    max-height: 85%;
    padding: 1 2;
    background: #161b22;
    border: heavy #388bfd;
}
.modal-title {
    text-style: bold;
    color: #58a6ff;
    padding-bottom: 1;
}
.modal-actions {
    height: auto;
    padding-top: 1;
    align: right middle;
}
.modal-actions Button {
    margin-left: 1;
}
#inspector-body {
    height: auto;
    max-height: 24;
    overflow-y: auto;
}
"""


class HelpModal(ModalScreen[None]):
    """Contextual keyboard and mouse help dialog."""

    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Container(classes="modal-dialog"):
            with Vertical(classes="modal-box"):
                yield Static("proc-stats — Keyboard & Mouse Controls", classes="modal-title")
                yield Static(
                    "Navigation:  Up/Down or j/k = move | PgUp/PgDn/Home/End = jump | Click header = sort\n"
                    "Inspect:     Enter = full process inspector | d = descendants | p = parent\n"
                    "Selection:   Space = pin/unpin | f = freeze/unfreeze snapshot\n"
                    "Filtering:   / = live filter | x / Esc = clear all filters (-g/-e/-p//)\n"
                    "Views:       s = sort menu | S = reverse sort | a = subtree aggregation\n"
                    "             c = columns/presets | g = group mode | h = history tab\n"
                    "Rows/Theme:  +/= and - = adjust visible rows | r = exact row count | t = theme\n"
                    "General:     ? = this help | q = quit (read-only monitor, never kills processes)"
                )
                with Horizontal(classes="modal-actions"):
                    yield Button("Close (Esc)", id="close-help", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class ChoiceModal(ModalScreen[Optional[str]]):
    """Generic option-picker modal for sort field, column preset, or group mode."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, options: Sequence[Tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._options = list(options)

    def compose(self) -> ComposeResult:
        with Container(classes="modal-dialog"):
            with Vertical(classes="modal-box"):
                yield Static(self._title, classes="modal-title")
                yield OptionList(*[Option(label, id=key) for key, label in self._options], id="choice-list")
                with Horizontal(classes="modal-actions"):
                    yield Button("Cancel", id="cancel-choice")

    def on_mount(self) -> None:
        self.query_one("#choice-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RowCountModal(ModalScreen[Optional[int]]):
    """Modal to set exact visible row count (0 = auto-fit terminal height)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_rows: Optional[int]) -> None:
        super().__init__()
        self._current = "" if current_rows is None else str(current_rows)

    def compose(self) -> ComposeResult:
        with Container(classes="modal-dialog"):
            with Vertical(classes="modal-box"):
                yield Static("Visible Row Count (0 = auto-fit terminal height)", classes="modal-title")
                yield Input(value=self._current, placeholder="Enter integer >= 0 (0 for auto)", id="row-count-input")
                with Horizontal(classes="modal-actions"):
                    yield Button("Auto", id="row-auto")
                    yield Button("Apply", id="row-apply", variant="primary")
                    yield Button("Cancel", id="row-cancel")

    def on_mount(self) -> None:
        self.query_one("#row-count-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_value(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "row-auto":
            self.dismiss(0)
        elif event.button.id == "row-apply":
            val = self.query_one("#row-count-input", Input).value
            self._submit_value(val)
        else:
            self.dismiss(None)

    def _submit_value(self, raw: str) -> None:
        try:
            num = int(raw.strip())
            if num >= 0:
                self.dismiss(num)
                return
        except ValueError:
            pass
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProcessInspectorModal(ModalScreen[Optional[str]]):
    """Detailed read-only inspector for a single process."""

    BINDINGS = [Binding("escape", "close", "Back")]

    def __init__(
        self,
        sample: ProcessSample,
        ancestry: Sequence[ProcessSample],
        parent: Optional[ProcessSample],
        history_series_cpu: Sequence[Optional[float]],
        history_series_rss: Sequence[Optional[float]],
        is_pinned: bool,
        extra_details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self.sample = sample
        self.ancestry = list(ancestry)
        self._parent_sample = parent
        self.history_cpu = list(history_series_cpu)
        self.history_rss = list(history_series_rss)
        self.is_pinned = is_pinned
        self.extra = extra_details or {}

    def compose(self) -> ComposeResult:
        s = self.sample
        cwd = self.extra.get("cwd") or s.cwd or "-"
        handles = self.extra.get("num_handles")
        if handles is None:
            handles = s.num_handles
        created_str = (
            datetime.fromtimestamp(s.create_time, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            if s.create_time > 0
            else "-"
        )
        parent_str = (
            f"{self._parent_sample.name} ({self._parent_sample.pid})"
            if self._parent_sample
            else f"PID {s.ppid}"
        )
        chain_str = " -> ".join(f"{p.name}({p.pid})" for p in self.ancestry) or "-"
        cpu_spark = make_sparkline(self.history_cpu, width=20) or "-"
        rss_spark = make_sparkline(self.history_rss, width=20) or "-"

        body = (
            f"Identity:    {s.identity.key}  |  PID: {s.pid}  |  Status: {'EXITED' if s.is_exited else (s.status or '-')}\n"
            f"Parent:      {parent_str}  |  User: {s.username or '-'}\n"
            f"Created:     {created_str}  |  Uptime: {format_duration(s.uptime_seconds)}\n"
            f"Executable:  {s.exe or '-'}\n"
            f"Working Dir: {cwd}\n"
            f"Cmdline:     {s.cmdline_redacted or '-'}  (redacted)\n\n"
            f"CPU:         {format_percent(s.cpu_percent)} raw  |  {format_percent(s.cpu_percent_normalized)} host-norm  |  "
            f"CumTime: {format_duration(s.cpu_time_seconds)}  |  Peak: {format_percent(s.peak_cpu_percent)}\n"
            f"Memory:      RSS {format_bytes_iec(s.rss_bytes)}  |  Private {format_bytes_iec(s.private_bytes)}  |  "
            f"Virtual {format_bytes_iec(s.vms_bytes)}  |  Peak RSS: {format_bytes_iec(s.peak_rss_bytes)}\n"
            f"Process I/O: Read {format_rate_iec(s.io_read_rate)} (total {format_bytes_iec(s.io_read_bytes)})  |  "
            f"Write {format_rate_iec(s.io_write_rate)} (total {format_bytes_iec(s.io_write_bytes)})\n"
            f"GPU:         Mem {format_bytes_iec(s.gpu_memory_bytes)}  |  GPU #{s.gpu_id if s.gpu_id is not None else '-'}  |  "
            f"Backend: {s.gpu_provenance or 'unavailable'}\n"
            f"Threads:     {s.num_threads if s.num_threads is not None else '-'}  |  "
            f"Handles: {handles if handles is not None else '-'}  |  "
            f"Children: {s.child_count}  |  Descendants: {s.descendant_count}\n"
            f"Subtree:     CPU {format_percent(s.subtree_cpu_percent)}  |  RSS {format_bytes_iec(s.subtree_rss_bytes)} (shared pages may overlap)\n"
            f"Ancestry:    {chain_str}\n"
            f"History:     CPU [{cpu_spark}]   RSS [{rss_spark}]"
        )

        with Container(classes="modal-dialog"):
            with Vertical(classes="modal-box"):
                yield Static(f"Process Inspector — {s.name} ({s.pid})", classes="modal-title", markup=False)
                yield Static(body, id="inspector-body", markup=False)
                with Horizontal(classes="modal-actions"):
                    yield Button("Return (Esc)", id="act-close", variant="primary")
                    yield Button("Show Parent", id="act-parent")
                    yield Button("Descendants", id="act-descendants")
                    yield Button("Unpin" if self.is_pinned else "Pin", id="act-pin")
                    yield Button("History", id="act-history")
                    yield Button("Copy Summary", id="act-copy")
                    yield Button("Compare Pinned", id="act-compare")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_close(self) -> None:
        self.dismiss(None)


class ProcessWatchApp(App[None]):
    """Interactive Textual process explorer."""

    CSS = APP_CSS
    TITLE = "proc-stats"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("enter", "inspect_selected", "Inspect"),
        Binding("space", "toggle_pin", "Pin"),
        Binding("/", "open_filter", "Filter"),
        Binding("s", "choose_sort", "Sort"),
        Binding("S", "reverse_sort", "RevSort", key_display="S"),
        Binding("a", "toggle_aggregate", "Subtree"),
        Binding("c", "choose_columns", "Cols"),
        Binding("g", "choose_group", "Group"),
        Binding("h", "show_history", "History"),
        Binding("d", "show_descendants", "Descendants"),
        Binding("p", "show_parent", "Parent"),
        Binding("f", "toggle_freeze", "Freeze"),
        Binding("+", "more_rows", "+Rows", show=False),
        Binding("=", "more_rows", "+Rows", show=False),
        Binding("-", "fewer_rows", "-Rows", show=False),
        Binding("r", "set_row_count", "Rows"),
        Binding("t", "cycle_theme", "Theme", show=False),
        Binding("?", "show_help", "Help"),
        Binding("x", "clear_filters", "ClearFilter"),
        Binding("escape", "handle_escape", "Back", show=False),
    ]

    def __init__(
        self,
        sampler: ProcessSampler,
        *,
        initial_filter: Optional[ProcessFilter] = None,
        interval_seconds: float = 1.0,
        sort_key: str = "cpu",
        sort_descending: bool = True,
        visible_rows: Optional[int] = None,
        column_preset: str = "default",
        aggregated: bool = False,
        max_pinned: int = 12,
        enable_background_worker: bool = True,
    ) -> None:
        super().__init__()
        self.sampler = sampler
        self.proc_filter = initial_filter or ProcessFilter()
        self.interval_seconds = max(0.2, float(interval_seconds))
        self.sort_key = sort_key if sort_key in SORT_FIELDS else "cpu"
        self.sort_descending = sort_descending
        self.visible_rows = visible_rows  # None means auto-fit terminal height
        self.column_preset = column_preset if column_preset in COLUMN_PRESETS else "default"
        self.aggregated = aggregated
        self.group_mode = "none"
        self.max_pinned = max(1, int(max_pinned))
        self.enable_background_worker = enable_background_worker

        self.frozen = False
        self.theme_index = 0
        self.selected_identity: Optional[ProcessIdentity] = None
        self._tree_selected_identity: Optional[ProcessIdentity] = None
        self._tree_expanded: Dict[ProcessIdentity, bool] = {}
        self.pinned_identities: List[ProcessIdentity] = []
        self._pinned_last_known: Dict[ProcessIdentity, ProcessSample] = {}
        self.latest_snapshot: Optional[MonitoringSnapshot] = None
        self._displayed_rows: List[ProcessSample] = []
        self._row_identities: List[ProcessIdentity] = []
        self._stop_event = threading.Event()
        self._current_columns: List[str] = list(COLUMN_PRESETS[self.column_preset])

    def compose(self) -> ComposeResult:
        yield Static("Starting proc-stats...", id="host-header", markup=False)
        with Container(id="filter-bar"):
            yield Input(placeholder="Filter by PID, name, exe, user... (Enter to apply, Esc to cancel)", id="filter-input")
        with TabbedContent(id="main-tabs"):
            with TabPane("Processes", id="tab-processes"):
                yield DataTable(id="proc-table", cursor_type="row")
            with TabPane("Tree", id="tab-tree"):
                yield Tree("Processes", id="proc-tree")
            with TabPane("Pinned", id="tab-pinned"):
                yield Static("No pinned processes. Press Space on any process to pin.", id="pinned-summary", markup=False)
                yield DataTable(id="pinned-table", cursor_type="row")
            with TabPane("History", id="tab-history"):
                yield Static("Select a process to view rolling history and lifecycle events.", id="history-summary", markup=False)
                yield DataTable(id="history-table", cursor_type="row")
                yield DataTable(id="events-table", cursor_type="row")
        yield Static("", id="quick-details", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._configure_tables()
        self.query_one("#proc-table", DataTable).focus()
        if self.enable_background_worker:
            self.query_one("#host-header", Static).update(
                "Host CPU: sampling... | RAM: ... | GPU: ...\nSampling processes in background..."
            )
            self._start_sampling_worker()
            return
        # Synchronous initial sample for deterministic headless tests
        snap = self.sampler.sample(
            focus_identities={self.selected_identity} if self.selected_identity else set(),
            pinned_identities=set(self.pinned_identities),
        )
        self.apply_snapshot(snap)

    def on_unmount(self) -> None:
        self._stop_event.set()

    def on_resize(self) -> None:
        if self.latest_snapshot is not None:
            self._refresh_views()

    def _configure_tables(self) -> None:
        pinned_tbl = self.query_one("#pinned-table", DataTable)
        pinned_tbl.add_columns("PID", "Process", "Status", "CPU %", "Peak CPU%", "RSS", "Peak RSS", "I/O/s", "Trend", "Uptime")

        hist_tbl = self.query_one("#history-table", DataTable)
        hist_tbl.add_columns("Time", "CPU %", "RSS", "Proc Read/s", "Proc Write/s", "GPU Mem")

        evt_tbl = self.query_one("#events-table", DataTable)
        evt_tbl.add_columns("Time", "Event", "PID", "Process")

    @work(thread=True, exclusive=True)
    def _start_sampling_worker(self) -> None:
        first = True
        while first or not self._stop_event.wait(self.interval_seconds):
            first = False
            if self.frozen:
                continue
            focus = {self.selected_identity} if self.selected_identity else set()
            pinned = set(self.pinned_identities)
            snap = self.sampler.sample(focus_identities=focus, pinned_identities=pinned)
            if not self._stop_event.is_set():
                try:
                    self.call_from_thread(self.apply_snapshot, snap)
                except Exception:
                    break

    def apply_snapshot(self, snapshot: MonitoringSnapshot) -> None:
        """Apply a new MonitoringSnapshot on the UI thread."""
        self.latest_snapshot = snapshot
        for ident in self.pinned_identities:
            if ident in snapshot.by_identity:
                self._pinned_last_known[ident] = snapshot.by_identity[ident]
            elif ident in self._pinned_last_known:
                prev = self._pinned_last_known[ident]
                prev.is_exited = True
                prev.status = "exited"
                prev.cpu_percent = None
                prev.io_read_rate = None
                prev.io_write_rate = None
        self._refresh_views()

    def _effective_row_limit(self) -> int:
        if self.visible_rows is not None and self.visible_rows > 0:
            return self.visible_rows
        height = max(16, self.size.height or 24)
        return max(5, height - 10)

    def _responsive_columns(self) -> List[str]:
        cols = list(COLUMN_PRESETS.get(self.column_preset, COLUMN_PRESETS["default"]))
        width = self.size.width or 120
        if width < 90:
            priority = [c for c in ("pid", "name", "cpu", "rss", "io_total") if c in COLUMN_DEFS]
            return priority
        if width < 115:
            return [c for c in cols if c not in ("gpu_mem", "uptime", "ppid", "user", "vms")]
        return cols

    def _refresh_views(self) -> None:
        if self.latest_snapshot is None:
            return
        snap = self.latest_snapshot
        filtered = filter_processes(snap.processes, self.proc_filter, snap.children_map)
        sorted_rows = sort_processes(
            filtered,
            sort_key=self.sort_key,
            descending=self.sort_descending,
            aggregated=self.aggregated,
        )
        self._displayed_rows = sorted_rows

        self._update_header(snap, matched_count=len(filtered), visible_count=len(sorted_rows))
        self._update_process_table(sorted_rows, snap)
        self._update_tree_view(filtered, snap)
        self._update_pinned_view(snap)
        self._update_history_view(snap)
        self._update_quick_details(snap)

    def _update_header(self, snap: MonitoringSnapshot, *, matched_count: int, visible_count: int) -> None:
        h = snap.host
        gpu_part = "GPU: n/a"
        if h.gpu_devices:
            dev = h.gpu_devices[0]
            load_s = format_percent(dev.get("load"))
            mem_s = f"{format_bytes_iec(dev.get('mem_used'))}/{format_bytes_iec(dev.get('mem_total'))}"
            age_s = f"{h.gpu_age_seconds:.0f}s" if h.gpu_age_seconds is not None else "-"
            gpu_part = f"GPU({h.gpu_backend}, {age_s}): {load_s} {mem_s}"
        elif h.gpu_backend != "unavailable":
            gpu_part = f"GPU({h.gpu_backend}): none"

        flags: List[str] = []
        if self.frozen:
            flags.append("[FROZEN]")
        if self.aggregated:
            flags.append("[SUBTREE]")
        if self.group_mode != "none":
            flags.append(f"[GRP:{self.group_mode}]")
        if self.proc_filter.search_text:
            flags.append(f"[/{self.proc_filter.search_text}]")
        if self.proc_filter.include_globs:
            flags.append(f"[g:{','.join(self.proc_filter.include_globs)}]")
        if self.proc_filter.exclude_globs:
            flags.append(f"[e:{','.join(self.proc_filter.exclude_globs)}]")
        if self.proc_filter.pids:
            flags.append(f"[PIDs:{','.join(str(p) for p in self.proc_filter.pids)}]")

        arrow = "▼" if self.sort_descending else "▲"
        row_label = "auto" if self.visible_rows is None else str(self.visible_rows)
        line1 = (
            f"Host CPU: {h.cpu_percent:.1f}% ({h.cpu_count}c) | "
            f"RAM: {format_bytes_iec(h.mem_used_bytes)}/{format_bytes_iec(h.mem_total_bytes)} ({h.mem_percent:.0f}%) | "
            f"Disk I/O: R {format_rate_iec(h.disk_read_rate)} W {format_rate_iec(h.disk_write_rate)} | {gpu_part}"
        )
        line2 = (
            f"Procs: {visible_count}/{matched_count} matched ({h.total_processes} total) | "
            f"Sort: {self.sort_key} {arrow} | Rows: {row_label} | Cols: {self.column_preset} | "
            f"Sample: {snap.host.sample_duration_ms:.0f}ms {' '.join(flags)}"
        )
        self.query_one("#host-header", Static).update(f"{line1}\n{line2}")

    def _update_process_table(self, all_rows: List[ProcessSample], snap: MonitoringSnapshot) -> None:
        table = self.query_one("#proc-table", DataTable)
        if self.visible_rows is not None and self.visible_rows > 0:
            table.styles.height = self.visible_rows + 1
            table.styles.max_height = self.visible_rows + 1
        else:
            table.styles.height = "1fr"
            table.styles.max_height = None

        cols = self._responsive_columns()
        columns_changed = cols != self._current_columns or len(table.columns) == 0

        if self.group_mode != "none":
            self._render_grouped_table(table, all_rows, snap)
            return

        if columns_changed:
            table.clear(columns=True)
            self._current_columns = cols
            arrow = "▼" if self.sort_descending else "▲"
            for key in cols:
                label, _ = COLUMN_DEFS.get(key, (key, False))
                if self.aggregated and key in ("cpu", "rss", "io_read", "io_write", "io_total"):
                    label = f"Tree {label}"
                if key == self.sort_key:
                    label = f"{label} {arrow}"
                table.add_column(label, key=key)
        else:
            # Update sort indicator on existing column headers if needed
            arrow = "▼" if self.sort_descending else "▲"
            for key in cols:
                if key in table.columns:
                    base, _ = COLUMN_DEFS.get(key, (key, False))
                    if self.aggregated and key in ("cpu", "rss", "io_read", "io_write", "io_total"):
                        base = f"Tree {base}"
                    table.columns[key].label = f"{base} {arrow}" if key == self.sort_key else base

        desired_keys = [s.identity.key for s in all_rows]
        existing_keys = list(table.rows.keys())
        self._row_identities = [s.identity for s in all_rows]

        if existing_keys != desired_keys:
            table.clear(columns=False)
            for sample in all_rows:
                row_vals = [format_cell_value(sample, key, aggregated=self.aggregated) for key in cols]
                table.add_row(*row_vals, key=sample.identity.key)
        else:
            for sample in all_rows:
                for key in cols:
                    table.update_cell(
                        sample.identity.key,
                        key,
                        format_cell_value(sample, key, aggregated=self.aggregated),
                    )

        # Restore selection by stable identity
        if self.selected_identity is not None and self.selected_identity.key in desired_keys:
            idx = desired_keys.index(self.selected_identity.key)
            if table.cursor_row != idx:
                table.move_cursor(row=idx)
        elif all_rows and (self.selected_identity is None or self.selected_identity.key not in desired_keys):
            # Keep previous selection if it's exited and still in snapshot, else select first visible
            if self.selected_identity is None or self.selected_identity not in snap.by_identity:
                self.selected_identity = all_rows[0].identity
                table.move_cursor(row=0)

    def _render_grouped_table(self, table: DataTable, visible: List[ProcessSample], snap: MonitoringSnapshot) -> None:
        table.clear(columns=True)
        self._current_columns = []
        table.add_columns("Group", "Count", "Sum CPU %", "Sum RSS", "Sum Read/s", "Sum Write/s", "Sum GPU Mem")
        by_pid = {s.pid: s for s in snap.processes if not s.is_exited}
        groups = group_processes(visible, self.group_mode, by_pid=by_pid)
        self._row_identities = []
        for grp in groups:
            table.add_row(
                grp.label,
                str(grp.member_count),
                format_percent(grp.cpu_percent),
                format_bytes_iec(grp.rss_bytes),
                format_rate_iec(grp.io_read_rate),
                format_rate_iec(grp.io_write_rate),
                format_bytes_iec(grp.gpu_memory_bytes),
                key=f"grp:{grp.group_key}",
            )

    def _snapshot_tree_expansion(self, node: Any) -> None:
        if isinstance(node.data, ProcessIdentity) and node.allow_expand:
            self._tree_expanded[node.data] = bool(node.is_expanded)
        for child in getattr(node, "children", ()):
            self._snapshot_tree_expansion(child)

    def _update_tree_view(self, filtered: List[ProcessSample], snap: MonitoringSnapshot) -> None:
        tree = self.query_one("#proc-tree", Tree)
        self._snapshot_tree_expansion(tree.root)
        if tree.cursor_node is not None and isinstance(tree.cursor_node.data, ProcessIdentity):
            self._tree_selected_identity = tree.cursor_node.data

        tree.clear()
        by_pid: Dict[int, ProcessSample] = {s.pid: s for s in filtered if not s.is_exited}
        children: Dict[int, List[ProcessSample]] = {}
        roots: List[ProcessSample] = []
        for s in filtered:
            if s.is_exited:
                continue
            if s.ppid and s.ppid in by_pid and s.ppid != s.pid:
                children.setdefault(s.ppid, []).append(s)
            else:
                roots.append(s)

        roots = sort_processes(roots, sort_key=self.sort_key, descending=self.sort_descending, aggregated=self.aggregated)
        node_by_identity: Dict[ProcessIdentity, Any] = {}
        default_expand = len(roots) <= 10

        def add_node(parent_node: Any, sample: ProcessSample, seen: Set[int]) -> None:
            if sample.pid in seen:
                return
            seen.add(sample.pid)
            cpu_v = sample.subtree_cpu_percent if self.aggregated else sample.cpu_percent
            rss_v = sample.subtree_rss_bytes if self.aggregated else sample.rss_bytes
            scope = "tree " if self.aggregated else ""
            label = f"{sample.name} ({sample.pid})  {scope}CPU {format_percent(cpu_v)} | RSS {format_bytes_iec(rss_v)}"
            kids = children.get(sample.pid, [])
            if kids:
                expand = self._tree_expanded.get(sample.identity, default_expand)
                node = parent_node.add(label, data=sample.identity, expand=expand)
                node_by_identity[sample.identity] = node
                for kid in sort_processes(kids, sort_key=self.sort_key, descending=self.sort_descending):
                    add_node(node, kid, seen)
            else:
                leaf = parent_node.add_leaf(label, data=sample.identity)
                node_by_identity[sample.identity] = leaf

        visited: Set[int] = set()
        for root in roots:
            add_node(tree.root, root, visited)
        tree.root.expand()

        target = self._tree_selected_identity or self.selected_identity
        if target is not None and target in node_by_identity:
            target_node = node_by_identity[target]
            if hasattr(tree, "_build"):
                tree._build()
            tree.select_node(target_node)

    def _update_pinned_view(self, snap: MonitoringSnapshot) -> None:
        summary = self.query_one("#pinned-summary", Static)
        tbl = self.query_one("#pinned-table", DataTable)
        tbl.clear(columns=False)
        if not self.pinned_identities:
            summary.update("No pinned processes. Press Space on any process to pin (max " + str(self.max_pinned) + ").")
            return
        summary.update(f"Pinned Processes: {len(self.pinned_identities)}/{self.max_pinned} (Space to unpin)")
        for ident in self.pinned_identities:
            sample = snap.by_identity.get(ident) or self._pinned_last_known.get(ident)
            if sample is None:
                continue
            hist = self.sampler.history_store.get(ident)
            cpu_stats = hist.summary("cpu") if hist else None
            spark = make_sparkline(hist.series("cpu"), width=8) if hist else ""
            trend_str = f"{cpu_stats.trend} {spark}" if cpu_stats else "-"
            tbl.add_row(
                str(sample.pid),
                sample.name,
                "EXITED" if sample.is_exited else (sample.status or "-"),
                format_percent(sample.cpu_percent),
                format_percent(sample.peak_cpu_percent),
                format_bytes_iec(sample.rss_bytes),
                format_bytes_iec(sample.peak_rss_bytes),
                format_rate_iec(sample.io_total_rate),
                trend_str,
                format_duration(sample.uptime_seconds),
                key=ident.key,
            )

    def _update_history_view(self, snap: MonitoringSnapshot) -> None:
        summary = self.query_one("#history-summary", Static)
        hist_tbl = self.query_one("#history-table", DataTable)
        evt_tbl = self.query_one("#events-table", DataTable)
        hist_tbl.clear(columns=False)
        evt_tbl.clear(columns=False)

        target_ident = self.selected_identity
        if target_ident is not None:
            sample = snap.by_identity.get(target_ident) or self._pinned_last_known.get(target_ident)
            hist = self.sampler.history_store.get(target_ident)
            if sample is not None and hist is not None:
                cpu_s = hist.summary("cpu")
                rss_s = hist.summary("rss")
                summary.update(
                    f"History: {sample.name} ({sample.pid}) | "
                    f"CPU cur {format_percent(cpu_s.current)} avg {format_percent(cpu_s.rolling_avg)} "
                    f"peak {format_percent(cpu_s.peak)} {cpu_s.trend} [{make_sparkline(hist.series('cpu'), 16)}] | "
                    f"RSS peak {format_bytes_iec(rss_s.peak)} [{make_sparkline(hist.series('rss'), 16)}]"
                )
                for pt in list(hist.points)[-15:][::-1]:
                    t_str = datetime.fromtimestamp(pt.timestamp_epoch, tz=timezone.utc).astimezone().strftime("%H:%M:%S")
                    hist_tbl.add_row(
                        t_str,
                        format_percent(pt.cpu_percent),
                        format_bytes_iec(pt.rss_bytes),
                        format_rate_iec(pt.io_read_rate),
                        format_rate_iec(pt.io_write_rate),
                        format_bytes_iec(pt.gpu_memory_bytes),
                    )
        for evt in list(snap.events)[-10:][::-1]:
            evt_tbl.add_row(evt.time_label, evt.event_type, str(evt.identity.pid), evt.name)

    def _update_quick_details(self, snap: MonitoringSnapshot) -> None:
        widget = self.query_one("#quick-details", Static)
        if self.selected_identity is None:
            widget.update("No process selected.")
            return
        sample = snap.by_identity.get(self.selected_identity) or self._pinned_last_known.get(self.selected_identity)
        if sample is None:
            widget.update("Selected process is no longer in snapshot.")
            return
        status_tag = " [EXITED]" if sample.is_exited else ""
        pin_tag = " [PINNED]" if sample.identity in self.pinned_identities else ""
        widget.update(
            f"Selected: {sample.name} ({sample.pid}){status_tag}{pin_tag} | "
            f"Peak CPU: {format_percent(sample.peak_cpu_percent)} | Peak RSS: {format_bytes_iec(sample.peak_rss_bytes)} | "
            f"Children: {sample.child_count} (Desc: {sample.descendant_count})\n"
            f"Cmd: {sample.cmdline_redacted or sample.exe or '-'}"
        )

    def _get_selected_sample(self) -> Optional[ProcessSample]:
        if self.latest_snapshot is None or self.selected_identity is None:
            return None
        return self.latest_snapshot.by_identity.get(self.selected_identity) or self._pinned_last_known.get(
            self.selected_identity
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "proc-table" and event.row_key and event.row_key.value:
            key_str = str(event.row_key.value)
            if key_str.startswith("grp:"):
                return
            for ident in self._row_identities:
                if ident.key == key_str:
                    self.selected_identity = ident
                    if self.latest_snapshot is not None:
                        self._update_quick_details(self.latest_snapshot)
                    break

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "proc-table" and event.row_key and event.row_key.value:
            key_str = str(event.row_key.value)
            if key_str.startswith("grp:"):
                return
            for ident in self._row_identities:
                if ident.key == key_str:
                    self.selected_identity = ident
                    break
            self.action_inspect_selected()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, ProcessIdentity):
            self.selected_identity = event.node.data
            self.action_inspect_selected()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.data_table.id != "proc-table" or not event.column_key or not event.column_key.value:
            return
        col_key = str(event.column_key.value)
        sort_map = {
            "pid": "pid",
            "name": "name",
            "cpu": "cpu",
            "cpu_norm": "cpu_norm",
            "rss": "rss",
            "io_read": "io_read",
            "io_write": "io_write",
            "io_total": "io_total",
            "gpu_mem": "gpu_mem",
            "uptime": "uptime",
            "threads": "threads",
            "peak_cpu": "peak_cpu",
            "peak_rss": "peak_rss",
            "subtree_cpu": "subtree_cpu",
            "subtree_rss": "subtree_rss",
        }
        mapped = sort_map.get(col_key)
        if mapped:
            if self.sort_key == mapped:
                self.sort_descending = not self.sort_descending
            else:
                self.sort_key = mapped
                self.sort_descending = mapped not in ("name", "pid")
            self._refresh_views()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if isinstance(event.node.data, ProcessIdentity):
            self.selected_identity = event.node.data
            self._tree_selected_identity = event.node.data
            if self.latest_snapshot is not None:
                self._update_quick_details(self.latest_snapshot)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if isinstance(event.node.data, ProcessIdentity):
            self._tree_expanded[event.node.data] = True

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        if isinstance(event.node.data, ProcessIdentity):
            self._tree_expanded[event.node.data] = False

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self.proc_filter.search_text = event.value
            self._refresh_views()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-input":
            self.proc_filter.search_text = event.value
            self.query_one("#proc-table", DataTable).focus()
            self._refresh_views()

    def _input_has_focus(self) -> bool:
        return isinstance(self.focused, Input)

    def action_move_down(self) -> None:
        if self._input_has_focus():
            return
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == "tab-processes":
            self.query_one("#proc-table", DataTable).action_cursor_down()
        elif tabs.active == "tab-tree":
            self.query_one("#proc-tree", Tree).action_cursor_down()

    def action_move_up(self) -> None:
        if self._input_has_focus():
            return
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active == "tab-processes":
            self.query_one("#proc-table", DataTable).action_cursor_up()
        elif tabs.active == "tab-tree":
            self.query_one("#proc-tree", Tree).action_cursor_up()

    def action_open_filter(self) -> None:
        if self._input_has_focus():
            return
        bar = self.query_one("#filter-bar")
        bar.add_class("visible")
        inp = self.query_one("#filter-input", Input)
        inp.focus()

    def action_clear_filters(self) -> None:
        if self._input_has_focus():
            return
        if not self.proc_filter.has_selectors():
            return
        self.proc_filter.search_text = ""
        self.proc_filter.include_globs = []
        self.proc_filter.exclude_globs = []
        self.proc_filter.pids = []
        self.proc_filter.recursive = False
        self.query_one("#filter-input", Input).value = ""
        self.query_one("#filter-bar").remove_class("visible")
        self._refresh_views()
        self.notify("Cleared all active filters.", severity="information")

    def action_handle_escape(self) -> None:
        bar = self.query_one("#filter-bar")
        if self._input_has_focus() or bar.has_class("visible"):
            self.proc_filter.search_text = ""
            self.query_one("#filter-input", Input).value = ""
            bar.remove_class("visible")
            self.query_one("#proc-table", DataTable).focus()
            self._refresh_views()
            return
        if self.proc_filter.search_text:
            self.proc_filter.search_text = ""
            self._refresh_views()
            return
        if self.proc_filter.has_selectors():
            self.action_clear_filters()

    def action_toggle_pin(self) -> None:
        if self._input_has_focus() or self.selected_identity is None:
            return
        ident = self.selected_identity
        if ident in self.pinned_identities:
            self.pinned_identities.remove(ident)
            self._pinned_last_known.pop(ident, None)
        else:
            if len(self.pinned_identities) >= self.max_pinned:
                self.notify(f"Pin limit ({self.max_pinned}) reached.", severity="warning")
                return
            self.pinned_identities.append(ident)
            sample = self._get_selected_sample()
            if sample is not None:
                self._pinned_last_known[ident] = sample
        self._refresh_views()

    def action_toggle_freeze(self) -> None:
        if self._input_has_focus():
            return
        self.frozen = not self.frozen
        self._refresh_views()

    def action_toggle_aggregate(self) -> None:
        if self._input_has_focus():
            return
        self.aggregated = not self.aggregated
        self._refresh_views()

    def action_reverse_sort(self) -> None:
        if self._input_has_focus():
            return
        self.sort_descending = not self.sort_descending
        self._refresh_views()

    def action_more_rows(self) -> None:
        if self._input_has_focus():
            return
        cur = self._effective_row_limit()
        self.visible_rows = cur + 5
        self._refresh_views()

    def action_fewer_rows(self) -> None:
        if self._input_has_focus():
            return
        cur = self._effective_row_limit()
        self.visible_rows = max(5, cur - 5)
        self._refresh_views()

    def action_set_row_count(self) -> None:
        if self._input_has_focus():
            return

        def on_done(val: Optional[int]) -> None:
            if val is not None:
                self.visible_rows = None if val == 0 else val
                self._refresh_views()

        self.push_screen(RowCountModal(self.visible_rows), callback=on_done)

    def action_choose_sort(self) -> None:
        if self._input_has_focus():
            return
        opts = [(f, f) for f in SORT_FIELDS if f != "random"]

        def on_done(choice: Optional[str]) -> None:
            if choice:
                self.sort_key = choice
                self.sort_descending = choice not in ("name", "pid")
                self._refresh_views()

        self.push_screen(ChoiceModal("Sort Processes By", opts), callback=on_done)

    def action_choose_columns(self) -> None:
        if self._input_has_focus():
            return
        opts = [(k, f"{k} ({', '.join(v[:5])}...)") for k, v in COLUMN_PRESETS.items()]

        def on_done(choice: Optional[str]) -> None:
            if choice and choice in COLUMN_PRESETS:
                self.column_preset = choice
                self._refresh_views()

        self.push_screen(ChoiceModal("Column Presets", opts), callback=on_done)

    def action_choose_group(self) -> None:
        if self._input_has_focus():
            return
        opts = [(m, f"Group by: {m}") for m in GROUP_MODES]

        def on_done(choice: Optional[str]) -> None:
            if choice and choice in GROUP_MODES:
                self.group_mode = choice
                self._refresh_views()

        self.push_screen(ChoiceModal("Grouping Mode", opts), callback=on_done)

    def action_show_history(self) -> None:
        if self._input_has_focus():
            return
        self.query_one("#main-tabs", TabbedContent).active = "tab-history"
        self._refresh_views()

    def action_show_descendants(self) -> None:
        if self._input_has_focus():
            return
        sample = self._get_selected_sample()
        if sample is None:
            return
        self.proc_filter.pids = [sample.pid]
        self.proc_filter.recursive = True
        self.query_one("#main-tabs", TabbedContent).active = "tab-processes"
        self._refresh_views()

    def action_show_parent(self) -> None:
        if self._input_has_focus() or self.latest_snapshot is None:
            return
        sample = self._get_selected_sample()
        if sample is None or not sample.ppid:
            return
        for proc in self.latest_snapshot.processes:
            if proc.pid == sample.ppid and not proc.is_exited:
                self.selected_identity = proc.identity
                self._refresh_views()
                return
        self.notify(f"Parent PID {sample.ppid} not in current snapshot.", severity="information")

    def action_cycle_theme(self) -> None:
        if self._input_has_focus():
            return
        self.theme_index = (self.theme_index + 1) % len(THEMES)
        screen = self.screen
        screen.remove_class("theme-light", "theme-high-contrast")
        theme = THEMES[self.theme_index]
        if theme == "light":
            screen.add_class("theme-light")
        elif theme == "high-contrast":
            screen.add_class("theme-high-contrast")
        self.notify(f"Theme: {theme} (press t to cycle)", severity="information")

    def action_show_help(self) -> None:
        if self._input_has_focus():
            return
        self.push_screen(HelpModal())

    def action_inspect_selected(self) -> None:
        if self._input_has_focus() or self.latest_snapshot is None:
            return
        sample = self._get_selected_sample()
        if sample is None:
            return
        by_pid = {p.pid: p for p in self.latest_snapshot.processes if not p.is_exited}
        ancestry = get_ancestry_chain(sample, by_pid)
        parent = by_pid.get(sample.ppid)
        hist = self.sampler.history_store.get(sample.identity)
        extra = self.sampler.inspect_process_details(sample.identity) if not sample.is_exited else {}

        def on_action(action_id: Optional[str]) -> None:
            if action_id == "act-parent":
                self.action_show_parent()
            elif action_id == "act-descendants":
                self.action_show_descendants()
            elif action_id == "act-pin":
                self.action_toggle_pin()
            elif action_id == "act-history":
                self.action_show_history()
            elif action_id == "act-compare":
                self.query_one("#main-tabs", TabbedContent).active = "tab-pinned"
            elif action_id == "act-copy":
                summary_text = format_sanitized_summary(sample, ancestry=ancestry)
                try:
                    from cross_platform.clipboard_utils import set_clipboard

                    set_clipboard(summary_text)
                    self.notify("Copied sanitized summary to clipboard.")
                except Exception:
                    self.copy_to_clipboard(summary_text)
                    self.notify("Copied sanitized summary.")

        self.push_screen(
            ProcessInspectorModal(
                sample=sample,
                ancestry=ancestry,
                parent=parent,
                history_series_cpu=hist.series("cpu") if hist else [],
                history_series_rss=hist.series("rss") if hist else [],
                is_pinned=sample.identity in self.pinned_identities,
                extra_details=extra,
            ),
            callback=on_action,
        )
