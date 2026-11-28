from __future__ import annotations

import json
import sqlite3
import tomllib
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from agent_continuity.cli import main as agents_main
from agent_continuity.deployment_compatibility import (
    count_active_llmd_writers,
    evaluate_deployment_preflight,
    installation_resolution,
)
from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import build_parser, dispatch
from agent_continuity.providers.claude import ClaudeAdapter
from agent_continuity.runtime_discovery import (
    EvidenceAvailability,
    MatchStatus,
    ProcessLiveness,
    SessionIdentityState,
)


def _install_complete_stopped_observation(monkeypatch):
    observation = SimpleNamespace(
        process_availability=EvidenceAvailability.COMPLETE,
        process_session_match=MatchStatus.NOT_OBSERVED,
        process_liveness=ProcessLiveness.EXITED,
        session_identity_state=SessionIdentityState.UNKNOWN,
        identity_conflict=False,
        evidence_conflict=False,
    )
    monkeypatch.setattr(DispatcherService, "observe_runtime_session", lambda *args: observation)


def _install_guarded_claude_executable(monkeypatch):
    """Make command previews deterministic without invoking a provider."""
    monkeypatch.setattr(ClaudeAdapter, "find_executable", lambda _self: "C:/guarded/claude.exe")


def _pending_claude(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", cwd=str(tmp_path), apply=True)
    session_id = str(uuid.uuid4())
    dispatcher.record_process_observation(
        slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
        return_code=0, outcome="claude_session_id_reserved", native_session_id=session_id,
        detail="Reserved exact Claude UUID; provider creation was interrupted.",
    )
    monkeypatch.setattr(
        ClaudeAdapter, "get_session_metadata",
        lambda _self, candidate: {"native_session_id": candidate, "cwd": str(tmp_path)} if candidate == session_id else None,
    )
    return home, dispatcher, session_id


def test_continue_preview_recovers_exact_pending_association_without_mutation(tmp_path, monkeypatch):
    _install_complete_stopped_observation(monkeypatch)
    _install_guarded_claude_executable(monkeypatch)
    home, dispatcher, session_id = _pending_claude(tmp_path, monkeypatch)
    before = dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid")
    parser = build_parser()
    output = StringIO()

    code = dispatch(
        parser.parse_args(["-H", str(home), "continue", "-g", "GUI", "-n", "Agent", "-d", "-j"]),
        parser, input_stream=StringIO(), output_stream=output,
    )

    payload = json.loads(output.getvalue())
    assert code == 0
    assert payload["applied"] is False
    assert payload["recovery"]["session_id"] == session_id
    assert "recovery" in payload["summary"].casefold()
    assert dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid") == before
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"] is None


def test_continue_apply_recovers_exact_pending_association_then_resumes_it(tmp_path, monkeypatch):
    _install_complete_stopped_observation(monkeypatch)
    _install_guarded_claude_executable(monkeypatch)
    home, dispatcher, session_id = _pending_claude(tmp_path, monkeypatch)
    dispatcher.set_workflow_type(gui="GUI", agent="Agent", workflow_type="handoff")
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    pending_launch = dispatcher.list_pending_launches()[0]
    dispatcher.record_terminal_launch({
        "launch_id": "terminal-launch-interrupted",
        "terminal_session_id": str(uuid.uuid4()),
        "gui_id": slot["gui_id"], "gui_alias": "GUI", "slot_id": slot["slot_id"],
        "slot_name": "Agent", "provider": "claude", "native_session_id": session_id,
        "environment_id": pending_launch["environment_id"], "launch_started_at": "2026-11-28T00:00:00Z",
        "launch_exited_at": None, "status": "launching", "exit_code": None,
        "requested_cwd": str(tmp_path), "effective_cwd": str(tmp_path), "native_cwd": str(tmp_path),
        "settings": {},
    })
    handoff = {}
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._run_pane",
        lambda _dispatcher, **kwargs: handoff.update(kwargs) or 0,
    )
    parser = build_parser()

    code = dispatch(
        parser.parse_args(["-H", str(home), "continue", "-g", "GUI", "-n", "Agent", "-a"]),
        parser, input_stream=StringIO(), output_stream=StringIO(),
    )

    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    assert code == 0
    assert slot["current"]["native_session_id"] == session_id
    session = dispatcher.materializer.get_session("claude", slot["current"]["environment_id"], session_id)
    assert session.cwd_native == str(tmp_path)
    assert slot["workflow_type"] == "handoff"
    assert handoff["expected_session_identity"] == ("claude", slot["current"]["environment_id"], session_id)
    pending = dispatcher._row("SELECT status FROM dispatcher_pending_launches")
    assert pending["status"] == "resolved"
    terminal = dispatcher._row("SELECT launch_exited_at, status FROM dispatcher_terminal_launches")
    assert terminal["launch_exited_at"] is not None
    assert terminal["status"] == "interrupted"


def test_continue_refuses_live_or_unavailable_provider_observation_before_recovery(tmp_path, monkeypatch):
    for availability, liveness in (
        (EvidenceAvailability.COMPLETE, ProcessLiveness.RUNNING),
        (EvidenceAvailability.UNAVAILABLE, ProcessLiveness.UNKNOWN),
    ):
        observation = SimpleNamespace(
            process_availability=availability,
            process_session_match=MatchStatus.EXACT if liveness is ProcessLiveness.RUNNING else MatchStatus.UNKNOWN,
            process_liveness=liveness,
            session_identity_state=SessionIdentityState.RESERVED,
            identity_conflict=False,
            evidence_conflict=False,
        )
        monkeypatch.setattr(DispatcherService, "observe_runtime_session", lambda *args, obs=observation: obs)
        _install_guarded_claude_executable(monkeypatch)
        home, dispatcher, _session_id = _pending_claude(tmp_path / str(liveness.value), monkeypatch)
        parser = build_parser()

        with pytest.raises(Exception, match="running|process evidence|enumeration"):
            dispatch(
                parser.parse_args(["-H", str(home), "continue", "-g", "GUI", "-n", "Agent", "-a"]),
                parser, input_stream=StringIO(), output_stream=StringIO(),
            )
        assert dispatcher.get_slot(gui="GUI", name="Agent")["current"] is None
        assert dispatcher._row("SELECT status FROM dispatcher_pending_launches")["status"] == "pending"


def test_continue_does_not_recover_pending_launch_when_a_session_is_already_selected(tmp_path, monkeypatch):
    _install_guarded_claude_executable(monkeypatch)
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    selected_session = str(uuid.uuid4())
    dispatcher.register("GUI", "Agent", provider="claude", session_id=selected_session)
    current = dispatcher.get_slot(gui="GUI", name="Agent")["current"]
    expected_current = (current["provider"], current["environment_id"], current["native_session_id"])
    launch = dispatcher.prepare_start(
        gui="GUI", name="Agent", provider="claude", expected_current=expected_current, apply=True,
    )
    reserved = str(uuid.uuid4())
    dispatcher.record_process_observation(
        slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
        return_code=0, outcome="claude_session_id_reserved", native_session_id=reserved,
    )
    parser = build_parser()

    with pytest.raises(Exception, match="unresolved pending launch"):
        dispatch(
            parser.parse_args(["-H", str(home), "continue", "-g", "GUI", "-n", "Agent", "-a"]),
            parser, input_stream=StringIO(), output_stream=StringIO(),
        )

    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    assert slot["current"]["native_session_id"] == selected_session
    assert dispatcher._row("SELECT status FROM dispatcher_pending_launches")["status"] == "pending"


def test_continue_reconciles_only_exact_stopped_open_terminal_record(tmp_path, monkeypatch):
    _install_complete_stopped_observation(monkeypatch)
    _install_guarded_claude_executable(monkeypatch)
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    session_id = str(uuid.uuid4())
    dispatcher.register("GUI", "Agent", provider="claude", session_id=session_id)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    dispatcher.record_terminal_launch({
        "launch_id": "terminal-launch-stale", "terminal_session_id": str(uuid.uuid4()),
        "gui_id": slot["gui_id"], "gui_alias": "GUI", "slot_id": slot["slot_id"],
        "slot_name": "Agent", "provider": "claude", "native_session_id": session_id,
        "environment_id": slot["current"]["environment_id"], "launch_started_at": "2026-11-28T00:00:00Z",
        "launch_exited_at": None, "status": "launching", "exit_code": None,
        "requested_cwd": None, "effective_cwd": None, "native_cwd": None, "settings": {},
    })
    handoffs = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda _dispatcher, **kwargs: handoffs.append(kwargs["expected_session_identity"]) or 0)
    parser = build_parser()

    result = dispatch(
        parser.parse_args(["-H", str(home), "continue", "-g", "GUI", "-n", "Agent", "-a"]),
        parser, input_stream=StringIO(), output_stream=StringIO(),
    )

    terminal = dispatcher._row("SELECT launch_exited_at, status FROM dispatcher_terminal_launches")
    assert result == 0
    assert terminal["launch_exited_at"] is not None
    assert terminal["status"] == "interrupted"
    assert len(handoffs) == 1 and handoffs[0][2] == session_id


def test_continue_rechecks_pending_reservation_before_apply(tmp_path, monkeypatch):
    _install_complete_stopped_observation(monkeypatch)
    _install_guarded_claude_executable(monkeypatch)
    home, dispatcher, _session_id = _pending_claude(tmp_path, monkeypatch)
    original = DispatcherService.recover_captured_launch

    def change_reservation(self, *, gui, name, apply=False, require_stopped=False):
        if apply:
            slot = dispatcher.get_slot(gui="GUI", name="Agent")
            pending = dispatcher.list_pending_launches()[0]
            dispatcher.record_process_observation(
                slot_id=slot["slot_id"], launch_id=pending["launch_id"], return_code=0,
                outcome="claude_session_id_reserved", native_session_id=str(uuid.uuid4()),
            )
        return original(self, gui=gui, name=name, apply=apply, require_stopped=require_stopped)

    monkeypatch.setattr(DispatcherService, "recover_captured_launch", change_reservation)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda *_a, **_k: pytest.fail("stale reservation must not reach provider handoff"))
    parser = build_parser()

    with pytest.raises(Exception, match="reservation|identity|conflict"):
        dispatch(
            parser.parse_args(["-H", str(home), "continue", "-g", "GUI", "-n", "Agent", "-a"]),
            parser, input_stream=StringIO(), output_stream=StringIO(),
        )
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"] is None
    assert dispatcher._row("SELECT status FROM dispatcher_pending_launches")["status"] == "pending"


def test_concurrent_continue_recovers_once_and_refuses_second_running_resume(tmp_path, monkeypatch):
    _install_complete_stopped_observation(monkeypatch)
    _install_guarded_claude_executable(monkeypatch)
    home, dispatcher, _session_id = _pending_claude(tmp_path, monkeypatch)
    first_entered = Event()
    release_first = Event()
    handoffs = []

    def guarded_handoff(instance, *, slot_id, expected_session_identity, **_kwargs):
        handoffs.append(expected_session_identity)
        with instance._hold_slot_lock(slot_id), instance._hold_session_lock(*expected_session_identity):
            first_entered.set()
            assert release_first.wait(timeout=5)
        return 0

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", guarded_handoff)
    parser = build_parser()
    argv = ["-H", str(home), "continue", "-g", "GUI", "-n", "Agent", "-a"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(dispatch, parser.parse_args(argv), parser,
                            input_stream=StringIO(), output_stream=StringIO())
        assert first_entered.wait(timeout=5)
        second = pool.submit(dispatch, parser.parse_args(argv), parser,
                             input_stream=StringIO(), output_stream=StringIO())
        with pytest.raises(Exception, match="already in use"):
            second.result(timeout=5)
        release_first.set()
        assert first.result(timeout=5) == 0

    assert len(handoffs) == 1
    assert dispatcher._row("SELECT status FROM dispatcher_pending_launches")["status"] == "resolved"


def test_deployment_preflight_distinguishes_package_update_from_schema_transition():
    package_only = evaluate_deployment_preflight(
        current_schema=4, target_schema=4, pending_launches=0, open_terminal_launches=0,
        process_enumeration="complete",
    )
    assert package_only["ready"] is True
    assert package_only["kind"] == "package_only"

    blocked = evaluate_deployment_preflight(
        current_schema=3, target_schema=4, pending_launches=1, open_terminal_launches=0,
        process_enumeration="complete",
    )
    assert blocked["ready"] is False
    assert "pending" in " ".join(blocked["blockers"]).casefold()

    open_launch = evaluate_deployment_preflight(
        current_schema=3, target_schema=4, pending_launches=0, open_terminal_launches=2,
        process_enumeration="complete", active_writers=0,
    )
    assert open_launch["ready"] is True
    assert "terminal launch" in " ".join(open_launch["warnings"]).casefold()

    unknown = evaluate_deployment_preflight(
        current_schema=3, target_schema=4, pending_launches=0, open_terminal_launches=0,
        process_enumeration="unavailable",
    )
    assert unknown["ready"] is False
    assert unknown["kind"] == "schema_transition"

    downgrade = evaluate_deployment_preflight(
        current_schema=4, target_schema=3, pending_launches=0, open_terminal_launches=0,
        process_enumeration="complete",
    )
    assert downgrade["ready"] is False
    assert downgrade["kind"] == "unsupported_downgrade"

    active_writer = evaluate_deployment_preflight(
        current_schema=3, target_schema=4, pending_launches=0, open_terminal_launches=0,
        process_enumeration="complete", active_writers=1,
    )
    assert active_writer["ready"] is False
    assert "active llmd writer" in " ".join(active_writer["blockers"]).casefold()


def test_installation_resolution_reports_conflicting_and_stale_path_candidates(tmp_path):
    current = tmp_path / "venv" / "Scripts" / "llmd.exe"
    stale = tmp_path / ".codex" / "worktrees" / "old-install" / "Scripts" / "llmd.exe"
    report = installation_resolution(
        executable=str(current), module_path=str(tmp_path / "venv" / "Lib" / "agent_continuity" / "__init__.py"),
        path_candidates={"llmd": [str(current), str(stale)], "agents": []},
    )
    assert report["status"] == "conflict"
    assert report["path_candidate_count"]["llmd"] == 2
    assert report["stale_candidates"] == [str(stale)]


def test_active_writer_count_requires_complete_inventory_and_ignores_current_process():
    inventory = SimpleNamespace(
        availability=EvidenceAvailability.COMPLETE,
        records=(
            SimpleNamespace(identity=SimpleNamespace(pid=10), image_name="llmd.exe", argv=("llmd.exe",)),
            SimpleNamespace(identity=SimpleNamespace(pid=20), image_name="python.exe",
                             argv=("python.exe", "-m", "agent_continuity.dispatcher_cli")),
        ),
    )
    assert count_active_llmd_writers(inventory, current_pid=10) == 1
    inventory.availability = EvidenceAvailability.PARTIAL
    assert count_active_llmd_writers(inventory, current_pid=10) is None


def test_agents_doctor_reports_read_only_install_and_schema_upgrade_preflight(tmp_path, capsys):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    before = dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid")

    result = agents_main([
        "-H", str(home), "doctor", "-P", "2.5.2", "-S", "5", "-j",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["installation"]["package_version"]
    assert payload["deployment_preflight"]["target_package_version"] == "2.5.2"
    assert payload["deployment_preflight"]["ready"] is False
    assert payload["deployment_preflight"]["kind"] == "schema_transition"
    assert "pending" in " ".join(payload["deployment_preflight"]["blockers"]).casefold()
    assert dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid") == before


def test_agents_doctor_package_only_upgrade_does_not_claim_a_schema_transition(tmp_path, capsys):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    before = dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid")

    result = agents_main(["-H", str(home), "doctor", "-P", "2.5.2", "-S", "4", "-j"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["deployment_preflight"]["kind"] == "package_only"
    assert payload["deployment_preflight"]["ready"] is True
    assert dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid") == before


def _downgrade_disposable_schema_for_test(dispatcher):
    connection = sqlite3.connect(dispatcher.materializer.db_path)
    connection.execute("UPDATE schema_metadata SET value = '3' WHERE key = 'schema_version'")
    connection.commit()
    connection.close()


def test_registry_schema_migration_refuses_pending_launches(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    _downgrade_disposable_schema_for_test(dispatcher)
    inventory = SimpleNamespace(availability=EvidenceAvailability.COMPLETE, records=())
    monkeypatch.setattr(
        "agent_continuity.runtime_discovery.PsutilProcessEnumerator.enumerate_processes",
        lambda _self: inventory,
    )

    with pytest.raises(Exception, match="registry_upgrade_blocked"):
        dispatcher.materializer._connect_rw()
    with pytest.raises(Exception, match="registry_upgrade_blocked"):
        dispatcher.materializer.rebuild_from_spools()

    connection = sqlite3.connect(dispatcher.materializer.db_path)
    assert connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0] == "3"
    connection.close()


def test_registry_schema_migration_refuses_unknown_process_enumeration(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    _downgrade_disposable_schema_for_test(dispatcher)
    inventory = SimpleNamespace(availability=EvidenceAvailability.UNAVAILABLE, records=())
    monkeypatch.setattr(
        "agent_continuity.runtime_discovery.PsutilProcessEnumerator.enumerate_processes",
        lambda _self: inventory,
    )

    with pytest.raises(Exception, match="registry_upgrade_blocked"):
        dispatcher.materializer._connect_rw()

    connection = sqlite3.connect(dispatcher.materializer.db_path)
    assert connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0] == "3"
    connection.close()


def test_registry_schema_migration_refuses_active_old_writer_process(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    _downgrade_disposable_schema_for_test(dispatcher)
    inventory = SimpleNamespace(
        availability=EvidenceAvailability.COMPLETE,
        records=(SimpleNamespace(identity=SimpleNamespace(pid=99999), image_name="llmd.exe", argv=("llmd.exe",)),),
    )
    monkeypatch.setattr(
        "agent_continuity.runtime_discovery.PsutilProcessEnumerator.enumerate_processes",
        lambda _self: inventory,
    )

    with pytest.raises(Exception, match="active LLMD writer"):
        dispatcher.materializer._connect_rw()

    connection = sqlite3.connect(dispatcher.materializer.db_path)
    assert connection.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()[0] == "3"
    connection.close()


def test_release_version_metadata_is_consistent():
    from agent_continuity import __version__

    module_root = Path(__file__).parents[1]
    package = tomllib.loads((module_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["project"]["version"] == __version__ == "2.5.2"
