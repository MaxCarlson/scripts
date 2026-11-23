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
