"""Expandable, live-refreshing controller for the backup-view carousel."""

from __future__ import annotations

import curses
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .inventory import BackupInventoryRecord
from .models import RunState
from .presentation import backup_detail_lines, human_bytes
from .state import RunStateStore
from .viewer import (
    VIEWER_PAGE_NAMES,
    ViewerPage,
    ViewerRow,
    build_history_page,
    build_schedules_page,
)
from .viewer_controller import build_summary_overview_page


_DETAIL_TOKEN = "::inline-detail::"
_ACTIVE_STATES = {RunState.QUEUED, RunState.WAITING, RunState.RUNNING}


def _progress_mapping(record: BackupInventoryRecord) -> Optional[Mapping[str, Any]]:
    run = record.latest_run
    if run is None:
        return None
    value = run.metadata.get("progress")
    return value if isinstance(value, Mapping) else None


def _duration(value: Any) -> str:
    if value is None:
        return "-"
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "-"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return "{0:02d}:{1:02d}:{2:02d}".format(hours, minutes, secs)
    return "{0:02d}:{1:02d}".format(minutes, secs)


def _percent(progress: Optional[Mapping[str, Any]]) -> str:
    if progress is None:
        return "-"
    try:
        return "{0:.2f}%".format(float(progress.get("percent_display", 0.0)))
    except (TypeError, ValueError):
        return "-"


def _speed(progress: Optional[Mapping[str, Any]]) -> str:
    if progress is None:
        return "-"
    try:
        return "{0}/s".format(human_bytes(int(float(progress.get("bytes_per_second", 0)))))
    except (TypeError, ValueError):
        return "-"


def _progress_details(record: BackupInventoryRecord) -> Tuple[str, ...]:
    progress = _progress_mapping(record)
    if progress is None:
        return tuple()
    files = "{0}/{1}".format(
        progress.get("files_done", 0),
        progress.get("total_files", 0),
    )
    byte_text = "{0}/{1}".format(
        human_bytes(int(progress.get("bytes_done", 0))),
        human_bytes(int(progress.get("total_bytes", 0))),
    )
    lines = [
        "Live aggregate Restic progress",
        "  Percent: {0}".format(_percent(progress)),
        "  Files: {0}".format(files),
        "  Bytes: {0}".format(byte_text),
        "  Speed: {0}".format(_speed(progress)),
        "  Elapsed: {0}".format(_duration(progress.get("seconds_elapsed"))),
        "  ETA: {0}".format(_duration(progress.get("eta_seconds"))),
    ]
    current_files = progress.get("current_files", [])
    if current_files:
        lines.append("  Current files:")
        lines.extend("    - {0}".format(value) for value in current_files)
    return tuple(lines)


def build_live_overview_page(
    records: Sequence[BackupInventoryRecord],
) -> ViewerPage:
    """Build the aggregate Overview with active progress in Activity details."""

    page = build_summary_overview_page(records)
    active = [
        record
        for record in records
        if record.latest_run is not None and record.latest_run.state in _ACTIVE_STATES
    ]
    if not active:
        return page

    rows: List[ViewerRow] = []
    for row in page.rows:
        if row.row_id != "overview:activity":
            rows.append(row)
            continue
        summaries = []
        details = list(row.details)
        details.append("")
        details.append("Active progress:")
        for record in active:
            progress = _progress_mapping(record)
            summaries.append(
                "{0} {1}".format(record.definition.name, _percent(progress))
            )
            details.append(
                "  - {0}: {1}; {2}; ETA {3}".format(
                    record.definition.name,
                    _percent(progress),
                    _speed(progress),
                    _duration(None if progress is None else progress.get("eta_seconds")),
                )
            )
        rows.append(
            replace(
                row,
                line="{0} | {1}".format(row.line, ", ".join(summaries)),
                details=tuple(details),
                search_text="{0} {1}".format(row.search_text, " ".join(summaries)).lower(),
            )
        )
    return replace(page, rows=tuple(rows))


def build_live_backups_page(
    records: Sequence[BackupInventoryRecord],
) -> ViewerPage:
    """Build the backup inventory page with persisted live progress columns."""

    rows: List[ViewerRow] = []
    for record in records:
        run = record.latest_run
        state = "NONE" if run is None else run.state.value.upper()
        progress = _progress_mapping(record)
        line = "{0:<20} {1:<12} {2:<9} {3:<14} {4:<9} {5:<24} {6}".format(
            record.definition.name,
            state,
            _percent(progress),
            _speed(progress),
            _duration(None if progress is None else progress.get("eta_seconds")),
            record.definition.source_summary,
            record.definition.profile.repository,
        )
        details = list(backup_detail_lines(record))
        details.extend([""] + list(_progress_details(record)) if progress is not None else [])
        rows.append(
            ViewerRow(
                row_id="backup:{0}".format(record.definition.name),
                line=line,
                details=tuple(details),
                search_text=" ".join(
                    (
                        record.definition.name,
                        state,
                        _percent(progress),
                        record.definition.source_summary,
                        record.definition.profile.repository,
                        " ".join(_progress_details(record)),
                    )
                ).lower(),
                sort_values={
                    "name": record.definition.name.lower(),
                    "state": state,
                    "progress": float(
                        0.0 if progress is None else progress.get("percent_display", 0.0)
                    ),
                    "repository": record.definition.profile.repository.lower(),
                },
            )
        )
    if not rows:
        rows.append(
            ViewerRow(
                row_id="backup:none",
                line="No configured backups were found.",
                details=("No configured backups were found.",),
                search_text="no configured backups",
                sort_values={"name": "", "state": "", "progress": 0.0, "repository": ""},
            )
        )
    return ViewerPage(
        name="backups",
        columns=(
            "BACKUP               STATE        PROGRESS  SPEED          ETA       "
            "SOURCES                  REPOSITORY"
        ),
        rows=tuple(rows),
        sort_fields=("name", "state", "progress", "repository"),
        initial_sort="name",
    )


def _parent_id(row_id: str) -> str:
    return row_id.split(_DETAIL_TOKEN, 1)[0]


def materialize_expanded_page(
    page: ViewerPage,
    expanded: Set[str],
) -> ViewerPage:
    """Insert inline detail rows directly after each expanded parent row."""

    rows: List[ViewerRow] = []
    for row in page.rows:
        has_details = bool(row.details)
        is_expanded = row.row_id in expanded and has_details
        marker = "v " if is_expanded else "> " if has_details else "  "
        parent = replace(
            row,
            line=marker + row.line,
            search_text=(row.search_text + " " + " ".join(row.details)).lower(),
        )
        rows.append(parent)
        if not is_expanded:
            continue
        for index, detail in enumerate(row.details):
            if not detail.strip():
                continue
            rows.append(
                ViewerRow(
                    row_id="{0}{1}{2}".format(row.row_id, _DETAIL_TOKEN, index),
                    line="    {0}".format(detail),
                    details=row.details,
                    search_text=parent.search_text,
                    sort_values=dict(row.sort_values),
                )
            )
    return replace(page, columns="  " + page.columns, rows=tuple(rows))


def _viewer_formatter(
    item: ViewerRow,
    sort_field: str,
    width: int,
    show_date: bool,
    show_time: bool,
    scroll_offset: int,
) -> str:
    del sort_field, show_date, show_time
    visible = item.line[scroll_offset:] if scroll_offset else item.line
    return visible.ljust(width)[:width]


def _viewer_filter(item: ViewerRow, pattern: str) -> bool:
    needle = pattern.lower().replace("*", "")
    return needle in item.search_text


def _refresh_records(
    records: Sequence[BackupInventoryRecord],
) -> Tuple[Tuple[BackupInventoryRecord, ...], bool]:
    refreshed: List[BackupInventoryRecord] = []
    changed = False
    for record in records:
        store = RunStateStore(
            Path(record.definition.profile.status_file).parent / "rrbackup-state"
        )
        latest = store.load_latest()
        if latest is not None and latest.profile != record.definition.profile.name:
            latest = record.latest_run
        old_payload = None if record.latest_run is None else record.latest_run.to_dict()
        new_payload = None if latest is None else latest.to_dict()
        if old_payload != new_payload:
            changed = True
            refreshed.append(replace(record, latest_run=latest))
        else:
            refreshed.append(record)
    return tuple(refreshed), changed


def run_viewer_dashboard(
    records: Sequence[BackupInventoryRecord],
    *,
    start_page: str = "overview",
    repository_loader: Callable[[], ViewerPage],
    diagnostics_loader: Callable[[], ViewerPage],
    demo: bool = False,
    refresh_interval_seconds: float = 1.0,
) -> None:
    """Run the six-page viewer with expansion and live progress refresh."""

    from termdash.interactive_list import InteractiveList

    current_records: Tuple[BackupInventoryRecord, ...] = tuple(records)
    cache: Dict[str, ViewerPage] = {}
    expanded: Dict[str, Set[str]] = {name: set() for name in VIEWER_PAGE_NAMES}
    holder: Dict[str, Any] = {}
    page_index = VIEWER_PAGE_NAMES.index(
        start_page if start_page in VIEWER_PAGE_NAMES else "overview"
    )

    def loaders() -> Dict[str, Callable[[], ViewerPage]]:
        return {
            "overview": lambda: build_live_overview_page(current_records),
            "backups": lambda: build_live_backups_page(current_records),
            "history": lambda: build_history_page(current_records),
            "repository": repository_loader,
            "schedules": lambda: build_schedules_page(current_records),
            "diagnostics": diagnostics_loader,
        }

    def load_page(index: int) -> ViewerPage:
        name = VIEWER_PAGE_NAMES[index]
        if name not in cache:
            cache[name] = loaders()[name]()
        return cache[name]

    def displayed_page(index: int) -> ViewerPage:
        page = load_page(index)
        return materialize_expanded_page(page, expanded[page.name])

    def sorters_for(page: ViewerPage) -> Dict[str, Callable[[ViewerRow], Any]]:
        return {
            field_name: (
                lambda item, field_name=field_name: item.sort_values.get(field_name)
            )
            for field_name in page.sort_fields
        }

    def page_header(index: int) -> str:
        prefix = "DEMO " if demo else ""
        return "{0}View: {1} — pg. {2}/{3}".format(
            prefix,
            VIEWER_PAGE_NAMES[index].upper(),
            index + 1,
            len(VIEWER_PAGE_NAMES),
        )

    def apply_page(index: int, *, reset_selection: bool = True) -> None:
        nonlocal page_index
        page_index = index % len(VIEWER_PAGE_NAMES)
        page = displayed_page(page_index)
        view = holder["view"]
        view.state.items = list(page.rows)
        view.state.header = page_header(page_index)
        view.state.columns_line = page.columns
        view.state.sorters = sorters_for(page)
        view.state.sort_field = page.initial_sort
        view.state.descending = page.descending
        view.state.scroll_offset = 0
        view.state.detail_view = False
        view.detail_formatter = lambda item: list(item.details)
        view._update_visible_items(reset_selection=reset_selection)

    def toggle_current(current: ViewerRow, expand: Optional[bool]) -> None:
        page = load_page(page_index)
        row_id = _parent_id(current.row_id)
        row = next((value for value in page.rows if value.row_id == row_id), None)
        if row is None or not row.details:
            return
        values = expanded[page.name]
        should_expand = row_id not in values if expand is None else expand
        if should_expand:
            values.add(row_id)
        else:
            values.discard(row_id)
        apply_page(page_index, reset_selection=False)

    def expand_all(value: bool) -> None:
        page = load_page(page_index)
        expanded[page.name] = (
            {row.row_id for row in page.rows if row.details} if value else set()
        )
        apply_page(page_index, reset_selection=True)

    def refresh_live_records() -> bool:
        nonlocal current_records
        if demo:
            return False
        refreshed, changed = _refresh_records(current_records)
        if not changed:
            return False
        current_records = refreshed
        for name in ("overview", "backups", "history"):
            cache.pop(name, None)
        if VIEWER_PAGE_NAMES[page_index] in {"overview", "backups", "history"}:
            apply_page(page_index, reset_selection=False)
        return True

    def key_handler(key: int, current: ViewerRow, state: Any) -> Tuple[bool, bool]:
        del state
        if key == 0:
            refresh_live_records()
            return True, False
        if key in {ord("]"), 9, ord("n"), ord("+"), ord("=")}:
            apply_page(page_index + 1)
            return True, False
        if key in {ord("["), ord("p"), ord("-")}:
            apply_page(page_index - 1)
            return True, False
        if key == ord("e"):
            toggle_current(current, None)
            return True, False
        if key == ord("c"):
            toggle_current(current, False)
            return True, False
        if key == ord("E"):
            expand_all(True)
            return True, False
        if key == ord("C"):
            expand_all(False)
            return True, False
        if ord("1") <= key <= ord(str(len(VIEWER_PAGE_NAMES))):
            apply_page(key - ord("1"))
            return True, False
        return False, False

    initial = displayed_page(page_index)
    view = InteractiveList(
        items=list(initial.rows),
        sorters=sorters_for(initial),
        formatter=_viewer_formatter,
        filter_func=_viewer_filter,
        initial_sort=initial.initial_sort,
        initial_order="desc" if initial.descending else "asc",
        header=page_header(page_index),
        columns_line=initial.columns,
        footer_lines=[
            "p/n or -/+: previous/next | 1-6: jump | e/c: expand/collapse | E/C: all",
            "Up/Down/j/k: move | PgUp/PgDn: page | f: filter | Enter/i: full details | Ctrl+Q: close",
        ],
        detail_formatter=lambda item: list(item.details),
        key_handler=key_handler,
        item_key_func=lambda item: item.row_id,
        dirs_first=False,
    )
    holder["view"] = view

    stop_refresh = threading.Event()
    wake_thread: Optional[threading.Thread] = None
    if refresh_interval_seconds > 0 and not demo:
        def wake() -> None:
            while not stop_refresh.wait(refresh_interval_seconds):
                try:
                    curses.ungetch(0)
                except curses.error:
                    return

        wake_thread = threading.Thread(
            target=wake,
            name="rrbackup-view-refresh",
            daemon=True,
        )
        wake_thread.start()
    try:
        view.run()
    finally:
        stop_refresh.set()
        if wake_thread is not None:
            wake_thread.join(timeout=2)
