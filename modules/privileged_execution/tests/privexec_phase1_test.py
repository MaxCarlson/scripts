"""Phase 1 tests for privexec CLI, protocol validation, and live .NET broker IPC."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from privexec import cli
from privexec.protocol import (
    PROTOCOL_VERSION,
    ProtocolValidationError,
    build_run_request,
    load_params_file,
)
from privexec.transport import UnsupportedPlatformError, WindowsNamedPipeClient

MODULE_ROOT = Path(__file__).resolve().parent.parent
BROKER_DLL = MODULE_ROOT / "broker" / "bin" / "PrivExecBroker.dll"
DESCRIPTORS_DIR = MODULE_ROOT / "descriptors"


def _start_test_broker(
    tmp_path: Path,
    *,
    allow_same_user: bool = True,
    allowed_client_sids: list[str] | None = None,
    allowed_capabilities: list[str] | None = None,
    allowed_targets: list[str] | None = None,
    ttl_seconds: int = 120,
) -> tuple[subprocess.Popen[str], str]:
    pipe_name = f"privexec-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    state_dir = tmp_path / "state"
    grant_file = tmp_path / "grant.json"
    grant_data = {
        "allowed_client_sids": allowed_client_sids or [],
        "allowed_capabilities": allowed_capabilities or ["synthetic.echo"],
        "allowed_targets": allowed_targets or ["synth-target-1"],
        "allow_mutation": False,
        "allowed_mutation_capabilities": [],
        "ttl_seconds": ttl_seconds,
    }
    grant_file.write_text(json.dumps(grant_data), encoding="utf-8")

    cmd = [
        "dotnet",
        str(BROKER_DLL),
        "--pipe",
        pipe_name,
        "--descriptors-dir",
        str(DESCRIPTORS_DIR),
        "--state-dir",
        str(state_dir),
        "--grant-file",
        str(grant_file),
    ]
    if allow_same_user:
        cmd.append("--allow-same-user")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    deadline = time.monotonic() + 10.0
    ready_line = ""
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"Broker exited early ({proc.returncode}): {ready_line}\n{err}")
        line = proc.stdout.readline()
        if line:
            ready_line = line.strip()
            if ready_line.startswith("PRIVEXEC_BROKER_READY"):
                return proc, pipe_name
    proc.kill()
    raise TimeoutError("Timed out waiting for PrivExecBroker readiness line.")


def _stop_proc(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_protocol_rejects_forbidden_client_fields(tmp_path: Path) -> None:
    with pytest.raises(ProtocolValidationError):
        build_run_request(
            capability="synthetic.echo",
            target_id="synth-target-1",
            parameters={"authorized": True},
        )

    bad_params = tmp_path / "bad.json"
    bad_params.write_text(json.dumps({"script_path": "C:\\evil.ps1"}), encoding="utf-8")
    with pytest.raises(ProtocolValidationError):
        load_params_file(bad_params)


def test_cli_rejects_apply_with_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["run", "synthetic.echo", "-t", "synth-target-1", "-n", "-A"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Cannot combine" in captured.err


def test_cli_broker_start_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["broker", "start", "-n", "-t", "60"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "broker_start_plan"
    assert out["ttl_seconds"] == 60


def test_unsupported_platform_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    client = WindowsNamedPipeClient("privexec-test")
    with pytest.raises(UnsupportedPlatformError):
        client.send({"protocol_version": PROTOCOL_VERSION, "action": "status"})


def test_cli_result_wait_uses_mock_client(capsys: pytest.CaptureFixture[str]) -> None:
    responses: list[dict[str, Any]] = [
        {"protocol_version": 1, "operation_id": "op-1", "state": "executing"},
        {"protocol_version": 1, "operation_id": "op-1", "state": "succeeded", "exit_code": 0},
    ]

    class FakeClient:
        def send(self, payload: dict[str, Any]) -> dict[str, Any]:
            assert payload["action"] == "result"
            return responses.pop(0)

    rc = cli.main(["result", "op-1", "-w", "-W", "5", "-f", "json"], client_factory=lambda _p: FakeClient())
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "succeeded"


@pytest.mark.skipif(os.name != "nt" or not BROKER_DLL.is_file(), reason="Requires Windows and built PrivExecBroker.dll")
def test_end_to_end_synthetic_run_status_result_and_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proc, pipe = _start_test_broker(tmp_path)
    try:
        assert cli.main(["status", "-P", pipe, "-f", "json"]) == 0
        status_out = json.loads(capsys.readouterr().out)
        assert status_out["status"] == "active"
        assert "synthetic.echo" in status_out["capabilities"]

        params_file = tmp_path / "params.json"
        params_file.write_text(json.dumps({"message": "phase1-ok"}), encoding="utf-8")

        assert (
            cli.main(
                [
                    "run",
                    "synthetic.echo",
                    "-t",
                    "synth-target-1",
                    "-T",
                    "synthetic",
                    "-p",
                    str(params_file),
                    "-n",
                    "-r",
                    "req-phase1-001",
                    "-P",
                    pipe,
                    "-f",
                    "json",
                ]
            )
            == 0
        )
        run_out = json.loads(capsys.readouterr().out)
        assert run_out["state"] == "succeeded"
        assert run_out["authorized"] is True
        assert run_out["result"]["echo"] == "phase1-ok"
        op_id = run_out["operation_id"]

        assert cli.main(["result", op_id, "-P", pipe, "-f", "json"]) == 0
        res_out = json.loads(capsys.readouterr().out)
        assert res_out["operation_id"] == op_id
        assert res_out["state"] == "succeeded"

        # Negative authorization checks over real named pipe
        assert (
            cli.main(
                [
                    "run",
                    "synthetic.echo",
                    "-t",
                    "unapproved-target",
                    "-T",
                    "synthetic",
                    "-P",
                    pipe,
                    "-f",
                    "json",
                ]
            )
            == 1
        )
        denied_target = json.loads(capsys.readouterr().out)
        assert denied_target["state"] == "denied"
        assert denied_target["diagnostic_category"] == "unauthorized_target"

        assert (
            cli.main(
                [
                    "run",
                    "unknown.cap",
                    "-t",
                    "synth-target-1",
                    "-T",
                    "synthetic",
                    "-P",
                    pipe,
                    "-f",
                    "json",
                ]
            )
            == 1
        )
        denied_cap = json.loads(capsys.readouterr().out)
        assert denied_cap["state"] == "denied"
        assert denied_cap["diagnostic_category"] == "unknown_capability"

        # Operator stop shuts down broker cleanly
        assert cli.main(["broker", "stop", "-P", pipe, "-f", "json"]) == 0
        stop_out = json.loads(capsys.readouterr().out)
        assert stop_out["status"] == "revoked_and_stopping"
        assert proc.wait(timeout=5) == 0
    finally:
        _stop_proc(proc)


@pytest.mark.skipif(os.name != "nt" or not BROKER_DLL.is_file(), reason="Requires Windows and built PrivExecBroker.dll")
def test_end_to_end_wrong_client_sid_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proc, pipe = _start_test_broker(
        tmp_path,
        allow_same_user=False,
        allowed_client_sids=["S-1-5-21-1234-5678-9012-1099"],
    )
    try:
        rc = cli.main(
            [
                "run",
                "synthetic.echo",
                "-t",
                "synth-target-1",
                "-T",
                "synthetic",
                "-P",
                pipe,
                "-f",
                "json",
            ]
        )
        assert rc == 1
        denied = json.loads(capsys.readouterr().out)
        assert denied["state"] == "denied"
        assert denied["diagnostic_category"] == "unauthorized_identity"
    finally:
        _stop_proc(proc)
