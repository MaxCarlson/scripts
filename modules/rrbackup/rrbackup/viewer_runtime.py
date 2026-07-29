"""Runtime routing for the interactive multi-page backup viewer."""

from __future__ import annotations

from typing import Any, List, Sequence

from . import cli_runtime
from .audit import AuditReport, collect_audit
from .inventory import BackupInventoryRecord
from .presentation import (
    interactive_available,
    render_backup_table,
    render_history,
    render_repository_summary,
    render_schedule_table,
)
from .repository_summary import RepositorySummary, collect_repository_summary
from .viewer import (
    VIEWER_PAGE_NAMES,
    build_demo_diagnostics_page,
    build_demo_records,
    build_demo_repository_page,
    build_diagnostics_page,
    build_repository_page,
    render_audit_summary,
    render_viewer_page_plain,
)
from .viewer_controller import build_summary_overview_page, run_viewer_dashboard

_DIAGNOSTIC_SECTIONS = (
    "configuration",
    "config-files",
    "paths",
    "inputs",
    "commands",
    "runtime",
    "environment",
    "provenance",
    "recommendations",
)


def _select_demo_records(args: Any) -> List[BackupInventoryRecord]:
    records = list(build_demo_records())
    if not getattr(args, "backup_name", None):
        return records
    normalized = args.backup_name.strip().lower()
    selected = [
        record for record in records if record.definition.name.lower() == normalized
    ]
    if len(selected) != 1:
        raise ValueError(
            "Demo backup name matched {0} definitions; exactly one is required: {1!r}".format(
                len(selected),
                args.backup_name,
            )
        )
    return selected


def _repository_summaries(
    records: Sequence[BackupInventoryRecord],
) -> List[RepositorySummary]:
    summaries: List[RepositorySummary] = []
    seen = set()
    for record in records:
        profile = record.definition.profile
        key = (profile.repository, profile.password_file, profile.restic_executable)
        if key in seen:
            continue
        seen.add(key)
        summaries.append(collect_repository_summary(profile))
    return summaries


def _diagnostic_report(record: BackupInventoryRecord, args: Any) -> AuditReport:
    return collect_audit(
        record.definition.profile,
        selected_sections=_DIAGNOSTIC_SECTIONS,
        include_legacy_evidence=args.include_legacy_evidence,
    )


def _full_audit(record: BackupInventoryRecord, args: Any) -> AuditReport:
    return collect_audit(
        record.definition.profile,
        include_legacy_evidence=args.include_legacy_evidence,
    )


def handle_view(args: Any) -> int:
    """Open the carousel or render one explicitly requested output section."""

    demo = bool(getattr(args, "demo", False))
    if demo:
        selected = _select_demo_records(args)
        payload = {
            "demo": True,
            "backups": [record.to_dict() for record in selected],
            "warnings": [],
        }
    else:
        inventory, selected = cli_runtime.records(args)
        payload = inventory.to_dict()

    section = getattr(args, "section", None) or "overview"
    structured = args.json or args.markdown or args.plain
    if not structured and section != "audit" and interactive_available():
        run_viewer_dashboard(
            selected,
            start_page=section if section in VIEWER_PAGE_NAMES else "overview",
            repository_loader=(
                (lambda: build_demo_repository_page(selected))
                if demo
                else (lambda: build_repository_page(_repository_summaries(selected)))
            ),
            diagnostics_loader=(
                build_demo_diagnostics_page
                if demo
                else (lambda: build_diagnostics_page(_diagnostic_report(selected[0], args)))
            ),
            demo=demo,
        )
        return cli_runtime.EXIT_OK

    if section == "overview":
        page = build_summary_overview_page(selected)
        cli_runtime.emit(
            {"section": section, "inventory": payload},
            args,
            text=render_viewer_page_plain(page),
            markdown=cli_runtime.inventory_markdown(selected),
        )
        return (
            cli_runtime.EXIT_UNHEALTHY
            if any(not record.health.healthy for record in selected)
            else cli_runtime.EXIT_OK
        )

    if section == "backups":
        cli_runtime.emit(
            {"section": section, "inventory": payload},
            args,
            text=render_backup_table(
                selected,
                colors=cli_runtime.theme(args),
                include_repository=True,
            ),
            markdown=cli_runtime.inventory_markdown(selected),
        )
        return (
            cli_runtime.EXIT_UNHEALTHY
            if any(not record.health.healthy for record in selected)
            else cli_runtime.EXIT_OK
        )

    if section == "history":
        cli_runtime.emit(
            {"section": section, "backups": [record.to_dict() for record in selected]},
            args,
            text=render_history(selected, colors=cli_runtime.theme(args)),
        )
        return cli_runtime.EXIT_OK

    if section == "schedules":
        cli_runtime.emit(
            {"section": section, "backups": [record.to_dict() for record in selected]},
            args,
            text=render_schedule_table(selected, colors=cli_runtime.theme(args)),
            markdown=cli_runtime.inventory_markdown(selected),
        )
        return cli_runtime.EXIT_OK

    if section == "repository":
        if demo:
            page = build_demo_repository_page(selected)
            cli_runtime.emit(
                {
                    "section": section,
                    "demo": True,
                    "repositories": [row.search_text for row in page.rows],
                },
                args,
                text=render_viewer_page_plain(page),
            )
            return cli_runtime.EXIT_OK
        summaries = _repository_summaries(selected)
        cli_runtime.emit(
            {
                "section": section,
                "repositories": [summary.to_dict() for summary in summaries],
            },
            args,
            text="\n\n".join(
                render_repository_summary(summary, colors=cli_runtime.theme(args))
                for summary in summaries
            ),
        )
        return (
            cli_runtime.EXIT_OK
            if all(summary.available for summary in summaries)
            else cli_runtime.EXIT_OPERATION_FAILED
        )

    if section == "diagnostics":
        if demo:
            page = build_demo_diagnostics_page()
            cli_runtime.emit(
                {
                    "section": section,
                    "demo": True,
                    "rows": [row.line for row in page.rows],
                },
                args,
                text=render_viewer_page_plain(page),
            )
            return cli_runtime.EXIT_OK
        report = _diagnostic_report(selected[0], args)
        cli_runtime.emit(
            report.to_dict(),
            args,
            text=render_viewer_page_plain(build_diagnostics_page(report)),
            markdown=report.to_markdown(),
        )
        return cli_runtime.EXIT_OK

    if demo:
        text = (
            "Audit export is intentionally unavailable in demo mode because demo mode "
            "does not inspect the host, configuration, environment, or repository."
        )
        cli_runtime.emit({"demo": True, "audit": None}, args, text=text, markdown=text)
        return cli_runtime.EXIT_OK

    report = _full_audit(selected[0], args)
    cli_runtime.emit(
        report.to_dict(),
        args,
        text=render_audit_summary(report),
        markdown=report.to_markdown(),
    )
    return cli_runtime.EXIT_OK
