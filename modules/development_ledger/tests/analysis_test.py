from __future__ import annotations

from development_ledger.analysis import (
    build_validation_event,
    evaluate_items,
    recommend_batch_candidates,
    recommend_local_model,
)
from development_ledger.models import NormalizedTest
from development_ledger.plan import load_plan


def _provenance(commit: str) -> dict:
    return {
        "repo_root": "/repo",
        "branch": "agent/demo",
        "commit": commit,
        "baseline_commit": "",
        "working_tree_clean": True,
        "working_tree_status": [],
        "changed_files": [],
        "diff_stat": "",
    }


def test_evaluate_items_separates_automated_and_manual_state(plan_path):
    plan = load_plan(plan_path)
    tests = [
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
    ]

    items = evaluate_items(plan, tests)

    assert items[0]["automated"] == "passed"
    assert items[0]["verification"] == "manual_pending"
    assert items[1]["verification"] == "verified"


def test_build_event_detects_persistent_failure_and_loop(plan_path):
    plan = load_plan(plan_path)
    failing = NormalizedTest(
        id="pytest:tests/engine_test.py::test_preview",
        name="test_preview",
        status="failed",
        message="AssertionError",
        item_ids=["AC-001"],
    )
    first = build_validation_event(
        event_id="run-1",
        timestamp="2026-07-29T00:00:00+00:00",
        plan=plan,
        tests=[failing],
        provenance=_provenance("a" * 40),
        prior_events=[],
    )
    first["progress"] = {"classification": "stalled", "material_progress": False, "reasons": []}
    plan.session["request"]["status"] = "no_new_request"
    plan.session["request"]["resolution"] = "none"

    second = build_validation_event(
        event_id="run-2",
        timestamp="2026-07-29T01:00:00+00:00",
        plan=plan,
        tests=[failing],
        provenance=_provenance("b" * 40),
        prior_events=[first],
    )

    assert second["comparison"]["persistent_failures"]
    assert second["progress"]["classification"] == "looping"
    assert second["routing"]["decision"] == "handoff_local"


def test_environment_failure_escalates_immediately(plan_path):
    plan = load_plan(plan_path)
    plan.session["environment_dependencies"] = ["windows", "filesystem"]
    event = build_validation_event(
        event_id="run-env",
        timestamp="2026-07-29T00:00:00+00:00",
        plan=plan,
        tests=[NormalizedTest(id="pytest:x", name="x", status="failed")],
        provenance=_provenance("c" * 40),
        prior_events=[],
    )

    assert event["routing"]["decision"] == "handoff_local"
    assert event["routing"]["model"] == "gpt-5.6-sol"
    assert event["routing"]["reasoning"] == "medium"


def test_recommend_local_model_uses_sol_for_security(plan_path):
    plan = load_plan(plan_path)
    plan.session["environment_dependencies"] = ["security"]

    assert recommend_local_model(plan) == ("gpt-5.6-sol", "high")


def test_all_items_verified_produces_ready(plan_path):
    plan = load_plan(plan_path)
    plan.manual_checks[0].status = "passed"
    tests = [
        NormalizedTest(
            id="pytest:tests/engine_test.py::test_preview",
            name="test_preview",
            status="passed",
            item_ids=["AC-001"],
        ),
        NormalizedTest(
            id="pytest:tests/cli_test.py::test_error_case",
            name="test_error_case",
            status="passed",
        ),
    ]

    event = build_validation_event(
        event_id="ready",
        timestamp="2026-07-29T00:00:00+00:00",
        plan=plan,
        tests=tests,
        provenance=_provenance("d" * 40),
        prior_events=[],
    )

    assert event["progress"]["classification"] == "ready"
    assert event["routing"]["decision"] == "ready_for_acceptance"


def test_conflicting_request_stops_before_implementation(plan_path):
    plan = load_plan(plan_path)
    plan.session["request"] = {
        "status": "conflict_pending",
        "summary": "Switch the persistence format.",
        "resolution": "user_decision_required",
        "affected_ids": ["AC-001"],
        "supersedes": [],
        "conflicts": ["The active plan requires JSON while the new request is ambiguous about replacement."],
    }

    event = build_validation_event(
        event_id="conflict",
        timestamp="2026-07-29T00:00:00+00:00",
        plan=plan,
        tests=[],
        provenance=_provenance("e" * 40),
        prior_events=[],
    )

    assert not event["planning_gate"]["passed"]
    assert event["routing"]["decision"] == "stop_for_user_decision"


def test_batch_candidates_favor_foundational_prerequisites(plan_path):
    plan = load_plan(plan_path)
    for item in plan.items:
        item.implementation = "planned"

    candidates = recommend_batch_candidates(plan)

    assert candidates[0]["id"] == "AC-001"
    assert candidates[0]["architecture_role"] == "foundation"


def test_architecture_review_becomes_due_after_configured_run_backstop(plan_path):
    plan = load_plan(plan_path)
    plan.policy["architecture_review"]["max_validation_runs"] = 1
    first = build_validation_event(
        event_id="first",
        timestamp="2026-07-29T00:00:00+00:00",
        plan=plan,
        tests=[],
        provenance=_provenance("f" * 40),
        prior_events=[],
    )
    plan.session["request"]["status"] = "no_new_request"
    plan.session["request"]["resolution"] = "none"

    second = build_validation_event(
        event_id="second",
        timestamp="2026-07-29T01:00:00+00:00",
        plan=plan,
        tests=[],
        provenance=_provenance("1" * 40),
        prior_events=[first],
    )

    assert second["architecture_review"]["due"]
    assert second["routing"]["decision"] == "review_architecture"
