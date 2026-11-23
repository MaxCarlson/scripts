from __future__ import annotations

import json
from io import StringIO

import pytest

from agent_continuity.dispatcher import DispatcherService, _mutation_lock
from agent_continuity.dispatcher_cli import build_parser, dispatch
from agent_continuity.errors import ContinuityError
from agent_continuity.service import ContinuityService


def _dispatch(home, *argv):
    parser = build_parser()
    output = StringIO()
    args = parser.parse_args(["-H", str(home), *argv])
    code = dispatch(args, parser, input_stream=StringIO(), output_stream=output)
    return code, output.getvalue()


def test_registry_lock_contention_is_reported_without_stale_claim(tmp_path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    with _mutation_lock(dispatcher.home_dir):
        from agent_continuity.dispatcher_cli import _probe_existing_lock
        assert _probe_existing_lock(dispatcher.home_dir / "dispatcher.lock") == "contended"
    assert _probe_existing_lock(dispatcher.home_dir / "dispatcher.lock") == "available"


def test_doctor_is_read_only_and_json_is_stable(tmp_path):
    home = tmp_path / "not-created"
    code, output = _dispatch(home, "doctor", "-j")
    first = json.loads(output)
    assert code == 0
    assert first["registry"]["database"]["integrity"] == "not_initialized"
    assert "do not prove external provider inactivity" in " ".join(first["limitations"])
    assert not home.exists()


def test_doctor_human_output_reports_registry_runtime_pending_and_limitations(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.register("P", "A")
    dispatcher.begin_launch(gui="P", name="A", provider="codex", apply=True)

    code, output = _dispatch(home, "doctor", "-g", "P", "-n", "A")

    assert code == 0
    assert "Registry integrity:" in output
    assert "Registry lock:" in output
    assert "P / A" in output
    assert "PENDING" in output
    assert "Pending launches:" in output
    assert "Limitations:" in output


def test_runtime_ownership_requires_same_wsl_distribution(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr("agent_continuity.environment.detect_runtime_kind", lambda: "wsl")
    monkeypatch.setattr("agent_continuity.environment.socket.gethostname", lambda: "shared-host")
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.register("P", "A", provider="codex", session_id="native")
    launch = dispatcher.begin_launch(gui="P", name="A", provider="codex", apply=True)
    slot = dispatcher.get_slot(gui="P", name="A")
    dispatcher.record_process_observation(slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
        return_code=0, outcome="bootstrap_id_captured", native_session_id="captured")

    monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
    with pytest.raises(ContinuityError, match="runtime ownership cannot be established"):
        dispatcher.recover_captured_launch(gui="P", name="A", apply=True)

    code, output = _dispatch(home, "doctor", "-g", "P", "-n", "A", "-j")
    assert code == 0
    assert json.loads(output)["agents"][0]["runtime"] == "UNKNOWN"


def test_runtime_ownership_requires_same_host(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_continuity.environment.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.environment.socket.gethostname", lambda: "host-one")
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.register("P", "A")
    launch = dispatcher.begin_launch(gui="P", name="A", provider="codex", apply=True)
    slot = dispatcher.get_slot(gui="P", name="A")
    dispatcher.record_process_observation(slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
        return_code=0, outcome="bootstrap_id_captured", native_session_id="captured")

    monkeypatch.setattr("agent_continuity.environment.socket.gethostname", lambda: "host-two")
    with pytest.raises(ContinuityError, match="runtime ownership cannot be established"):
        dispatcher.recover_captured_launch(gui="P", name="A", apply=True)

    code, output = _dispatch(home, "doctor", "-g", "P", "-n", "A", "-j")
    assert code == 0
    assert json.loads(output)["agents"][0]["runtime"] == "UNKNOWN"


def test_doctor_does_not_create_session_lock_files(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.register("P", "A", provider="codex", session_id="known")
    lock_files = set(home.glob("session-*.lock"))
    _dispatch(home, "doctor", "-g", "P", "-n", "A", "-j")
    assert set(home.glob("session-*.lock")) == lock_files


def test_doctor_reports_runtime_and_pending_launch(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.register("P", "A")
    launch = dispatcher.begin_launch(gui="P", name="A", provider="codex", apply=True)
    code, output = _dispatch(home, "doctor", "-g", "P", "-n", "A", "-j")
    data = json.loads(output)
    assert code == 0
    assert data["agents"][0]["runtime"] == "PENDING"
    assert data["pending_launches"][0]["launch_id"] == launch["details"]["launch_id"]


def test_recover_captured_launch_preview_apply_and_repeat(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.register("P", "A")
    launch = dispatcher.begin_launch(gui="P", name="A", provider="codex", apply=True)
    slot = dispatcher.get_slot(gui="P", name="A")
    dispatcher.record_process_observation(slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
        return_code=0, outcome="bootstrap_id_captured", native_session_id="captured-session")
    preview = dispatcher.recover_captured_launch(gui="P", name="A", apply=False)
    assert preview["status"] == "preview"
    assert dispatcher.get_slot(gui="P", name="A")["current"] is None
    applied = dispatcher.recover_captured_launch(gui="P", name="A", apply=True)
    assert applied["status"] == "recovered"
    view = dispatcher.get_slot(gui="P", name="A")
    assert view["current"]["native_session_id"] == "captured-session"
    assert len(view["history"]) == 1
    again = dispatcher.recover_captured_launch(gui="P", name="A", apply=True)
    assert again["status"] == "already_recovered"
    assert len(dispatcher.get_slot(gui="P", name="A")["history"]) == 1
    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()
    assert dispatcher.get_slot(gui="P", name="A")["current"]["native_session_id"] == "captured-session"


def test_metadata_failure_after_provider_exit_is_actionable(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import pytest

    from agent_continuity.dispatcher_cli import _run_pane
    from agent_continuity.errors import ContinuityError, ErrorCode
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.register("P", "A", provider="codex", session_id="native")
    slot = dispatcher.get_slot(gui="P", name="A")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *args, **kwargs: ["fake-provider"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(dispatcher, "record_process_observation", lambda **kwargs: (_ for _ in ()).throw(
        ContinuityError(ErrorCode.METADATA_INACCESSIBLE, "lock timeout")))
    with pytest.raises(ContinuityError, match="process exited with code 0.*Do not relaunch blindly"):
        _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None, input_stream=StringIO(), output_stream=StringIO())


@pytest.mark.parametrize("command", ["continue", "attach", "switch"])
def test_switch_refuses_running_current_session_without_writing_or_launching(tmp_path, monkeypatch, command):
    import hashlib

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("P", "A", provider="codex", session_id="historical")
    dispatcher.register("P", "A", provider="agy", session_id="current", select=True)
    slot = dispatcher.get_slot(gui="P", name="A")
    current = slot["current"]
    lock_key = hashlib.sha256(
        f"{current['provider']}\0{current['environment_id']}\0{current['native_session_id']}".encode()
    ).hexdigest()[:24]
    lock_name = f"session-{lock_key}.lock"
    before_history = slot["history"]
    before_events = dispatcher._rows("SELECT event_id, event_type FROM activity_events ORDER BY observed_timestamp, event_id")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: launches.append(True) or 0)
    parser = build_parser()
    argv = {
        "continue": ["continue", "-g", "P", "-n", "A", "-p", "codex", "-a"],
        "attach": ["attach", "-g", "P", "-n", "A", "-p", "codex", "-i", "historical", "-a"],
        "switch": ["switch", "-g", "P", "-n", "A", "-p", "codex", "-r", "-a"],
    }[command]

    with _mutation_lock(home, lock_name):
        args = parser.parse_args(["-H", str(home), *argv])
        with pytest.raises(ContinuityError, match="current session.*in use"):
            dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())

    after = dispatcher.get_slot(gui="P", name="A")
    assert after["history"] == before_history
    assert dispatcher._rows("SELECT event_id, event_type FROM activity_events ORDER BY observed_timestamp, event_id") == before_events
    assert launches == []


def test_attach_same_current_session_is_noop_even_when_running(tmp_path):
    import hashlib

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("P", "A", provider="codex", session_id="current")
    slot = dispatcher.get_slot(gui="P", name="A")
    current = slot["current"]
    lock_key = hashlib.sha256(
        f"{current['provider']}\0{current['environment_id']}\0{current['native_session_id']}".encode()
    ).hexdigest()[:24]
    before_events = dispatcher._rows("SELECT event_id, event_type FROM activity_events ORDER BY observed_timestamp, event_id")

    with _mutation_lock(home, f"session-{lock_key}.lock"):
        result = dispatcher.attach_session(gui="P", name="A", provider="codex", session_id="current", apply=True)

    assert result["events"] == []
    assert dispatcher.get_slot(gui="P", name="A")["history"] == slot["history"]
    assert dispatcher._rows("SELECT event_id, event_type FROM activity_events ORDER BY observed_timestamp, event_id") == before_events


def test_process_observation_uses_session_that_child_ran(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from agent_continuity.dispatcher_cli import _run_pane

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("P", "A", provider="codex", session_id="child-session")
    slot = dispatcher.get_slot(gui="P", name="A")

    @contextmanager
    def release_then_switch(*args, **kwargs):
        yield
        dispatcher.attach_session(gui="P", name="A", provider="agy", session_id="new-selection", apply=True)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._session_runtime_lock", release_then_switch)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *args, **kwargs: ["fake-provider"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=1))

    assert _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                     input_stream=StringIO(), output_stream=StringIO()) == 1

    event = dispatcher._row(
        "SELECT provider, native_session_id FROM activity_events "
        "WHERE event_type = 'dispatcher.process_observed' ORDER BY observed_timestamp DESC, event_id DESC LIMIT 1"
    )
    assert event == {"provider": "codex", "native_session_id": "child-session"}
