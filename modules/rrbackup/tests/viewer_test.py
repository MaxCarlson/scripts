from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rrbackup import application
from rrbackup.audit import AuditReport
from rrbackup.models import RunState
from rrbackup.viewer import (
    VIEWER_PAGE_NAMES,
    build_backups_page,
    build_demo_diagnostics_page,
    build_demo_records,
    build_demo_repository_page,
    build_diagnostics_page,
    build_history_page,
    build_schedules_page,
    render_audit_summary,
    render_viewer_page_plain,
    select_backups,
)
from rrbackup.viewer_controller import (
    build_summary_overview_page,
    run_viewer_dashboard,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 18, 0, tzinfo=UTC)


def test_view_parser_exposes_safe_demo_mode() -> None:
    parser = application.build_parser("backup")

    args = parser.parse_args(["view", "--demo", "--section", "history"])
    default_args = parser.parse_args(["view"])

    assert args.demo is True
    assert args.section == "history"
    assert default_args.section == "overview"


def test_demo_records_cover_varied_states_without_touching_real_paths() -> None:
    records = build_demo_records(now=NOW)

    assert len(records) == 6
    assert {record.health.severity.value for record in records} == {
        "ok",
        "info",
        "warning",
        "critical",
    }
    assert {record.latest_run.state for record in records if record.latest_run} == {
        RunState.SUCCESS,
        RunState.SKIPPED,
        RunState.FAILURE,
        RunState.INTERRUPTED,
        RunState.RUNNING,
    }
    assert all(
        record.definition.profile.password_file.startswith("DEMO_ONLY/")
        for record in records
    )


def test_all_carousel_pages_render_demo_data() -> None:
    records = build_demo_records(now=NOW)
    pages = (
        build_summary_overview_page(records),
        build_backups_page(records),
        build_history_page(records),
        build_demo_repository_page(records),
        build_schedules_page(records),
        build_demo_diagnostics_page(),
    )

    assert tuple(page.name for page in pages) == VIEWER_PAGE_NAMES
    assert all(page.rows for page in pages)
    assert pages[0].columns == "CATEGORY           STATUS     SUMMARY"
    assert [row.row_id for row in pages[0].rows] == [
        "overview:backups",
        "overview:activity",
        "overview:completion",
        "overview:schedules",
        "overview:repositories",
    ]
    assert "RUNNING" in "\n".join(
        "\n".join(row.details) for row in pages[0].rows
    )


def test_diagnostics_and_audit_default_human_output_are_compact() -> None:
    report = AuditReport(
        generated_utc=NOW,
        profile="local-main",
        sections={
            "runtime": {
                "rrbackup_version": "2.0.0",
                "python_version": "3.12.10 test",
                "hostname": "Xeres",
            },
            "commands": {
                "backup": {"resolved": "backup.exe"},
                "restic": {"resolved": "restic.exe"},
            },
            "recommendations": ["Inspect the interrupted run."],
        },
        warnings=("Synthetic warning",),
    )

    diagnostics = render_viewer_page_plain(build_diagnostics_page(report))
    audit = render_audit_summary(report)

    assert "View: DIAGNOSTICS" in diagnostics
    assert "RUNTIME" in diagnostics
    assert "```json" not in diagnostics
    assert "Backup Audit Summary" in audit
    assert "Use --json" in audit
    assert "```json" not in audit


def test_carousel_switches_pages_and_loads_expensive_pages_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termdash.interactive_list as interactive_list

    records = build_demo_records(now=NOW)
    calls = {"repository": 0, "diagnostics": 0}
    observed_headers = []

    def repository_loader():
        calls["repository"] += 1
        return build_demo_repository_page(records)

    def diagnostics_loader():
        calls["diagnostics"] += 1
        return build_demo_diagnostics_page()

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

        def _update_visible_items(self, reset_selection=False):
            del reset_selection
            self.state.visible = list(self.state.items)
            observed_headers.append(self.state.header)

        def run(self):
            observed_headers.append(self.state.header)
            assert self.state.columns_line == "CATEGORY           STATUS     SUMMARY"
            self.key_handler(ord("]"), self.state.visible[0], self.state)
            self.key_handler(ord("4"), self.state.visible[0], self.state)

    monkeypatch.setattr(interactive_list, "InteractiveList", FakeInteractiveList)

    run_viewer_dashboard(
        records,
        repository_loader=repository_loader,
        diagnostics_loader=diagnostics_loader,
    )

    assert observed_headers[0] == "View: OVERVIEW — pg. 1/6"
    assert "View: BACKUPS — pg. 2/6" in observed_headers
    assert "View: REPOSITORY — pg. 4/6" in observed_headers
    assert calls == {"repository": 1, "diagnostics": 0}


def test_bare_view_routes_to_aggregate_carousel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rrbackup.viewer_runtime as viewer_runtime

    records = list(build_demo_records(now=NOW))
    captured = {}
    inventory = SimpleNamespace(to_dict=lambda: {"backups": []})
    args = SimpleNamespace(
        demo=False,
        backup_name=None,
        section="overview",
        json=False,
        markdown=False,
        plain=False,
        include_legacy_evidence=False,
    )

    monkeypatch.setattr(
        viewer_runtime.cli_runtime,
        "records",
        lambda current_args: (inventory, records),
    )
    monkeypatch.setattr(viewer_runtime, "interactive_available", lambda: True)

    def capture_dashboard(selected, **kwargs):
        captured["selected"] = list(selected)
        captured.update(kwargs)

    monkeypatch.setattr(viewer_runtime, "run_viewer_dashboard", capture_dashboard)

    result = viewer_runtime.handle_view(args)

    assert result == viewer_runtime.cli_runtime.EXIT_OK
    assert captured["selected"] == records
    assert captured["start_page"] == "overview"
    assert captured["demo"] is False


def test_plain_overview_is_aggregate_not_duplicate_backup_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rrbackup.viewer_runtime as viewer_runtime

    records = list(build_demo_records(now=NOW))
    inventory = SimpleNamespace(to_dict=lambda: {"backups": []})
    emitted = {}
    args = SimpleNamespace(
        demo=False,
        backup_name=None,
        section="overview",
        json=False,
        markdown=False,
        plain=True,
        include_legacy_evidence=False,
    )

    monkeypatch.setattr(
        viewer_runtime.cli_runtime,
        "records",
        lambda current_args: (inventory, records),
    )

    def capture_emit(payload, current_args, **kwargs):
        emitted["payload"] = payload
        emitted["text"] = kwargs["text"]

    monkeypatch.setattr(viewer_runtime.cli_runtime, "emit", capture_emit)

    result = viewer_runtime.handle_view(args)

    assert result == viewer_runtime.cli_runtime.EXIT_UNHEALTHY
    assert "View: OVERVIEW" in emitted["text"]
    assert "CATEGORY" in emitted["text"]
    assert "ACTIVITY" in emitted["text"]
    assert "LAST COMPLETE" not in emitted["text"]


def test_concise_run_selector_uses_unlabeled_row_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termdash.interactive_list as interactive_list

    records = build_demo_records(now=NOW)
    captured = {}

    class FakeInteractiveList:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.items = list(kwargs["items"])

        def get_selected_items(self):
            return [self.items[0]]

        def run(self):
            rendered = captured["formatter"](
                self.items[0],
                "name",
                240,
                True,
                True,
                0,
            )
            captured["rendered"] = rendered
            captured["key_handler"](
                ord("r"),
                self.items[0],
                SimpleNamespace(),
            )

    monkeypatch.setattr(interactive_list, "InteractiveList", FakeInteractiveList)

    selected = select_backups(
        records,
        title="Select backups",
        multi_select=True,
    )

    assert selected == [records[0]]
    assert "complete " not in captured["rendered"].lower()
    assert "attempt " not in captured["rendered"].lower()
    assert "next " not in captured["rendered"].lower()
    assert "missed " not in captured["rendered"].lower()
    assert "LAST COMPLETE" in captured["columns_line"]
