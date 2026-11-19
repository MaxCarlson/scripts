from __future__ import annotations

import subprocess
import ctypes
from pathlib import Path

import pytest

from runtime_lifecycle import (
    ElevationRequiredError,
    LogonTrigger,
    NamedMutex,
    OwnershipConflictError,
    PreviewResult,
    TaskPrincipal,
    TaskSpec,
    decode_hresult,
    parse_task_xml,
    render_task_xml,
)
from runtime_lifecycle import helpers, windows


def make_spec(tmp_path: Path, **changes: object) -> TaskSpec:
    executable = tmp_path / "pythonw.exe"
    executable.write_bytes(b"placeholder")
    working = tmp_path / "runtime"
    working.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "owner": "snips",
        "name": "runtime",
        "executable": executable,
        "args": ("-m", "snips.cli", "ensure-runtime", "--apply"),
        "working_dir": working,
        "triggers": (LogonTrigger(),),
        "principal": TaskPrincipal(sid="S-1-5-21-1-2-3-1001"),
    }
    values.update(changes)
    return TaskSpec(**values)  # type: ignore[arg-type]


def test_hresult_decoder_normalizes_signed_codes() -> None:
    assert decode_hresult(0) == "0x00000000: The operation completed successfully"
    assert decode_hresult(0x41301).startswith("0x00041301:")
    signed = 0x8004130F - 0x100000000
    assert decode_hresult(signed).startswith("0x8004130F:")
    assert decode_hresult(None) is None


def test_preview_for_missing_task_is_create(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: None)
    result = windows.preview(task)
    assert result.action == "create"
    assert result.task_path == r"\Scripts\snips-runtime"
    assert "UTF-16" in result.xml


def test_preview_matching_owned_spec_is_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    parsed = parse_task_xml(render_task_xml(task))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: (b"xml", parsed, None))
    assert windows.preview(task).action == "noop"


def test_apply_is_idempotent_when_preview_is_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_require_elevation", lambda _spec: None)
    monkeypatch.setattr(windows, "preview", lambda _spec: PreviewResult("noop", task.task_path, "<Task/>"))
    monkeypatch.setattr(windows, "status", lambda *args, **kwargs: object())
    monkeypatch.setattr(windows, "_register_xml", lambda *args: pytest.fail("noop must not re-register"))
    result = windows.apply(task)
    assert result.action == "unchanged"


def test_apply_conflict_requires_force_and_force_updates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_require_elevation", lambda _spec: None)
    monkeypatch.setattr(
        windows, "preview", lambda _spec: PreviewResult("conflict", task.task_path, "<Task/>", reason="foreign task")
    )
    with pytest.raises(OwnershipConflictError, match="foreign task"):
        windows.apply(task)
    calls: list[str] = []
    monkeypatch.setattr(windows, "_create_folder", lambda _folder: calls.append("folder"))
    monkeypatch.setattr(windows, "_register_xml", lambda *_args: calls.append("register"))
    monkeypatch.setattr(
        windows,
        "status",
        lambda *args, **kwargs: windows.TaskStatus(task.task_path, "registered"),
    )
    result = windows.apply(task, force=True)
    assert result.action == "updated"
    assert calls == ["folder", "register"]


def test_apply_requires_elevation_for_highest_principal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path, principal=TaskPrincipal(sid="S-1-5-21-1-2-3-1001", run_level="highest"))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "is_elevated", lambda: False)
    with pytest.raises(ElevationRequiredError, match="Administrator"):
        windows.apply(task)


def test_remove_refuses_foreign_task_before_delete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    foreign = parse_task_xml(render_task_xml(make_spec(tmp_path, owner="other")))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: (b"xml", foreign, None))
    monkeypatch.setattr(windows, "current_user_sid", lambda: task.principal_sid)
    monkeypatch.setattr(windows, "_run_schtasks", lambda _args: pytest.fail("foreign task must not be deleted"))
    with pytest.raises(OwnershipConflictError):
        windows.remove(task.owner, task.name, principal_sid=task.principal_sid)


def test_remove_deletes_owned_task_and_is_idempotent_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task = make_spec(tmp_path)
    parsed = parse_task_xml(render_task_xml(task))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: (b"xml", parsed, None))
    monkeypatch.setattr(windows, "_require_task_mutation_elevation", lambda _path: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        windows,
        "_run_schtasks",
        lambda args: calls.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )
    assert windows.remove(task.owner, task.name, principal_sid=task.principal_sid) is True
    assert calls == [["/Delete", "/TN", task.task_path, "/F"]]
    monkeypatch.setattr(windows, "_inspect", lambda _path: None)
    assert windows.remove(task.owner, task.name, principal_sid=task.principal_sid) is False


def test_restore_rejects_corrupted_snapshot_hash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    xml = render_task_xml(task)
    snapshot = windows.TaskSnapshot(
        task.task_path,
        task.owner,
        task.name,
        task.principal_sid,
        xml,
        "0" * 64,
        True,
    )
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    with pytest.raises(ValueError, match="hash"):
        windows.restore(snapshot)


def test_restore_registers_only_verified_owned_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    xml = render_task_xml(task)
    snapshot = windows.TaskSnapshot(
        task.task_path,
        task.owner,
        task.name,
        task.principal_sid,
        xml,
        __import__("hashlib").sha256(xml).hexdigest(),
        True,
    )
    calls: list[str] = []
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: None)
    monkeypatch.setattr(windows, "_create_folder", lambda _folder: calls.append("folder"))
    monkeypatch.setattr(windows, "_register_xml", lambda *_args: calls.append("register"))
    monkeypatch.setattr(
        windows,
        "status",
        lambda *args, **kwargs: windows.TaskStatus(task.task_path, "registered"),
    )
    result = windows.restore(snapshot)
    assert result.action == "created"
    assert calls == ["folder", "register"]


def test_list_tasks_filters_to_managed_owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    parsed = parse_task_xml(render_task_xml(task))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(
        windows, "_powershell", lambda *_args: '[{"path":"\\\\Scripts\\\\snips-runtime","state":"Ready"}]'
    )
    monkeypatch.setattr(
        windows, "_inspect", lambda _path: (b"xml", parsed, windows._TaskInfo(state="Ready", last_result=0))
    )
    assert len(windows.list_tasks(owner="snips")) == 1
    assert windows.list_tasks(owner="other") == []


def test_task_info_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "_powershell", lambda *_args: "not json")
    with pytest.raises(RuntimeError, match="invalid status JSON"):
        windows._task_info(r"\Scripts\snips-runtime")


@pytest.mark.parametrize(
    "operation, expected",
    [
        (windows.enable, "/ENABLE"),
        (windows.disable, "/DISABLE"),
        (windows.start, "/Run"),
        (windows.stop, "/End"),
    ],
)
def test_task_controls_use_owned_task_path_and_requested_operation(
    monkeypatch: pytest.MonkeyPatch, operation, expected: str
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_owned_task", lambda *_args, **_kwargs: r"\Scripts\snips-runtime")
    monkeypatch.setattr(windows, "_require_task_mutation_elevation", lambda _path: None)
    monkeypatch.setattr(
        windows,
        "_run_schtasks",
        lambda args: calls.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )
    operation("snips", "runtime", principal_sid="S-1-5-21-1")
    assert expected in calls[0]
    assert calls[0][calls[0].index("/TN") + 1] == r"\Scripts\snips-runtime"


def test_preview_reports_foreign_task_conflict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    parsed = parse_task_xml(render_task_xml(make_spec(tmp_path, owner="other")))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: (b"xml", parsed, None))
    result = windows.preview(task)
    assert result.action == "conflict"
    assert "different owner" in (result.reason or "")


def test_status_detects_semantic_drift_after_manual_edit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    xml = render_task_xml(task).decode("utf-16").replace(str(task.executable), r"C:\Other\pythonw.exe")
    parsed = parse_task_xml(xml.encode("utf-16"))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: (xml.encode("utf-16"), parsed, None))
    result = windows.status(task.owner, task.name, spec=task)
    assert result.registration_state == "drifted"
    assert result.executable == r"C:\Other\pythonw.exe"


def test_owned_task_rejects_mismatched_principal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = make_spec(tmp_path)
    parsed = parse_task_xml(render_task_xml(task))
    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_inspect", lambda _path: (b"xml", parsed, None))
    monkeypatch.setattr(windows, "current_user_sid", lambda: "S-1-5-21-7")
    with pytest.raises(OwnershipConflictError, match="principal SID"):
        windows._owned_task(task.owner, task.name, folder=task.folder, task_name_override=None, principal_sid=None)


def test_register_xml_cleans_temporary_file_when_schtasks_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Path] = []

    def fail(args: list[str]) -> subprocess.CompletedProcess[bytes]:
        xml_path = Path(args[args.index("/XML") + 1])
        captured.append(xml_path)
        return subprocess.CompletedProcess(args, 1, b"", b"registration failed")

    monkeypatch.setattr(windows, "_require_windows", lambda: None)
    monkeypatch.setattr(windows, "_run_schtasks", fail)
    with pytest.raises(RuntimeError, match="registration failed"):
        windows._register_xml(r"\Scripts\snips-runtime", b"xml")
    assert len(captured) == 1
    assert not captured[0].exists()


def test_pythonw_resolution_checks_sibling_then_base_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    interpreter = tmp_path / "venv" / "Scripts" / "python.exe"
    interpreter.parent.mkdir(parents=True)
    (interpreter.parent / "pythonw.exe").write_bytes(b"")
    assert helpers.resolve_pythonw(interpreter) == (interpreter.parent / "pythonw.exe").resolve()

    fallback = tmp_path / "base" / "pythonw.exe"
    fallback.parent.mkdir()
    fallback.write_bytes(b"")
    other = tmp_path / "other" / "python.exe"
    other.parent.mkdir()
    monkeypatch.setattr(helpers.sys, "base_prefix", str(fallback.parent))
    assert helpers.resolve_pythonw(other) == fallback.resolve()


def test_spawn_detached_retries_when_breakaway_is_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[int] = []

    def fake_popen(_args: list[str], **kwargs: object) -> object:
        flags = int(kwargs["creationflags"])
        calls.append(flags)
        if flags & 0x01000000:
            error = OSError("breakaway denied")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        return object()

    monkeypatch.setattr(helpers, "_is_windows", lambda: True)
    monkeypatch.setattr(helpers.subprocess, "Popen", fake_popen)
    process = helpers.spawn_detached(["AutoHotkey.exe", "snips.ahk"], cwd=tmp_path)
    assert process is not None
    assert len(calls) == 2
    assert calls[0] & 0x01000000
    assert calls[1] & 0x01000000 == 0


def test_named_mutex_file_fallback_times_out_then_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helpers, "_is_windows", lambda: False)
    first = NamedMutex("runtime-lifecycle-test-mutex", timeout_seconds=0.1)
    second = NamedMutex("runtime-lifecycle-test-mutex", timeout_seconds=0.05)
    assert first.acquire()
    assert second.acquire() is False
    first.release()
    assert second.acquire()
    second.release()


def test_named_mutex_rejects_unsafe_name() -> None:
    with pytest.raises(ValueError, match="slashes"):
        NamedMutex("unsafe/name")


def test_windows_mutex_treats_wait_abandoned_as_acquired(monkeypatch: pytest.MonkeyPatch) -> None:
    class Function:
        def __init__(self, result: int) -> None:
            self.result = result

        def __call__(self, *_args):
            return self.result

    class Kernel32:
        CreateMutexW = Function(42)
        WaitForSingleObject = Function(0x00000080)
        ReleaseMutex = Function(1)
        CloseHandle = Function(1)

    monkeypatch.setattr(helpers, "_is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32())
    mutex = NamedMutex("abandoned-lock")
    assert mutex.acquire() is True
    mutex.release()
