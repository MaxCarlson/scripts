"""Aggregate overview and controller for the interactive backup-view carousel."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .inventory import BackupInventoryRecord
from .models import RunRecord, RunState
from .presentation import human_age, human_datetime
from .viewer import (
    VIEWER_PAGE_NAMES,
    ViewerPage,
    ViewerRow,
    build_backups_page,
    build_history_page,
    build_schedules_page,
)

UTC = timezone.utc
_MIN_TIME = datetime.min.replace(tzinfo=UTC)


def _run_time(run: Optional[RunRecord]) -> Optional[datetime]:
    if run is None:
        return None
    return run.finished_utc or run.started_utc or run.created_utc


def _last_complete_time(record: BackupInventoryRecord) -> Optional[datetime]:
    snapshot_time = None if record.latest_snapshot is None else record.latest_snapshot.time
    run = record.latest_run
    successful_run_time = (
        _run_time(run)
        if run is not None and run.state == RunState.SUCCESS
        else None
    )
    values = [value for value in (snapshot_time, successful_run_time) if value is not None]
    return max(values) if values else None


def _summary_row(
    category: str,
    status: str,
    summary: str,
    details: Sequence[str],
    *,
    order: int,
) -> ViewerRow:
    line = "{0:<18} {1:<10} {2}".format(category.upper(), status.upper(), summary)
    return ViewerRow(
        row_id="overview:{0}".format(category.lower()),
        line=line,
        details=tuple(details),
        search_text="{0} {1} {2} {3}".format(
            category,
            status,
            summary,
            " ".join(details),
        ).lower(),
        sort_values={"category": order, "status": status.lower()},
    )


def build_summary_overview_page(
    records: Sequence[BackupInventoryRecord],
) -> ViewerPage:
    """Build an aggregate dashboard that is distinct from the backup list page."""

    if not records:
        return ViewerPage(
            name="overview",
            columns="CATEGORY           STATUS     SUMMARY",
            rows=(
                _summary_row(
                    "Backups",
                    "warning",
                    "No configured backups were found.",
                    ("No configured backups were found.",),
                    order=0,
                ),
            ),
            sort_fields=("category", "status"),
            initial_sort="category",
        )

    severity_counts = {severity: 0 for severity in ("ok", "info", "warning", "critical")}
    state_counts = {state: 0 for state in RunState}
    no_attempts = 0
    complete_times: List[datetime] = []
    manual_schedules = 0
    installed_schedules = 0
    disabled_schedules = 0
    missing_schedules = 0
    total_missed = 0
    unknown_missed = 0
    repositories: Dict[str, List[str]] = {}

    for record in records:
        severity_counts[record.health.severity.value] += 1
        run = record.latest_run
        if run is None:
            no_attempts += 1
        else:
            state_counts[run.state] += 1
        complete_time = _last_complete_time(record)
        if complete_time is not None:
            complete_times.append(complete_time)

        scheduler = record.scheduler_record
        if scheduler is None:
            if record.definition.schedule.type == "manual":
                manual_schedules += 1
            else:
                missing_schedules += 1
        elif scheduler.enabled is False:
            disabled_schedules += 1
        else:
            installed_schedules += 1

        if record.missed_runs is None:
            unknown_missed += 1
        else:
            total_missed += record.missed_runs

        repositories.setdefault(record.definition.profile.repository, []).append(
            record.definition.name
        )

    unhealthy = severity_counts["warning"] + severity_counts["critical"]
    health_status = "critical" if severity_counts["critical"] else (
        "warning" if severity_counts["warning"] else "ok"
    )
    health_summary = (
        "{0} configured; {1} healthy/info; {2} warning; {3} critical"
    ).format(
        len(records),
        severity_counts["ok"] + severity_counts["info"],
        severity_counts["warning"],
        severity_counts["critical"],
    )
    health_details = ["Backup health:"]
    health_details.extend(
        "  - {0}: {1}".format(
            record.definition.name,
            record.health.severity.value.upper(),
        )
        for record in records
    )
    if unhealthy:
        health_details.append("Unhealthy backups: {0}".format(unhealthy))

    active_states = {RunState.QUEUED, RunState.WAITING, RunState.RUNNING}
    error_states = {RunState.FAILURE, RunState.INTERRUPTED}
    active = sum(state_counts[state] for state in active_states)
    errors = sum(state_counts[state] for state in error_states)
    activity_status = "active" if active else ("critical" if errors else "ok")
    activity_summary = (
        "{0} active; {1} failed/interrupted; {2} successful; {3} without attempts"
    ).format(active, errors, state_counts[RunState.SUCCESS], no_attempts)
    activity_details = ["Latest attempt state by backup:"]
    activity_details.extend(
        "  - {0}: {1} at {2}".format(
            record.definition.name,
            "NONE" if record.latest_run is None else record.latest_run.state.value.upper(),
            human_datetime(_run_time(record.latest_run)),
        )
        for record in records
    )

    completed = len(complete_times)
    never_completed = len(records) - completed
    completion_status = "warning" if never_completed else "ok"
    newest_complete = max(complete_times) if complete_times else None
    completion_summary = "{0} completed; {1} never completed; newest {2}".format(
        completed,
        never_completed,
        human_age(newest_complete),
    )
    completion_details = ["Last completed backup:"]
    completion_details.extend(
        "  - {0}: {1}".format(
            record.definition.name,
            human_datetime(_last_complete_time(record)),
        )
        for record in records
    )

    schedule_problem_count = disabled_schedules + missing_schedules + total_missed
    schedule_status = "warning" if schedule_problem_count else "ok"
    schedule_summary = (
        "{0} installed; {1} manual; {2} disabled; {3} missing; {4} missed"
    ).format(
        installed_schedules,
        manual_schedules,
        disabled_schedules,
        missing_schedules,
        total_missed,
    )
    schedule_details = ["Schedule state by backup:"]
    schedule_details.extend(
        "  - {0}: {1}; next {2}; missed {3}".format(
            record.definition.name,
            (
                "MANUAL"
                if record.scheduler_record is None
                and record.definition.schedule.type == "manual"
                else "MISSING"
                if record.scheduler_record is None
                else "DISABLED"
                if record.scheduler_record.enabled is False
                else (record.scheduler_record.state or "ENABLED").upper()
            ),
            human_datetime(record.next_run),
            "unknown" if record.missed_runs is None else record.missed_runs,
        )
        for record in records
    )
    if unknown_missed:
        schedule_details.append(
            "Missed-run count is unknown for {0} backup(s).".format(unknown_missed)
        )

    repository_summary = "{0} repositories serving {1} backups".format(
        len(repositories),
        len(records),
    )
    repository_details = ["Repositories:"]
    for repository, names in sorted(repositories.items()):
        repository_details.append(
            "  - {0}: {1}".format(repository, ", ".join(sorted(names)))
        )

    rows = (
        _summary_row(
            "Backups",
            health_status,
            health_summary,
            health_details,
            order=0,
        ),
        _summary_row(
            "Activity",
            activity_status,
            activity_summary,
            activity_details,
            order=1,
        ),
        _summary_row(
            "Completion",
            completion_status,
            completion_summary,
            completion_details,
            order=2,
        ),
        _summary_row(
            "Schedules",
            schedule_status,
            schedule_summary,
            schedule_details,
            order=3,
        ),
        _summary_row(
            "Repositories",
            "ok",
            repository_summary,
            repository_details,
            order=4,
        ),
    )
    return ViewerPage(
        name="overview",
        columns="CATEGORY           STATUS     SUMMARY",
        rows=rows,
        sort_fields=("category", "status"),
        initial_sort="category",
    )


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


def run_viewer_dashboard(
    records: Sequence[BackupInventoryRecord],
    *,
    start_page: str = "overview",
    repository_loader: Callable[[], ViewerPage],
    diagnostics_loader: Callable[[], ViewerPage],
    demo: bool = False,
) -> None:
    """Run the six-page viewer with an aggregate default Overview page."""

    from termdash.interactive_list import InteractiveList

    loaders: Dict[str, Callable[[], ViewerPage]] = {
        "overview": lambda: build_summary_overview_page(records),
        "backups": lambda: build_backups_page(records),
        "history": lambda: build_history_page(records),
        "repository": repository_loader,
        "schedules": lambda: build_schedules_page(records),
        "diagnostics": diagnostics_loader,
    }
    cache: Dict[str, ViewerPage] = {}
    holder: Dict[str, Any] = {}
    page_index = VIEWER_PAGE_NAMES.index(
        start_page if start_page in VIEWER_PAGE_NAMES else "overview"
    )

    def load_page(index: int) -> ViewerPage:
        name = VIEWER_PAGE_NAMES[index]
        if name not in cache:
            cache[name] = loaders[name]()
        return cache[name]

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

    def apply_page(index: int) -> None:
        nonlocal page_index
        page_index = index % len(VIEWER_PAGE_NAMES)
        page = load_page(page_index)
        view = holder["view"]
        view.state.items = list(page.rows)
        view.state.header = page_header(page_index)
        view.state.columns_line = page.columns
        view.state.sorters = sorters_for(page)
        view.state.sort_field = page.initial_sort
        view.state.descending = page.descending
        view.state.filter_pattern = ""
        view.state.exclusion_pattern = ""
        view.state.scroll_offset = 0
        view.state.detail_view = False
        view.detail_formatter = lambda item: list(item.details)
        view._update_visible_items(reset_selection=True)

    def key_handler(key: int, current: ViewerRow, state: Any) -> Tuple[bool, bool]:
        del current, state
        if key in {ord("]"), 9}:
            apply_page(page_index + 1)
            return True, False
        if key == ord("["):
            apply_page(page_index - 1)
            return True, False
        if ord("1") <= key <= ord(str(len(VIEWER_PAGE_NAMES))):
            apply_page(key - ord("1"))
            return True, False
        return False, False

    initial = load_page(page_index)
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
            "[/]: previous/next view | Tab: next | 1-6: jump | Enter/i: details",
            "Up/Down/j/k: move | PgUp/PgDn: page | f: filter | Left/Right: scroll | Ctrl+Q: close",
        ],
        detail_formatter=lambda item: list(item.details),
        key_handler=key_handler,
        item_key_func=lambda item: item.row_id,
        dirs_first=False,
    )
    holder["view"] = view
    view.run()
