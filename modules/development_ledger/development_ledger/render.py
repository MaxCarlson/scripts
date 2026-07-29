"""Generate compact LLM-oriented projections from plan and event history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from development_ledger.analysis import current_manual_statuses
from development_ledger.models import PlanState


def write_projections(output_dir: Path, plan: PlanState, events: list[dict[str, Any]]) -> None:
    """Write all generated current-state and handoff projections."""

    output_dir.mkdir(parents=True, exist_ok=True)
    latest = events[-1] if events else {}
    _atomic_write(output_dir / "LATEST.json", json.dumps(latest, indent=4, ensure_ascii=False) + "\n")
    _atomic_write(output_dir / "PROGRESS.md", render_progress(plan, events))
    _atomic_write(output_dir / "TRACEABILITY.md", render_traceability(plan, events))
    _atomic_write(output_dir / "MANUAL_CHECKS.md", render_manual_checks(plan, events))
    _atomic_write(output_dir / "LOCAL_HANDOFF.md", render_local_handoff(plan, events))


def render_progress(plan: PlanState, events: list[dict[str, Any]]) -> str:
    """Render the primary fresh-LLM orientation document."""

    validations = [event for event in events if event.get("event_type") == "validation_run"]
    latest = validations[-1] if validations else None
    lines = [
        f"# Development Progress: {plan.title}",
        "",
        "> Generated from structured plan state and immutable validation/manual events. Do not edit manually.",
        "",
        "## Current State",
        "",
        f"- **Plan:** `{plan.plan_id}`",
        f"- **Project root:** `{plan.project_root}`",
        f"- **Stage:** `{plan.stage.get('id', '')}` — {plan.stage.get('title', '')}",
        f"- **Stage status:** `{plan.stage.get('status', 'unknown')}`",
    ]
    if latest:
        provenance = latest.get("provenance", {})
        progress = latest.get("progress", {})
        routing = latest.get("routing", {})
        summary = latest.get("test_summary", {})
        lines.extend(
            [
                f"- **Latest run:** `{latest.get('event_id', '')}`",
                f"- **Tested commit:** `{provenance.get('commit', '')}`",
                f"- **Progress:** `{progress.get('classification', 'unknown')}`",
                f"- **Routing:** `{routing.get('decision', 'unknown')}`",
                f"- **Tests:** {summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed, "
                f"{summary.get('errors', 0)} errors, {summary.get('skipped', 0)} skipped",
                "",
                "## Latest Intent and Judgment",
                "",
                f"- **Objective:** {latest.get('intent', {}).get('objective', '') or '(not declared)'}",
                f"- **Hypothesis:** {latest.get('intent', {}).get('hypothesis', '') or '(none)'}",
                f"- **Decision reason:** {routing.get('reason', '')}",
            ]
        )
        for reason in progress.get("reasons", []):
            lines.append(f"- **Progress evidence:** {reason}")
    else:
        lines.extend(["- **Latest run:** none", "", "No validation run has been recorded."])

    lines.extend(
        [
            "",
            "## Plan Item State",
            "",
            "| ID | Kind | Implementation | Automated | Manual | Verification |",
            "|---|---|---|---|---|---|",
        ]
    )
    latest_items = {item["id"]: item for item in latest.get("items", [])} if latest else {}
    for item in plan.items:
        state = latest_items.get(item.id, {})
        lines.append(
            f"| `{item.id}` | {item.kind} | {item.implementation} | {state.get('automated', 'not_run')} | "
            f"{state.get('manual', 'not_required')} | **{state.get('verification', item.implementation)}** |"
        )

    lines.extend(["", "## Persistent and Recent Failures", ""])
    if latest and latest.get("failure_fingerprints"):
        for fingerprint in latest["failure_fingerprints"]:
            persistence = _failure_run_count(validations, fingerprint)
            lines.append(f"- `{fingerprint}` — present in {persistence} validation run(s)")
    else:
        lines.append("- None in the latest validation run.")

    lines.extend(
        [
            "",
            "## Run History",
            "",
            "| Run | Commit | Progress | Routing | Pass | Fail/Error | Verified Δ |",
            "|---|---|---|---|---:|---:|---:|",
        ]
    )
    for event in validations:
        summary = event.get("test_summary", {})
        comparison = event.get("comparison", {})
        commit = str(event.get("provenance", {}).get("commit", ""))[:12]
        lines.append(
            f"| `{event.get('event_id', '')}` | `{commit}` | {event.get('progress', {}).get('classification', '')} | "
            f"{event.get('routing', {}).get('decision', '')} | {summary.get('passed', 0)} | "
            f"{int(summary.get('failed', 0)) + int(summary.get('errors', 0))} | {comparison.get('verified_delta', 0)} |"
        )

    lines.extend(["", "## Read Next", ""])
    if latest:
        for path in latest.get("artifacts", []):
            lines.append(f"- `{path}`")
    for path in plan.relevant_docs:
        lines.append(f"- `{path}`")
    if not latest and not plan.relevant_docs:
        lines.append("- Active plan document")
    return "\n".join(lines).rstrip() + "\n"


def render_traceability(plan: PlanState, events: list[dict[str, Any]]) -> str:
    """Render bidirectional plan-item to test/manual-check traceability."""

    latest = next((event for event in reversed(events) if event.get("event_type") == "validation_run"), None)
    latest_items = {item["id"]: item for item in latest.get("items", [])} if latest else {}
    lines = [
        f"# Traceability: {plan.title}",
        "",
        "> Generated. Plan items declare expected evidence; normalized results report actual evidence.",
        "",
        "## Item to Evidence",
        "",
    ]
    for item in plan.items:
        state = latest_items.get(item.id, {})
        lines.extend(
            [
                f"### `{item.id}` — {item.title}",
                "",
                f"- Kind: `{item.kind}`",
                f"- Implementation: `{item.implementation}`",
                f"- Verification: `{state.get('verification', item.implementation)}`",
                f"- Expected test patterns: {', '.join(f'`{value}`' for value in item.tests) or '(none)'}",
                "- Matched tests: "
                + (", ".join(f"`{value}`" for value in state.get("matched_test_ids", [])) or "(none)"),
                f"- Manual checks: {', '.join(f'`{value}`' for value in item.manual_checks) or '(none)'}",
                f"- Relevant files: {', '.join(f'`{value}`' for value in item.relevant_files) or '(none)'}",
                "",
            ]
        )

    lines.extend(["## Test to Item", ""])
    tests = latest.get("tests", []) if latest else []
    if not tests:
        lines.append("No normalized tests are available.")
    else:
        for test in tests:
            item_ids = set(test.get("item_ids", []))
            for item in plan.items:
                if test.get("id") in latest_items.get(item.id, {}).get("matched_test_ids", []):
                    item_ids.add(item.id)
            lines.append(
                f"- `{test.get('id', '')}` → "
                + (", ".join(f"`{value}`" for value in sorted(item_ids)) or "(regression-only)")
                + f" — **{test.get('status', '')}**"
            )
    return "\n".join(lines).rstrip() + "\n"


def render_manual_checks(plan: PlanState, events: list[dict[str, Any]]) -> str:
    """Render pending and completed user validation instructions."""

    statuses = current_manual_statuses(plan, events)
    lines = [
        f"# Manual Validation: {plan.title}",
        "",
        "> Generated. Complete only checks whose safety and environment requirements are understood.",
        "",
    ]
    if not plan.manual_checks:
        lines.append("No manual checks are declared for this plan.")
        return "\n".join(lines) + "\n"

    for check in plan.manual_checks:
        status = statuses.get(check.id, check.status)
        lines.extend(
            [
                f"## `{check.id}` — {check.title}",
                "",
                f"- **Status:** `{status}`",
                f"- **Platform:** `{check.platform}`",
                f"- **Safety:** `{check.safety}`",
                f"- **Plan items:** {', '.join(f'`{value}`' for value in check.item_ids) or '(none)'}",
                "",
                "### Instructions",
                "",
            ]
        )
        for index, instruction in enumerate(check.instructions, start=1):
            lines.append(f"{index}. {instruction}")
        lines.extend(["", "### Expected Result", "", check.expected, ""])
        if check.notes:
            lines.extend(["### Notes", "", check.notes, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_local_handoff(plan: PlanState, events: list[dict[str, Any]]) -> str:
    """Render a self-contained local-Codex handoff when routing recommends it."""

    latest = next((event for event in reversed(events) if event.get("event_type") == "validation_run"), None)
    if not latest or latest.get("routing", {}).get("decision") != "handoff_local":
        return (
            f"# Local Diagnostic Handoff: {plan.title}\n\n"
            "No local-LLM handoff is currently active. The latest routing decision does not require local Codex.\n"
        )

    routing = latest["routing"]
    provenance = latest.get("provenance", {})
    lines = [
        f"# Local Codex Diagnostic Handoff: {plan.title}",
        "",
        "## Assignment",
        "",
        "Diagnose and fix only the blocker described below. Do not redesign the full feature or implement "
        "unrelated plan stages.",
        "",
        "## Recommended Configuration",
        "",
        f"- **Model:** `{routing.get('model', 'gpt-5.6-terra')}`",
        f"- **Reasoning:** `{routing.get('reasoning', 'medium')}`",
        f"- **Reason:** {routing.get('reason', '')}",
        "",
        "## Repository State",
        "",
        f"- **Project root:** `{plan.project_root}`",
        f"- **Branch:** `{provenance.get('branch', '')}`",
        f"- **Tested commit:** `{provenance.get('commit', '')}`",
        f"- **Stage:** `{plan.stage.get('id', '')}` — {plan.stage.get('title', '')}",
        "",
        "## Intended Work",
        "",
        f"- **Objective:** {latest.get('intent', {}).get('objective', '')}",
        f"- **Hypothesis:** {latest.get('intent', {}).get('hypothesis', '') or '(none)'}",
        f"- **Target items:** {', '.join(f'`{value}`' for value in latest.get('intent', {}).get('target_ids', []))}",
        "",
        "## Current Failures",
        "",
    ]
    for fingerprint in latest.get("failure_fingerprints", []):
        lines.append(f"- `{fingerprint}`")
    if not latest.get("failure_fingerprints"):
        lines.append("- No normalized failure fingerprint was available; inspect the listed raw artifacts.")

    lines.extend(["", "## Attempts Already Recorded", ""])
    for event in [event for event in events if event.get("event_type") == "validation_run"][-4:]:
        lines.extend(
            [
                f"### `{event.get('event_id', '')}`",
                "",
                f"- Commit: `{event.get('provenance', {}).get('commit', '')}`",
                f"- Objective: {event.get('intent', {}).get('objective', '')}",
                f"- Hypothesis: {event.get('intent', {}).get('hypothesis', '') or '(none)'}",
                f"- Progress: `{event.get('progress', {}).get('classification', '')}`",
                f"- Failures: {len(event.get('failure_fingerprints', []))}",
                "",
            ]
        )

    lines.extend(
        [
            "## Required Work",
            "",
            "1. Read `PROGRESS.md`, `TRACEABILITY.md`, `LATEST.json`, the active plan, and the raw "
            "artifacts listed below.",
            "2. Reproduce the exact failure in the local environment.",
            "3. Identify the environment fact or root cause unavailable to the remote agent.",
            "4. Add or improve the narrowest practical regression test or diagnostic check.",
            "5. Make the smallest compatible source change required to fix the blocker.",
            "6. Preserve public interfaces and unrelated behavior.",
            "7. Run the complete project validation dispatcher after changes.",
            "8. Work on a separate local patch branch; do not edit the remote feature branch concurrently.",
            "9. Leave changes for user inspection, staging, commit, and push unless the user explicitly "
            "authorizes those actions.",
            "",
            "## Evidence Paths",
            "",
        ]
    )
    for path in latest.get("artifacts", []):
        lines.append(f"- `{path}`")
    for path in plan.relevant_docs:
        lines.append(f"- `{path}`")

    lines.extend(
        [
            "",
            "## Required Final Report",
            "",
            "Report: root cause, local/environment-specific evidence, files changed, tests added or modified, "
            "exact validation commands and exit codes, remaining uncertainty, and whether the patch is ready "
            "for user review.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _failure_run_count(validations: list[dict[str, Any]], fingerprint: str) -> int:
    return sum(fingerprint in event.get("failure_fingerprints", []) for event in validations)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
