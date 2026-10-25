from datetime import datetime, timedelta, timezone

import pytest

from llm_monitor.events import NormalizedEvent
from llm_monitor.history_analysis import analyze_stored_session, compare_stored_sessions, reconstruct_timeline
from llm_monitor.storage import AmbiguousSessionError, TelemetryStore


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
ENDPOINT = "http://localhost:4096"


def stamp(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def observation(store, session_id, second, state, coverage="complete"):
    return store.ingest_poll(
        "opencode", ENDPOINT, session_id,
        {"polled_at": stamp(second), "normalized_state": state,
         "pending_permissions": 1 if state == "waiting_permission" else 0,
         "pending_questions": 1 if state == "waiting_question" else 0,
         "history_coverage": {"status": coverage, "source": "cursor", "pages": 1, "limit": 100},
         "errors": {}},
        [],
    )


def event(session_id, identity, category, second, *, duration=None, tokens=None, **values):
    return NormalizedEvent(
        event_id=f"{session_id}-{identity}", timestamp=stamp(second), observed_at=stamp(second + 1),
        source="synthetic", category=category, subtype=values.pop("subtype", "completed"),
        session_id=session_id, provider_id=values.pop("provider_id", identity),
        duration_seconds=duration, completed_at=stamp(second + duration) if duration is not None and category == "inference" else None,
        outcome=values.pop("outcome", "completed" if category == "inference" else "succeeded"),
        model=values.pop("model", "model-a"), agent="worker", tokens=tokens, **values,
    )


def seed_session(store, session_id, *, scale=1, coverage="complete", model="model-a"):
    observation(store, session_id, 0, "idle", coverage)
    observation(store, session_id, 1, "inference_running", coverage)
    observation(store, session_id, 5, "idle", coverage)
    observation(store, session_id, 7, "waiting_question", coverage)
    observation(store, session_id, 10, "idle", coverage)
    observation(store, session_id, 15, "idle", coverage)
    store.ingest_model_configuration(
        "opencode", ENDPOINT, session_id, stamp(0),
        {"model_id": model, "context": 4096 * scale, "output": 1024},
        {"id": model, "state": "loaded", "context_length": 4096 * scale},
    )
    target = "sha256:target-a"
    events = [
        event(session_id, "inf-1", "inference", 1, duration=2,
              tokens={"input": 2500, "output": 100, "reasoning": 10, "cache_read": 500}, model=model),
        event(session_id, "read-before", "tool", 3, duration=1, tool_name="read", tool_target=target),
        event(session_id, "compact-part-1", "compaction", 5, duration=2,
              provider_id="compact-cycle-1", part_id="compact-part-1", outcome="completed"),
        event(session_id, "compact-part-2", "compaction", 5, duration=None,
              provider_id="compact-cycle-1", part_id="compact-part-2", outcome="completed"),
        event(session_id, "read-after-1", "tool", 8, duration=0.5, tool_name="read", tool_target=target),
        event(session_id, "read-after-2", "tool", 9, duration=None, tool_name="read", tool_target=target),
        event(session_id, "edit-fail-1", "tool", 11, tool_name="edit", tool_target=target, outcome="failed"),
        event(session_id, "edit-fail-2", "tool", 12, tool_name="edit", tool_target=target, outcome="failed"),
        event(session_id, "inf-2", "inference", 13, duration=1,
              tokens={"input": 1000, "output": 40, "reasoning": 4}, model=model),
    ]
    for item in events:
        store.ingest_poll(
            "opencode", ENDPOINT, session_id,
            {"polled_at": stamp(15), "normalized_state": "idle",
             "history_coverage": {"status": coverage, "source": "cursor", "pages": 1, "limit": 100},
             "errors": {}}, [item],
        )


def test_streaming_session_analysis_preserves_metrics_and_time_semantics(tmp_path):
    with TelemetryStore(tmp_path / "history.sqlite3") as store:
        seed_session(store, "run-a")
        result = analyze_stored_session(store, "run-a", endpoint=ENDPOINT)

    metrics = result["metrics"]
    assert metrics["execution"]["observed_wall_seconds"]["value"] == 15
    assert metrics["execution"]["sampled_state_seconds"]["values"]["idle"] == 8
    assert metrics["execution"]["sampled_state_seconds"]["method"] == "bounded_poll_interval_interpolation"
    assert metrics["inference"]["count"] == 2
    assert metrics["inference"]["duration_seconds"]["median"] == 1.5
    assert metrics["inference"]["duration_seconds"]["p90"] is None
    assert metrics["inference"]["duration_seconds"]["percentile_status"] == "insufficient_sample"
    assert metrics["inference"]["output_tokens_per_second"]["method"] == "approx_message_elapsed"
    assert metrics["tokens"]["observed_completed_totals"]["input"]["value"] == 3500
    assert metrics["context"]["utilization_percent"]["maximum"] == pytest.approx(81.4, abs=0.1)
    assert metrics["compactions"]["unique_cycles"] == 1
    assert metrics["compactions"]["raw_parts"] == 2
    assert metrics["tools"]["read_calls"] == 3
    assert metrics["tools"]["reported_edit_failures"] == 2
    assert metrics["tools"]["repeated_read_targets"] == 1
    assert result["completion"]["task_acceptance"] == "unverified"
    assert any(item["code"] == "reads.repeated_after_compaction" for item in result["findings"])


def test_compare_sessions_reports_deltas_and_fairness_warnings(tmp_path):
    with TelemetryStore(tmp_path / "compare.sqlite3") as store:
        seed_session(store, "run-a", scale=1, coverage="complete")
        seed_session(store, "run-b", scale=2, coverage="partial", model="model-b")
        result = compare_stored_sessions(store, ["run-a", "run-b"], endpoints=[ENDPOINT, ENDPOINT])

    assert len(result["runs"]) == 2
    assert result["differences"]["observed_wall_seconds"][0]["absolute"] == 0
    assert result["differences"]["observed_wall_seconds"][0]["percent"] == 0
    assert result["differences"]["context_capacity"][0]["absolute"] == 4096
    assert result["differences"]["context_capacity"][0]["percent"] == 100
    assert result["comparability"]["task_equivalence"] == "unknown"
    assert any(warning["code"] == "comparison.coverage_differs" for warning in result["warnings"])
    assert any(warning["code"] == "comparison.model_differs" for warning in result["warnings"])


def test_comparison_rejects_duplicate_session_ids_across_endpoints(tmp_path):
    with TelemetryStore(tmp_path / "ambiguous.sqlite3") as store:
        snapshot = {"polled_at": stamp(0), "normalized_state": "idle",
                    "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 10}}
        store.ingest_poll("opencode", "http://one:4096", "same", snapshot, [])
        store.ingest_poll("opencode", "http://two:4096", "same", snapshot, [])
        with pytest.raises(AmbiguousSessionError, match="multiple provider instances"):
            analyze_stored_session(store, "same")


def test_legacy_history_without_state_samples_keeps_idle_time_unknown(tmp_path):
    with TelemetryStore(tmp_path / "legacy.sqlite3") as store:
        store.ingest_poll(
            "opencode", ENDPOINT, "legacy",
            {"polled_at": stamp(15), "normalized_state": "idle",
             "history_coverage": {"status": "complete", "source": "legacy", "pages": 1, "limit": 100}}, [],
        )
        result = analyze_stored_session(store, "legacy", endpoint=ENDPOINT)

    assert result["metrics"]["execution"]["sampled_state_seconds"]["values"] is None
    assert result["metrics"]["execution"]["sampled_state_seconds"]["status"] == "unavailable"


def test_overlapping_activity_intervals_are_unioned_without_double_counting():
    records = [
        {"category": "inference", "payload": event("s", "i", "inference", 0, duration=10).to_dict()},
        {"category": "tool", "payload": event("s", "t", "tool", 5, duration=7, tool_name="shell").to_dict()},
        {"category": "compaction", "payload": event("s", "c", "compaction", 11, duration=2).to_dict()},
        {"category": "tool", "payload": event("s", "unknown", "tool", 15, tool_name="shell").to_dict()},
    ]

    timeline = reconstruct_timeline(records)

    assert timeline["time_by_operation_seconds"]["inference"] == 10
    assert timeline["time_by_operation_seconds"]["tool"] == 7
    assert timeline["time_by_operation_seconds"]["compaction"] == 2
    assert timeline["combined_activity_union_seconds"] == 13
    assert timeline["event_count"] == 4


def test_long_state_sampling_gap_is_unknown_not_idle(tmp_path):
    with TelemetryStore(tmp_path / "sampling-gap.sqlite3") as store:
        observation(store, "gap", 0, "idle")
        observation(store, "gap", 120, "idle")
        result = analyze_stored_session(store, "gap", endpoint=ENDPOINT)

    sampled = result["metrics"]["execution"]["sampled_state_seconds"]
    assert sampled["values"] == {}
    assert sampled["unknown_seconds"] == 120
