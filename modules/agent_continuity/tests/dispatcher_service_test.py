from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.models import EventEnvelope, EventType
from agent_continuity.service import ContinuityService


def test_slot_lookup_uses_one_sync_and_honors_locked_freshness_hint(tmp_path, monkeypatch):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    slot = dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    slot_id = slot["details"]["slot_id"]
    sync_calls = 0
    original_sync = dispatcher._sync

    def count_sync():
        nonlocal sync_calls
        sync_calls += 1
        original_sync()

    monkeypatch.setattr(dispatcher, "_sync", count_sync)
    assert dispatcher.get_slot_by_id(slot_id)["slot_id"] == slot_id
    assert sync_calls == 1
    sync_calls = 0
    assert dispatcher.get_slot_by_id(slot_id, state_already_synced=True)["slot_id"] == slot_id
    assert sync_calls == 0


def test_activation_history_preserves_repeated_native_session_and_rebuild(tmp_path):
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)

    dispatcher.create_gui("AgentImprovement", apply=True)
    slot = dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)

    dispatcher.attach_session(
        gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-A", apply=True
    )
    dispatcher.attach_session(
        gui="AgentImprovement", name="AgentPerf", provider="codex", session_id="codex-B", apply=True
    )
    dispatcher.attach_session(
        gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-A", apply=True
    )

    slot_view = dispatcher.get_slot(gui="agentimprovement", name="agentperf")
    assert [entry["native_session_id"] for entry in slot_view["history"]] == ["agy-A", "codex-B", "agy-A"]
    assert slot_view["current"]["native_session_id"] == "agy-A"
    assert slot["details"]["slot_id"] == slot_view["slot_id"]

    continuity.materializer.db_path.unlink()
    continuity.materializer.rebuild_from_spools()
    rebuilt = DispatcherService(continuity).get_slot(gui="AgentImprovement", name="AgentPerf")
    assert rebuilt["current"] == slot_view["current"]
    assert rebuilt["history"] == slot_view["history"]


def test_verified_user_prompt_switches_to_previously_bound_session(tmp_path):
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(
        gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-A", apply=True
    )
    dispatcher.attach_session(
        gui="AgentImprovement", name="AgentPerf", provider="codex", session_id="codex-B", apply=True
    )
    env_id = dispatcher.list_slots(gui="AgentImprovement")[0]["current_environment_id"]
    later = (datetime.now(UTC) + timedelta(seconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    continuity._emit_and_materialize([
        EventEnvelope(
            event_id="evt_verified_prompt_a",
            event_schema_version=1,
            event_type=EventType.HOOK_EVENT.value,
            provider="agy",
            environment_id=env_id,
            native_session_id="agy-A",
            source_timestamp=later,
            observed_timestamp=later,
            source_adapter_version="test",
            payload={"normalized_event_type": "turn.submitted"},
        )
    ])

    slot = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")
    assert [entry["native_session_id"] for entry in slot["history"]] == ["agy-A", "codex-B", "agy-A"]
    assert slot["history"][-1]["provenance"] == "verified_user_prompt"


def test_slot_lifecycle_hides_inactive_from_active_list_and_retains_history(tmp_path):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentBench", apply=True)
    dispatcher.attach_session(
        gui="AgentImprovement", name="AgentBench", provider="codex", session_id="bench-1", apply=True
    )

    dispatcher.set_slot_state(gui="AgentImprovement", name="AgentBench", state="completed", apply=True)

    assert [slot["name"] for slot in dispatcher.list_slots(gui="AgentImprovement")] == ["AgentPerf"]
    history = dispatcher.get_slot(gui="AgentImprovement", name="AgentBench")
    assert history["state"] == "completed"
    assert [item["native_session_id"] for item in history["history"]] == ["bench-1"]


def test_active_agent_query_returns_one_current_session_per_named_slot(tmp_path):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentBench", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-1", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentBench", provider="codex", session_id="codex-1", apply=True)

    slots = dispatcher.list_slots(gui="AgentImprovement")
    assert {(row["name"], row["current_provider"], row["current_session_id"]) for row in slots} == {
        ("AgentPerf", "agy", "agy-1"),
        ("AgentBench", "codex", "codex-1"),
    }


def test_unresolved_slot_remains_pending_without_changing_last_session(tmp_path):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-1", apply=True)
    launch = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="codex", apply=True)

    slot = dispatcher.list_slots(gui="AgentImprovement")[0]
    request = dispatcher.open_request(gui="AgentImprovement")
    assert slot["current_session_id"] == "agy-1"
    assert slot["pending_provider"] == "codex"
    assert slot["pending_launch_id"] == launch["details"]["launch_id"]
    assert request["panes"] == []
    assert request["unresolved"] == [
        {
            "slot_id": slot["slot_id"],
            "agent_name": "AgentPerf",
            "reason": "pending codex destination must be recovered before opening this slot",
        }
    ]


def test_pending_launch_failure_and_explicit_resolution_preserve_current_until_attached(tmp_path):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-A", apply=True)

    failed = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="codex", apply=True)
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["current"]["native_session_id"] == "agy-A"
    dispatcher.mark_launch_failed(launch_id=failed["details"]["launch_id"], detail="simulated spawn error")
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["current"]["native_session_id"] == "agy-A"

    pending = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="codex", apply=True)
    dispatcher.attach_session(
        gui="AgentImprovement", name="AgentPerf", provider="codex", session_id="codex-B",
        launch_id=pending["details"]["launch_id"], apply=True,
    )
    current = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")
    assert current["current"]["native_session_id"] == "codex-B"
    launches = dispatcher._rows("SELECT status, resolved_session_id FROM dispatcher_pending_launches ORDER BY requested_at")
    assert [row["status"] for row in launches] == ["failed", "resolved"]
    assert launches[-1]["resolved_session_id"] == "codex-B"


def test_gui_aliases_are_case_insensitive_and_sorted_without_unknown_dates(tmp_path):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("AgentArchitecture", apply=True)
    dispatcher.create_gui("AgentImprovement", apply=True)

    conversations = dispatcher.list_guis()
    assert {item["alias"].casefold() for item in conversations} == {"agentarchitecture", "agentimprovement"}
    assert all(item["last_activity_at"] is None for item in conversations)

    duplicate = dispatcher.create_gui("agentimprovement", apply=False)
    assert duplicate["applied"] is False
    assert duplicate["details"]["existing_alias"] == "AgentImprovement"


def test_renaming_gui_alias_keeps_stable_identity_slot_and_activation_history(tmp_path):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    created = dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="agy-1", apply=True)

    result = dispatcher.rename_gui(gui="AgentImprovement", alias="AgentPerformance", apply=True)
    renamed = dispatcher.get_slot(gui="agentperformance", name="AgentPerf")

    assert result["details"]["gui_id"] == created["details"]["gui_id"]
    assert renamed["gui_alias"] == "AgentPerformance"
    assert renamed["history"][0]["native_session_id"] == "agy-1"
