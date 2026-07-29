from __future__ import annotations

from pathlib import Path

from development_ledger.analysis import build_validation_event
from development_ledger.models import NormalizedTest
from development_ledger.plan import load_plan
from development_ledger.render import (
    render_architecture_review,
    render_local_handoff,
    render_progress,
    write_projections,
)


def _event(plan):
    return build_validation_event(
        event_id="run-1",
        timestamp="2026-07-29T00:00:00+00:00",
        plan=plan,
        tests=[
            NormalizedTest(
                id="pytest:tests/engine_test.py::test_preview",
                name="test_preview",
                status="passed",
                item_ids=["AC-001"],
            ),
            NormalizedTest(
                id="pytest:tests/cli_test.py::test_error_code",
                name="test_error_code",
                status="passed",
            ),
        ],
        provenance={"branch": "agent/demo", "commit": "abc", "working_tree_clean": True},
        prior_events=[],
        artifacts=["pytest.xml"],
    )


def test_render_progress_is_compact_orientation_document(plan_path):
    plan = load_plan(plan_path)
    text = render_progress(plan, [_event(plan)])

    assert "# Development Progress: Demo Plan" in text
    assert "## Plan Item State" in text
    assert "Request intake" in text
    assert "Session budget" in text
    assert "Recommended Next-Batch Candidates" in text
    assert "AC-001" in text
    assert "Run History" in text


def test_write_projections_creates_all_expected_files(plan_path, tmp_path: Path):
    plan = load_plan(plan_path)
    output = tmp_path / "ledger"

    write_projections(output, plan, [_event(plan)])

    assert {path.name for path in output.iterdir()} == {
        "LATEST.json",
        "PROGRESS.md",
        "TRACEABILITY.md",
        "MANUAL_CHECKS.md",
        "ARCHITECTURE_REVIEW.md",
        "LOCAL_HANDOFF.md",
    }


def test_local_handoff_contains_attempt_history_when_escalated(plan_path):
    plan = load_plan(plan_path)
    event = _event(plan)
    event["routing"] = {
        "decision": "handoff_local",
        "reason": "Persistent local failure",
        "model": "gpt-5.6-terra",
        "reasoning": "high",
    }
    event["failure_fingerprints"] = ["pytest:x|failed|AssertionError"]

    text = render_local_handoff(plan, [event])

    assert "Local Codex Diagnostic Handoff" in text
    assert "gpt-5.6-terra" in text
    assert "Attempts Already Recorded" in text
    assert "Plan revision" in text


def test_architecture_review_projection_explains_due_review(plan_path):
    plan = load_plan(plan_path)
    plan.session["architecture_review"]["requested"] = True
    event = _event(plan)

    text = render_architecture_review(plan, [event])

    assert "Architecture Review" in text
    assert "Due:** `yes`" in text
    assert "Review Questions" in text


def test_render_progress_without_events_and_inactive_handoff(plan_path):
    plan = load_plan(plan_path)

    progress = render_progress(plan, [])
    handoff = render_local_handoff(plan, [])

    assert "No validation run has been recorded" in progress
    assert "No local-LLM handoff is currently active" in handoff
