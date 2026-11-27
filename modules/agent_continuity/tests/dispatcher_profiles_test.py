from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.environment import load_or_create_environment
from agent_continuity.errors import ContinuityError
from agent_continuity.identifiers import generate_id
from agent_continuity.models import EventType


def test_profile_assignment_survives_event_projection_rebuild(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("GUI", "Agent")
    profile = dispatcher.create_profile(
        name="safe", provider="codex", runtime_kind="windows", cwd=str(tmp_path),
        settings={"sandbox": "workspace-write", "model": "gpt-test"},
    )

    dispatcher.assign_profile(gui="GUI", agent="Agent", profile="safe")
    before = dispatcher.get_slot(gui="GUI", name="Agent")
    assert before["profile_id"] == profile["details"]["profile_id"]
    assert dispatcher.get_profile("safe")["settings"] == {
        "model": "gpt-test", "sandbox": "workspace-write"
    }

    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()

    after = dispatcher.get_slot(gui="GUI", name="Agent")
    assert after["profile_id"] == profile["details"]["profile_id"]
    assert dispatcher.get_profile("SAFE")["provider"] == "codex"
    assert dispatcher.get_profile("safe")["revision"] == 1


def test_profile_rejects_unknown_raw_or_authorization_settings(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")

    for settings in (
        {"api_key": "do-not-store"},
        {"raw_config": "model = secret"},
        {"allow_native_unknown": True},
        {"permission_bypass": True},
    ):
        with pytest.raises(ContinuityError, match="profile setting"):
            dispatcher.create_profile(name="unsafe", provider="codex", settings=settings)



def test_agent_numbers_are_monotonic_per_gui_and_survive_projection_rebuild(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI-A", "One")
    dispatcher.register("GUI-A", "Two")
    dispatcher.register("GUI-B", "Other")

    assert dispatcher.get_slot(gui="GUI-A", name="One")["agent_number"] == 1
    assert dispatcher.get_slot(gui="GUI-A", name="Two")["agent_number"] == 2
    assert dispatcher.get_slot(gui="GUI-B", name="Other")["agent_number"] == 1

    dispatcher.set_slot_state(gui="GUI-A", name="One", state="inactive", apply=True)
    dispatcher.register("GUI-A", "Three")
    assert dispatcher.get_slot(gui="GUI-A", name="Three")["agent_number"] == 3

    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()
    assert dispatcher.get_slot(gui="GUI-A", name="One")["agent_number"] == 1
    assert dispatcher.get_slot(gui="GUI-A", name="Two")["agent_number"] == 2
    assert dispatcher.get_slot(gui="GUI-A", name="Three")["agent_number"] == 3


def test_slot_creation_dry_run_does_not_consume_agent_number(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)

    preview = dispatcher.create_slot(gui="GUI", name="Preview", apply=False)
    assert preview["details"]["agent_number"] == 1
    assert dispatcher.register("GUI", "Actual")["details"]["agent_number"] == 1


def test_workflow_type_is_nullable_until_explicitly_changed_and_rebuilds(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Legacy")
    assert dispatcher.get_slot(gui="GUI", name="Legacy")["workflow_type"] is None

    result = dispatcher.set_workflow_type(gui="GUI", agent="Legacy", workflow_type="handoff")
    assert result["applied"] is True
    assert dispatcher.get_slot(gui="GUI", name="Legacy")["workflow_type"] == "handoff"

    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()
    assert dispatcher.get_slot(gui="GUI", name="Legacy")["workflow_type"] == "handoff"


def test_workflow_type_rejects_invalid_and_requires_explicit_clear(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Agent")
    with pytest.raises(ContinuityError, match="workflow type"):
        dispatcher.set_workflow_type(gui="GUI", agent="Agent", workflow_type="unknown")
    assert dispatcher.get_slot(gui="GUI", name="Agent")["workflow_type"] is None
    dispatcher.set_workflow_type(gui="GUI", agent="Agent", workflow_type="goal")
    dispatcher.set_workflow_type(gui="GUI", agent="Agent", workflow_type=None)
    assert dispatcher.get_slot(gui="GUI", name="Agent")["workflow_type"] is None


def test_profile_revision_update_clear_and_retirement(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_profile(name="safe", provider="codex", settings={"sandbox": "workspace-write", "model": "gpt-test"})
    result = dispatcher.update_profile("safe", settings={"model": "gpt-next"}, clear_settings=["sandbox"])
    assert result["details"]["revision"] == 2
    assert dispatcher.get_profile("safe")["settings"] == {"model": "gpt-next"}
    dispatcher.retire_profile("safe")
    assert dispatcher.list_profiles() == []
    assert dispatcher.get_profile("safe")["status"] == "retired"


def test_profiles_cannot_persist_unattended_authorization(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    for provider, settings in (("codex", {"approval_policy": "never"}),
                               ("claude", {"permission_mode": "dontAsk"}),
                               ("codex", {"auto_approval": True})):
        with pytest.raises(ContinuityError, match="profile|authorization|Unsupported"):
            dispatcher.create_profile(name="unsafe", provider=provider, settings=settings)
def test_verified_legacy_agent_number_import_precedes_fallback_and_rebuilds(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    conversation = dispatcher._row("SELECT gui_id FROM dispatcher_gui_conversations WHERE alias_key = 'gui'")
    env = load_or_create_environment(dispatcher.home_dir, persist=True)
    slot_id = generate_id("slot")
    event = dispatcher._event(EventType.DISPATCHER_SLOT_CREATED, environment_id=env.environment_id,
                              payload={"slot_id": slot_id, "gui_id": conversation["gui_id"],
                                       "name": "Legacy", "name_key": "legacy"})
    dispatcher.continuity._emit_and_materialize([event])

    before = dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid")
    preview = dispatcher.reconcile_agent_number(gui="GUI", agent="Legacy", agent_number=42,
                                                source="verified handoff manifest", apply=False)
    assert preview["applied"] is False
    assert dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid") == before
    assert dispatcher._row("SELECT agent_number FROM agent_slots WHERE slot_id = ?", (slot_id,))["agent_number"] is None

    dispatcher.reconcile_agent_number(gui="GUI", agent="Legacy", agent_number=42,
                                      source="verified handoff manifest", apply=True)
    dispatcher.register("GUI", "Next")
    assert dispatcher.get_slot(gui="GUI", name="Legacy")["agent_number"] == 42
    assert dispatcher.get_slot(gui="GUI", name="Next")["agent_number"] == 43

    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()
    assert dispatcher.get_slot(gui="GUI", name="Legacy")["agent_number"] == 42
    assert dispatcher.get_slot(gui="GUI", name="Next")["agent_number"] == 43


def test_concurrent_slot_creation_reserves_unique_numbers(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)

    def create(index):
        return dispatcher.create_slot(gui="GUI", name=f"Agent {index}", apply=True)["details"]["agent_number"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        numbers = list(pool.map(create, range(6)))
    assert sorted(numbers) == list(range(1, 7))
    assert len({row["agent_number"] for row in dispatcher.list_slots(gui="GUI", active_only=False)}) == 6


def test_registration_and_status_expose_profile_checkpoint_metadata(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    registration = dispatcher.register("GUI", "Agent")
    assert registration["details"]["agent_number"] == 1
    dispatcher.create_profile(name="safe", provider="codex", settings={"sandbox": "workspace-write"})
    dispatcher.assign_profile(gui="GUI", agent="Agent", profile="safe")
    dispatcher.set_workflow_type(gui="GUI", agent="Agent", workflow_type="goal")

    slot = dispatcher.list_slots(gui="GUI", active_only=False)[0]
    assert slot["gui_id"] == dispatcher._row("SELECT gui_id FROM dispatcher_gui_conversations WHERE alias_key = 'gui'")["gui_id"]
    assert slot["agent_number"] == 1
    assert slot["workflow_type"] == "goal"
    assert slot["profile_name"] == "safe"
    assert slot["profile_revision"] == 1
    assert slot["profile_settings_digest"].startswith("sha256:")
    assert "_profile_settings_json" not in slot
