"""Shared human, color, table, and interactive presentation helpers."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .inventory import BackupInventoryRecord
from .repository_summary import RepositorySummary

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_MIN_TIME = datetime.min.replace(tzinfo=timezone.utc)
_MAX_TIME = datetime.max.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Palette:
    """Consistent RRBackup terminal palette."""

    enabled: bool

    def _wrap(self, code: str, text: object) -> str:
        value = str(text)
        if not self.enabled:
            return value
        return "\033[{0}m{1}\033[0m".format(code, value)

    def heading(self, text: object) -> str:
        return self._wrap("1;36", text)

    def identifier(self, text: object) -> str:
        return self._wrap("1;36", text)

    def good(self, text: object) -> str:
        return self._wrap("1;32", text)

    def warning(self, text: object) -> str:
        return self._wrap("1;33", text)

    def bad(self, text: object) -> str:
        return self._wrap("1;31", text)

    def active(self, text: object) -> str:
        return self._wrap("1;35", text)

    def muted(self, text: object) -> str:
        return self._wrap("2", text)

    def value(self, text: object) -> str:
        return self._wrap("1;37", text)


def color_enabled(*, stream: Any = None, force: Optional[bool] = None) -> bool:
    """Return whether ANSI color should be emitted."""

    if force is not None:
        return force
    if os.environ.get("NO_COLOR") is not None:
        return False
    target = sys.stdout if stream is None else stream
    return bool(hasattr(target, "isatty") and target.isatty())


def palette(*, stream: Any = None, force: Optional[bool] = None) -> Palette:
    return Palette(color_enabled(stream=stream, force=force))


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _pad(text: str, width: int, *, align: str = "left") -> str:
    length = len(strip_ansi(text))
    padding = max(0, width - length)
    if align == "right":
        return (" " * padding) + text
    return text + (" " * padding)


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    right_aligned: Iterable[int] = (),
) -> str:
    """Render an ANSI-aware table with stable spacing."""

    normalized = [list(headers)] + [list(row) for row in rows]
    if not normalized or not headers:
        return ""
    widths = [
        max(len(strip_ansi(row[index])) for row in normalized)
        for index in range(len(headers))
    ]
    right = set(right_aligned)
    lines: List[str] = []
    for row_index, row in enumerate(normalized):
        cells = [
            _pad(row[index], widths[index], align="right" if index in right else "left")
            for index in range(len(headers))
        ]
        lines.append("  ".join(cells).rstrip())
        if row_index == 0:
            lines.append("  ".join("─" * width for width in widths).rstrip())
    return "\n".join(lines)


def human_bytes(value: Optional[int]) -> str:
    if value is None:
        return "-"
    amount = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    index = 0
    while abs(amount) >= 1024.0 and index < len(units) - 1:
        amount /= 1024.0
        index += 1
    precision = 0 if index == 0 else 2
    return "{0:.{1}f} {2}".format(amount, precision, units[index])


def human_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def human_age(value: Optional[datetime], *, now: Optional[datetime] = None) -> str:
    if value is None:
        return "never"
    current = (now or datetime.now().astimezone()).astimezone(value.tzinfo)
    seconds = max(0, int((current - value).total_seconds()))
    if seconds < 60:
        return "{0}s ago".format(seconds)
    minutes = seconds // 60
    if minutes < 60:
        return "{0}m ago".format(minutes)
    hours = minutes // 60
    if hours < 48:
        return "{0}h ago".format(hours)
    days = hours // 24
    if days < 60:
        return "{0}d ago".format(days)
    months = days // 30
    if months < 24:
        return "{0}mo ago".format(months)
    return "{0}y ago".format(days // 365)


def _health_text(record: BackupInventoryRecord, colors: Palette) -> str:
    severity = record.health.severity.value
    text = severity.upper()
    if severity in {"ok", "info"}:
        return colors.good(text)
    if severity == "warning":
        return colors.warning(text)
    return colors.bad(text)


def _schedule_state(record: BackupInventoryRecord, colors: Palette) -> str:
    scheduler = record.scheduler_record
    if scheduler is None:
        if record.definition.schedule.type == "manual":
            return colors.warning("MANUAL")
        return colors.bad("MISSING")
    if scheduler.enabled is False:
        return colors.bad("DISABLED")
    return colors.good((scheduler.state or "ENABLED").upper())


def render_backup_table(
    records: Sequence[BackupInventoryRecord],
    *,
    colors: Optional[Palette] = None,
    include_repository: bool = False,
) -> str:
    """Render compact two-line backup records."""

    theme = colors or palette()
    if not records:
        return theme.warning("No configured backups were found.")
    headers = [
        theme.heading("Backup"),
        theme.heading("Health"),
        theme.heading("Latest"),
        theme.heading("Next"),
        theme.heading("Missed"),
    ]
    if include_repository:
        headers.append(theme.heading("Repository"))
    rows: List[List[str]] = []
    for record in records:
        latest = record.latest_snapshot
        missed = "-" if record.missed_runs is None else str(record.missed_runs)
        if record.missed_runs:
            missed = theme.bad(missed)
        elif record.missed_runs == 0:
            missed = theme.good(missed)
        first = [
            theme.identifier(record.definition.name),
            _health_text(record, theme),
            human_age(None if latest is None else latest.time),
            human_datetime(record.next_run),
            missed,
        ]
        if include_repository:
            first.append(record.definition.profile.repository)
        rows.append(first)
        detail = [
            theme.muted("  └─ {0}".format(record.definition.source_summary)),
            theme.muted(_schedule_state(record, theme)),
            theme.muted(record.definition.schedule_text),
            theme.muted(record.definition.retention_text),
            "",
        ]
        if include_repository:
            detail.append("")
        rows.append(detail)
    return render_table(headers, rows, right_aligned=(4,))


def render_schedule_table(
    records: Sequence[BackupInventoryRecord],
    *,
    colors: Optional[Palette] = None,
) -> str:
    """Render one backup row followed by one schedule/retention row."""

    theme = colors or palette()
    if not records:
        return theme.warning("No configured backups were found.")
    headers = [
        theme.heading("Backup"),
        theme.heading("State"),
        theme.heading("Last run"),
        theme.heading("Next run"),
        theme.heading("Missed"),
    ]
    rows: List[List[str]] = []
    for record in records:
        scheduler = record.scheduler_record
        missed = "-" if record.missed_runs is None else str(record.missed_runs)
        missed_text = theme.bad(missed) if record.missed_runs else missed
        rows.append(
            [
                theme.identifier(record.definition.name),
                _schedule_state(record, theme),
                "-" if scheduler is None else (scheduler.last_run or "-"),
                human_datetime(record.next_run),
                missed_text,
            ]
        )
        rows.append(
            [
                theme.muted("  └─ {0}".format(record.definition.schedule_text)),
                theme.muted(record.definition.retention_text),
                theme.muted("task: {0}".format(record.definition.task_name)),
                "",
                "",
            ]
        )
    return render_table(headers, rows, right_aligned=(4,))


def render_history(
    records: Sequence[BackupInventoryRecord],
    *,
    colors: Optional[Palette] = None,
) -> str:
    theme = colors or palette()
    lines: List[str] = [theme.heading("Backup History")]
    events: List[Tuple[datetime, str]] = []
    for record in records:
        if record.latest_snapshot is not None:
            snapshot = record.latest_snapshot
            events.append(
                (
                    snapshot.time,
                    "{0}  {1}  snapshot {2}".format(
                        human_datetime(snapshot.time),
                        theme.identifier(record.definition.name),
                        snapshot.short_id,
                    ),
                )
            )
        if record.latest_run is not None:
            run = record.latest_run
            events.append(
                (
                    run.created_utc,
                    "{0}  {1}  run {2} ({3})".format(
                        human_datetime(run.created_utc),
                        theme.identifier(record.definition.name),
                        run.run_id[:8],
                        run.state.value,
                    ),
                )
            )
    for _, line in sorted(events, key=lambda item: item[0], reverse=True):
        lines.append("● " + line)
    if len(lines) == 1:
        lines.append(theme.warning("No snapshot or run history was found."))
    return "\n".join(lines)


def render_repository_summary(
    summary: RepositorySummary,
    *,
    colors: Optional[Palette] = None,
) -> str:
    """Render a combined, labeled repository summary."""

    theme = colors or palette()
    status = theme.good("AVAILABLE") if summary.available else theme.bad("UNAVAILABLE")
    latest = summary.latest_snapshot
    lines = [
        theme.heading("Repository"),
        "  Location:       {0}".format(theme.identifier(summary.repository)),
        "  Status:         {0}".format(status),
        "  Format:         {0}".format(summary.format_version or "unknown"),
        "  Repository ID:  {0}".format(summary.repository_id or "unknown"),
        "  Snapshots:      {0}".format(summary.snapshot_count),
        "  Latest:         {0}".format(
            "none"
            if latest is None
            else "{0} at {1}".format(latest.short_id, human_datetime(latest.time))
        ),
        "",
        theme.heading("Keys"),
    ]
    lines.extend("  {0}".format(line) for line in summary.key_lines)
    if not summary.key_lines:
        lines.append("  " + theme.warning("No key metadata returned."))
    lines.extend(["", theme.heading("Locks")])
    if summary.lock_lines:
        lines.extend("  {0}".format(line) for line in summary.lock_lines)
    else:
        lines.append("  " + theme.good("No repository locks."))
    lines.extend(["", theme.heading("Storage statistics")])
    if summary.storage is None:
        lines.append("  " + theme.warning("Not cached. Run: backup repo --refresh-storage"))
    else:
        payload = summary.storage.payload
        lines.extend(
            [
                "  Generated:      {0}".format(human_datetime(summary.storage.generated_utc)),
                "  Snapshots:      {0}".format(payload.get("snapshots_count", "-")),
                "  Files:          {0:,}".format(int(payload.get("total_file_count", 0))),
                "  Restore size:   {0}".format(human_bytes(int(payload.get("total_size", 0)))),
            ]
        )
    if summary.warnings:
        lines.extend(["", theme.heading("Warnings")])
        lines.extend("  {0}".format(theme.warning(value)) for value in summary.warnings)
    return "\n".join(lines)


def backup_detail_lines(record: BackupInventoryRecord) -> List[str]:
    """Build expandable detail content used by the shared interactive list."""

    definition = record.definition
    latest = record.latest_snapshot
    scheduler = record.scheduler_record
    lines = [
        "Name: {0}".format(definition.name),
        "Health: {0}".format(record.health.severity.value.upper()),
        "Repository: {0}".format(definition.profile.repository),
        "Sources:",
    ]
    lines.extend("  - {0}".format(value) for value in definition.sources)
    if definition.excludes:
        lines.append("Exclusions:")
        lines.extend("  - {0}".format(value) for value in definition.excludes)
    lines.extend(
        [
            "Schedule: {0}".format(definition.schedule_text),
            "Retention: {0}".format(definition.retention_text),
            "Task: {0}".format(definition.task_name),
            "Next expected run: {0}".format(human_datetime(record.next_run)),
            "Missed runs: {0}".format("unknown" if record.missed_runs is None else record.missed_runs),
            "Latest snapshot: {0}".format(
                "none"
                if latest is None
                else "{0} at {1}".format(latest.short_id, human_datetime(latest.time))
            ),
            "Scheduler: {0}".format("not installed" if scheduler is None else scheduler.identifier),
        ]
    )
    if record.health.issues:
        lines.append("Health findings:")
        lines.extend(
            "  - [{0}] {1}".format(issue.severity.value.upper(), issue.message)
            for issue in record.health.issues
        )
    if record.warnings:
        lines.append("Warnings:")
        lines.extend("  - {0}".format(value) for value in record.warnings)
    return lines


class _SelectionComplete(Exception):
    pass


def interactive_available() -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        from termdash.interactive_list import InteractiveList  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def browse_backups(
    records: Sequence[BackupInventoryRecord],
    *,
    title: str,
    multi_select: bool = False,
    action_key: Optional[str] = None,
    action_label: Optional[str] = None,
) -> List[BackupInventoryRecord]:
    """Open the shared TermDash list and return explicitly selected records."""

    if not records or not interactive_available():
        return []

    from termdash.interactive_list import InteractiveList

    selected: List[BackupInventoryRecord] = []
    holder: Dict[str, Any] = {}

    def formatter(
        item: BackupInventoryRecord,
        sort_field: str,
        width: int,
        show_date: bool,
        show_time: bool,
        scroll_offset: int,
    ) -> str:
        del sort_field, show_date, show_time
        latest = "never" if item.latest_snapshot is None else human_age(item.latest_snapshot.time)
        missed = "?" if item.missed_runs is None else str(item.missed_runs)
        line = "{0:<20} {1:<9} latest {2:<10} next {3:<16} missed {4:<4} {5}".format(
            item.definition.name,
            item.health.severity.value.upper(),
            latest,
            human_datetime(item.next_run),
            missed,
            item.definition.source_summary,
        )
        if scroll_offset:
            line = line[scroll_offset:]
        return line.ljust(width)[:width]

    def filter_item(item: BackupInventoryRecord, pattern: str) -> bool:
        needle = pattern.lower().replace("*", "")
        haystack = " ".join(
            [
                item.definition.name,
                item.definition.source_summary,
                item.definition.profile.repository,
                item.definition.schedule_text,
                item.health.severity.value,
            ]
        ).lower()
        return needle in haystack

    def key_handler(key: int, current: BackupInventoryRecord, state: Any) -> Tuple[bool, bool]:
        del state
        if action_key and key in {ord(action_key.lower()), ord(action_key.upper())}:
            view = holder["view"]
            chosen = view.get_selected_items() if multi_select else [current]
            if not chosen:
                chosen = [current]
            selected.extend(chosen)
            raise _SelectionComplete()
        return False, False

    footer = [
        "Up/Down/j/k: move | PgUp/PgDn: page | f: filter | Enter/i: details | Left/Right: scroll",
    ]
    if multi_select:
        footer.append("Space: select/deselect")
    if action_key and action_label:
        footer.append("{0}: {1} | Ctrl+Q: cancel".format(action_key.upper(), action_label))
    else:
        footer.append("Ctrl+Q: close")

    view = InteractiveList(
        items=list(records),
        sorters={
            "name": lambda item: item.definition.name.lower(),
            "health": lambda item: item.health.severity.value,
            "latest": lambda item: _MIN_TIME if item.latest_snapshot is None else item.latest_snapshot.time,
            "next": lambda item: _MAX_TIME if item.next_run is None else item.next_run,
            "missed": lambda item: -1 if item.missed_runs is None else item.missed_runs,
        },
        formatter=formatter,
        filter_func=filter_item,
        initial_sort="name",
        initial_order="asc",
        header=title,
        columns_line="BACKUP               HEALTH    LATEST         NEXT             MISSED SOURCES",
        footer_lines=footer,
        detail_formatter=backup_detail_lines,
        key_handler=key_handler,
        multi_select=multi_select,
        item_key_func=lambda item: item.definition.name,
        dirs_first=False,
    )
    holder["view"] = view
    try:
        view.run()
    except _SelectionComplete:
        pass
    return selected
