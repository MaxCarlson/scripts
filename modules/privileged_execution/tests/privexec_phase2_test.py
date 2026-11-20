"""Phase 2 end-to-end execution, persistence, and adversarial security tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from privexec import cli

MODULE_ROOT = Path(__file__).resolve().parent.parent
BROKER_DLL = MODULE_ROOT / "broker" / "bin" / "PrivExecBroker.dll"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_synthetic_descriptor(
    descriptors_dir: Path,
    *,
    cap_id: str,
    script_path: Path,
    is_mutating: bool = False,
    supports_apply: bool = False,
    max_duration_seconds: int = 15,
    extra_params: dict | None = None,
) -> Path:
    descriptors_dir.mkdir(parents=True, exist_ok=True)
    param_schema = {
        "marker": {
            "type": "string",
            "required": False,
            "pattern": "^[A-Za-z0-9._-]{1,64}$",
            "cli_flag": "--marker",
            "mode_scope": "any",
        },
        "sleep_sec": {
            "type": "int",
            "required": False,
            "min": 0,
            "max": 30,
            "cli_flag": "--sleep-sec",
            "mode_scope": "any",
        },
    }
    if extra_params:
        param_schema.update(extra_params)

    desc = {
        "schema_version": 1,
        "capability_id": cap_id,
        "version": "1.0.0",
        "runner_type": "python",
        "executable_path": sys.executable,
        "executable_sha256": _sha256_file(Path(sys.executable)),
        "script_path": str(script_path),
        "script_sha256": _sha256_file(script_path),
        "working_directory": str(script_path.parent),
        "target_types": ["synthetic"],
        "allowed_targets": ["synth-vm-1", "synth-vm-2"],
        "supports_dry_run": True,
        "supports_apply": supports_apply,
        "is_mutating": is_mutating,
        "max_duration_seconds": max_duration_seconds,
        "requires_guest_credential": False,
        "fixed_args": ["-B", "{script_path}"],
        "dry_run_args": ["--mode", "dry_run"],
        "apply_args": ["--mode", "apply"],
        "parameter_schema": param_schema,
    }
    out = descriptors_dir / f"{cap_id}.json"
    out.write_text(json.dumps(desc, indent=2), encoding="utf-8")
    return out


def _start_broker(
    tmp_path: Path,
    *,
    descriptors_dir: Path,
    state_dir: Path,
    allowed_capabilities: list[str],
    allowed_targets: list[str],
    allow_mutation: bool = False,
    allowed_mutation_capabilities: list[str] | None = None,
) -> tuple[subprocess.Popen[str], str]:
    pipe_name = f"privexec-p2-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    grant_file = tmp_path / f"grant-{uuid.uuid4().hex[:6]}.json"
    grant_file.write_text(
        json.dumps(
            {
                "allowed_capabilities": allowed_capabilities,
                "allowed_targets": allowed_targets,
                "allow_mutation": allow_mutation,
                "allowed_mutation_capabilities": allowed_mutation_capabilities or [],
                "ttl_seconds": 120,
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [
            "dotnet",
            str(BROKER_DLL),
            "--pipe",
            pipe_name,
            "--descriptors-dir",
            str(descriptors_dir),
            "--state-dir",
            str(state_dir),
            "--grant-file",
            str(grant_file),
            "--allow-same-user",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdout is not None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"Broker exited early ({proc.returncode}): {err}")
        line = proc.stdout.readline()
        if line and line.strip().startswith("PRIVEXEC_BROKER_READY"):
            return proc, pipe_name
    proc.kill()
    raise TimeoutError("Broker readiness timeout")


def _stop_proc(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _create_worker_script(script_path: Path, counter_file: Path, started_flag: Path | None = None) -> None:
    script = f"""
import argparse, json, pathlib, time
p = argparse.ArgumentParser()
p.add_argument("--mode", required=True)
p.add_argument("--marker", default="default")
p.add_argument("--sleep-sec", type=int, default=0)
args = p.parse_args()
started = {repr(str(started_flag)) if started_flag else "None"}
if started:
    pathlib.Path(started).write_text("started", encoding="utf-8")
if args.sleep_sec > 0:
    time.sleep(args.sleep_sec)
cfile = pathlib.Path({repr(str(counter_file))})
prev = int(cfile.read_text(encoding="utf-8")) if cfile.exists() else 0
if args.mode == "apply":
    cfile.write_text(str(prev + 1), encoding="utf-8")
print("password=TopSecretGuestPassword123!")
print("PRIVEXEC_SECRET:tok_xyz_999")
print(json.dumps({{"mode": args.mode, "marker": args.marker, "apply_count": prev + (1 if args.mode == "apply" else 0)}}))
"""
    script_path.write_text(script.strip() + "\n", encoding="utf-8")


@pytest.mark.skipif(os.name != "nt" or not BROKER_DLL.is_file(), reason="Requires Windows and built PrivExecBroker.dll")
def test_phase2_execution_idempotency_redaction_and_restart_persistence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    desc_dir = tmp_path / "descriptors"
    state_dir = tmp_path / "state"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "worker.py"
    counter_file = tmp_path / "apply_count.txt"
    _create_worker_script(script_path, counter_file)

    _write_synthetic_descriptor(
        desc_dir,
        cap_id="synth.mutate",
        script_path=script_path,
        is_mutating=True,
        supports_apply=True,
    )

    proc, pipe = _start_broker(
        tmp_path,
        descriptors_dir=desc_dir,
        state_dir=state_dir,
        allowed_capabilities=["synth.mutate"],
        allowed_targets=["synth-vm-1"],
        allow_mutation=True,
        allowed_mutation_capabilities=["synth.mutate"],
    )
    try:
        # 1. Dry-run default does not mutate
        p_dry = tmp_path / "dry.json"
        p_dry.write_text(json.dumps({"marker": "dry1"}), encoding="utf-8")
        assert cli.main(["run", "synth.mutate", "-t", "synth-vm-1", "-T", "synthetic", "-p", str(p_dry), "-P", pipe]) == 0
        dry_out = json.loads(capsys.readouterr().out)
        assert dry_out["mode"] == "dry_run"
        assert dry_out["result"]["apply_count"] == 0
        assert not counter_file.exists()

        # 2. Apply with request_id executes once; duplicate request_id replays without re-executing
        p_app = tmp_path / "apply.json"
        p_app.write_text(json.dumps({"marker": "app1"}), encoding="utf-8")
        assert (
            cli.main(
                [
                    "run",
                    "synth.mutate",
                    "-t",
                    "synth-vm-1",
                    "-T",
                    "synthetic",
                    "-p",
                    str(p_app),
                    "-A",
                    "-r",
                    "req-idemp-001",
                    "-P",
                    pipe,
                ]
            )
            == 0
        )
        app_out = json.loads(capsys.readouterr().out)
        assert app_out["state"] == "succeeded"
        assert counter_file.read_text(encoding="utf-8") == "1"
        op_id = app_out["operation_id"]

        # Verify secrets were redacted from evidence file
        ev_file = Path(app_out["evidence"][0])
        ev_text = ev_file.read_text(encoding="utf-8")
        assert "TopSecretGuestPassword123" not in ev_text
        assert "tok_xyz_999" not in ev_text
        assert "[REDACTED]" in ev_text

        # Replay identical request_id + payload
        assert (
            cli.main(
                [
                    "run",
                    "synth.mutate",
                    "-t",
                    "synth-vm-1",
                    "-T",
                    "synthetic",
                    "-p",
                    str(p_app),
                    "-A",
                    "-r",
                    "req-idemp-001",
                    "-P",
                    pipe,
                ]
            )
            == 0
        )
        replay_out = json.loads(capsys.readouterr().out)
        assert replay_out["operation_id"] == op_id
        assert counter_file.read_text(encoding="utf-8") == "1"

        # Reuse request_id with DIFFERENT payload -> denied (409)
        p_diff = tmp_path / "diff.json"
        p_diff.write_text(json.dumps({"marker": "app2"}), encoding="utf-8")
        assert (
            cli.main(
                [
                    "run",
                    "synth.mutate",
                    "-t",
                    "synth-vm-1",
                    "-T",
                    "synthetic",
                    "-p",
                    str(p_diff),
                    "-A",
                    "-r",
                    "req-idemp-001",
                    "-P",
                    pipe,
                ]
            )
            == 1
        )
        mismatch_out = json.loads(capsys.readouterr().out)
        assert mismatch_out["diagnostic_category"] == "request_id_payload_mismatch"

        # Argument injection attempt rejected
        p_inj = tmp_path / "inj.json"
        p_inj.write_text(json.dumps({"marker": "x; whoami"}), encoding="utf-8")
        assert (
            cli.main(
                [
                    "run",
                    "synth.mutate",
                    "-t",
                    "synth-vm-1",
                    "-T",
                    "synthetic",
                    "-p",
                    str(p_inj),
                    "-P",
                    pipe,
                ]
            )
            == 1
        )
        inj_out = json.loads(capsys.readouterr().out)
        assert inj_out["diagnostic_category"] == "invalid_parameters"

        # Script tampering after startup rejected
        script_path.write_text("print('tampered')\n", encoding="utf-8")
        assert (
            cli.main(
                [
                    "run",
                    "synth.mutate",
                    "-t",
                    "synth-vm-1",
                    "-T",
                    "synthetic",
                    "-P",
                    pipe,
                ]
            )
            == 1
        )
        tamper_out = json.loads(capsys.readouterr().out)
        assert tamper_out["diagnostic_category"] == "integrity_check_failed"

        assert cli.main(["broker", "stop", "-P", pipe]) == 0
        capsys.readouterr()
        assert proc.wait(timeout=5) == 0
    finally:
        _stop_proc(proc)

    # Restart broker on same state_dir and retrieve durable result
    _create_worker_script(script_path, counter_file)
    proc2, pipe2 = _start_broker(
        tmp_path,
        descriptors_dir=desc_dir,
        state_dir=state_dir,
        allowed_capabilities=["synth.mutate"],
        allowed_targets=["synth-vm-1"],
    )
    try:
        assert cli.main(["result", op_id, "-P", pipe2, "-f", "json"]) == 0
        persisted = json.loads(capsys.readouterr().out)
        assert persisted["operation_id"] == op_id
        assert persisted["state"] == "succeeded"
    finally:
        _stop_proc(proc2)


@pytest.mark.skipif(os.name != "nt" or not BROKER_DLL.is_file(), reason="Requires Windows and built PrivExecBroker.dll")
def test_phase2_concurrent_mutation_conflict_and_crash_unknown_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    desc_dir = tmp_path / "descriptors"
    state_dir = tmp_path / "state"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "slow_worker.py"
    counter_file = tmp_path / "apply_count.txt"
    started_flag = tmp_path / "started.flag"
    _create_worker_script(script_path, counter_file, started_flag)

    _write_synthetic_descriptor(
        desc_dir,
        cap_id="synth.slow",
        script_path=script_path,
        is_mutating=True,
        supports_apply=True,
        max_duration_seconds=20,
    )

    proc, pipe = _start_broker(
        tmp_path,
        descriptors_dir=desc_dir,
        state_dir=state_dir,
        allowed_capabilities=["synth.slow"],
        allowed_targets=["synth-vm-1"],
        allow_mutation=True,
        allowed_mutation_capabilities=["synth.slow"],
    )
    first_result_holder: dict[str, str] = {}

    def _run_slow() -> None:
        from privexec.protocol import build_run_request
        from privexec.transport import WindowsNamedPipeClient

        req = build_run_request(
            capability="synth.slow",
            target_id="synth-vm-1",
            target_type="synthetic",
            mode="apply",
            request_id="req-crash-mut-1",
            parameters={"sleep_sec": 5},
        )
        try:
            resp = WindowsNamedPipeClient(pipe).send(req)
            first_result_holder["resp"] = json.dumps(resp)
        except Exception as exc:  # noqa: BLE001
            first_result_holder["err"] = str(exc)

    try:
        t = threading.Thread(target=_run_slow, daemon=True)
        t.start()
        deadline = time.monotonic() + 5.0
        while not started_flag.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started_flag.exists()

        # Concurrent conflicting mutation on same target rejected immediately
        assert (
            cli.main(
                [
                    "run",
                    "synth.slow",
                    "-t",
                    "synth-vm-1",
                    "-T",
                    "synthetic",
                    "-A",
                    "-r",
                    "req-conflict-2",
                    "-P",
                    pipe,
                ]
            )
            == 1
        )
        conflict_out = json.loads(capsys.readouterr().out)
        assert conflict_out["diagnostic_category"] == "target_mutation_conflict"

        # Simulate unclean broker crash while first mutation is still executing
        proc.kill()
        proc.wait(timeout=5)
        t.join(timeout=2)
    finally:
        _stop_proc(proc)

    # Restart broker on same state_dir: interrupted mutation becomes outcome_unknown and will NOT auto-replay
    proc2, pipe2 = _start_broker(
        tmp_path,
        descriptors_dir=desc_dir,
        state_dir=state_dir,
        allowed_capabilities=["synth.slow"],
        allowed_targets=["synth-vm-1"],
        allow_mutation=True,
        allowed_mutation_capabilities=["synth.slow"],
    )
    try:
        p_replay = tmp_path / "replay_sleep.json"
        p_replay.write_text(json.dumps({"sleep_sec": 5}), encoding="utf-8")
        assert (
            cli.main(
                [
                    "run",
                    "synth.slow",
                    "-t",
                    "synth-vm-1",
                    "-T",
                    "synthetic",
                    "-p",
                    str(p_replay),
                    "-A",
                    "-r",
                    "req-crash-mut-1",
                    "-P",
                    pipe2,
                ]
            )
            == 1
        )
        unknown_out = json.loads(capsys.readouterr().out)
        assert unknown_out["state"] == "outcome_unknown"
        assert unknown_out["diagnostic_category"] == "broker_crash_unknown_outcome"
        assert not counter_file.exists()
    finally:
        _stop_proc(proc2)
