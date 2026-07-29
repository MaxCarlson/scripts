from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rrbackup.viewer import build_demo_records
from rrbackup.viewer_dashboard import (
    build_live_backups_page,
    build_live_overview_page,
    materialize_expanded_page,
    run_viewer_dashboard,
)


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


def _records_with_progress():
    records = list(build_demo_records(now=NOW))
    run = records[4].latest_run
    assert run is not None
    run.metadata["progress"] = {
        "percent_display": 25.0,
        "bytes_per_second": 1024 * 1024,
        "eta_seconds": 30,
        "seconds_elapsed": 10,
        "files_done": 5,
        "total_files": 20,
        "bytes_done": 25 * 1024 * 1024,
        "total_bytes": 100 * 1024 * 1024,
        "current_files": ["/E/Phone/example.bin"],
    }
    return tuple(records)


def test_live_pages_surface_persisted_active_progress() -> None:
    records = _records_with_progress()
    overview = build_live_overview_page(records)
    backups = build_live_backups_page(records)

    activity = next(row for row in overview.rows if row.row_id == "overview:activity")
    running = next(row for row in backups.rows if "running-phone-sync" in row.row_id)

    assert "running-phone-sync 25.00%" in activity.line
    assert "RUNNING" in running.line
    assert "25.00%" in running.line
    assert "1.00 MiB/s" in running.line
    assert any("Current files" in line for line in running.details)


def test_materialized_expansion_keeps_details_inline_after_parent() -> None:
    page = build_live_overview_page(build_demo_records(now=NOW))
    first = page.rows[0]

    collapsed = materialize_expanded_page(page, set())
    expanded = materialize_expanded_page(page, {first.row_id})

    assert collapsed.rows[0].line.startswith("> ")
    assert expanded.rows[0].line.startswith("v ")
    assert len(expanded.rows) > len(collapsed.rows)
    assert expanded.rows[1].row_id.startswith(first.row_id + "::inline-detail::")
    assert expanded.rows[1].sort_values == first.sort_values


def test_dashboard_hotkeys_expand_collapse_and_use_reliable_page_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termdash.interactive_list as interactive_list

    records = build_demo_records(now=NOW)
    observed = {
        "headers": [],
        "counts": [],
        "footer": None,
    }

    class FakeInteractiveList:
        def __init__(self, **kwargs):
            self.state = SimpleNamespace(
                items=list(kwargs["items"]),
                visible=list(kwargs["items"]),
                header=kwargs["header"],
                columns_line=kwargs["columns_line"],
                sorters=kwargs["sorters"],
                sort_field=kwargs["initial_sort"],
                descending=kwargs["initial_order"] == "desc",
                filter_pattern="",
                exclusion_pattern="",
                scroll_offset=0,
                detail_view=False,
            )
            self.detail_formatter = kwargs["detail_formatter"]
            self.key_handler = kwargs["key_handler"]
            observed["footer"] = kwargs["footer_lines"]

        def _update_visible_items(self, reset_selection=False):
            del reset_selection
            self.state.visible = list(self.state.items)
            observed["headers"].append(self.state.header)
            observed["counts"].append(len(self.state.items))

        def run(self):
            initial_count = len(self.state.items)
            current = self.state.items[0]
            self.key_handler(ord("E"), current, self.state)
            expanded_count = len(self.state.items)
            self.key_handler(ord("C"), self.state.items[0], self.state)
            collapsed_count = len(self.state.items)
            self.key_handler(ord("n"), self.state.items[0], self.state)
            self.key_handler(ord("p"), self.state.items[0], self.state)
            observed["counts"].extend(
                [initial_count, expanded_count, collapsed_count]
            )

    monkeypatch.setattr(interactive_list, "InteractiveList", FakeInteractiveList)

    run_viewer_dashboard(
        records,
        repository_loader=lambda: build_live_backups_page(records),
        diagnostics_loader=lambda: build_live_overview_page(records),
        demo=True,
        refresh_interval_seconds=0,
    )

    assert observed["counts"][-2] > observed["counts"][-3]
    assert observed["counts"][-1] == observed["counts"][-3]
    assert "DEMO View: BACKUPS — pg. 2/6" in observed["headers"]
    assert observed["headers"][-1] == "DEMO View: OVERVIEW — pg. 1/6"
    assert "e/c: expand/collapse" in observed["footer"][0]
