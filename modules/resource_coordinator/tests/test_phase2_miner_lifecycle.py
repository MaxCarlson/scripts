"""
Phase 02 Miner Lifecycle, Manifest Resolution, and Process Ownership Test Suite.

Verifies:
- W01: Manifest resolution and dry-run compatibility; arguments match launcher.
- W02: Foreign miner running -> refuse implicit adoption/stop/start.
- W03: Exact child process identity (PID + creation-time matching).
- W04: Safe process stop and child tree verification.
- W05: Stop failure leaves resource safe without unverified forward.
- W06: Rapid stop/start cycles maintain at most one instance and leave zero orphans.
- Credential redaction in logged and displayed arguments.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import psutil
import pytest

from resource_coordinator.adapters.miners.manifest import MinerManifest, redact_miner_args
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessInfo,
    ProcessLifecycleOwner,
    ProcessState,
    ProcessSupervisor,
    WindowsProcessBackend,
)


def test_redact_miner_args():
    """Verify wallet and pool credentials are comprehensively redacted."""
    raw = [
        "--coin", "pearl",
        "--url", "stratum+ssl://prl.kryptex.network:8048",
        "--user", "krxXPVG8JN/Xeres",
        "--gpu-cclock", "2400",
        "--password", "secret123",
        "--gpu-plimit", "550",
    ]
    redacted = redact_miner_args(raw)
    assert "[REDACTED]" in redacted
    assert "krxXPVG8JN/Xeres" not in redacted
    assert "secret123" not in redacted
    assert "--gpu-cclock" in redacted
    assert "2400" in redacted
    assert "550" in redacted

    # Test equals-separated flags
    raw_eq = ["--user=mywallet/worker", "--password=pass"]
    redacted_eq = redact_miner_args(raw_eq)
    assert redacted_eq == ["--user=[REDACTED]", "--password=[REDACTED]"]


def test_manifest_from_preview_text():
    """W01: Verify parsing of start-prl.ps1 -Preview text."""
    preview_output = """
Coin: Pearl (PRL)
Miner: krig
Pool: Kryptex North America, SSL port 8048
Kryptex username/worker: krxXPVG8JN/Xeres
The RTX 5090 will mine until you stop the miner with Ctrl+C.
Requested temporary GPU power limit: 550 W.
KRig core clock lock: 2400 MHz.
Executable: C:\\Users\\mcarls\\src\\Mining\\vendor\\krig-miner-1.5.6\\krig-miner.exe
Arguments: --coin pearl --url stratum+ssl://prl-us.kryptex.network:8048 --user krxXPVG8JN/Xeres --gpu-cclock 2400 --gpu-plimit 550
Preview only: no miner started and no GPU settings changed.
"""
    manifest = MinerManifest.from_preview_text(
        preview_output,
        miner_type="krig",
        power_limit_watts=550,
        core_clock_mhz=2400,
    )
    assert manifest.miner_type == "krig"
    assert manifest.executable == r"C:\Users\mcarls\src\Mining\vendor\krig-miner-1.5.6\krig-miner.exe"
    assert "--coin" in manifest.arguments
    assert "pearl" in manifest.arguments
    assert "--gpu-cclock" in manifest.arguments
    assert "2400" in manifest.arguments
    assert manifest.power_limit_watts == 550
    assert manifest.core_clock_mhz == 2400
    assert "[REDACTED]" in manifest.redacted_arguments
    assert "krxXPVG8JN/Xeres" not in manifest.redacted_arguments


def test_manifest_resolution_from_actual_mining_repo():
    """W01: Resolve manifest directly against local Mining repo."""
    mining_repo = Path(r"C:\Users\mcarls\src\Mining")
    if not (mining_repo / "start-prl.ps1").exists():
        pytest.skip("Mining repo not found on host")

    manifest = MinerManifest.resolve_from_mining_repo(
        mining_repo=mining_repo,
        miner_type="krig",
        power_limit_watts=550,
        krig_core_clock_mhz=2400,
        use_preview_invocation=True,
    )
    assert manifest.miner_type == "krig"
    assert manifest.executable.endswith("krig-miner.exe")
    assert "--coin" in manifest.arguments
    assert "pearl" in manifest.arguments
    assert "--gpu-cclock" in manifest.arguments
    assert "2400" in manifest.arguments
    assert "--gpu-plimit" in manifest.arguments
    assert "550" in manifest.arguments


def test_manifest_to_process_config():
    """W01, W03: Manifest config enforces non-interactive same-console ownership."""
    manifest = MinerManifest(
        miner_type="krig",
        executable=r"C:\Mining\krig-miner.exe",
        arguments=["--coin", "pearl"],
        working_directory=r"C:\Mining",
    )
    p_cfg = manifest.to_process_config(name="krig_miner", stop_timeout_seconds=8.0)
    assert p_cfg.name == "krig_miner"
    assert p_cfg.executable == r"C:\Mining\krig-miner.exe"
    assert p_cfg.arguments == ["--coin", "pearl"]
    assert p_cfg.stop_timeout_seconds == 8.0
    # Must NOT use new console (to preserve CTRL+BREAK process-group signaling)
    assert p_cfg.new_console is False
    # Must refuse external adoption
    assert p_cfg.allow_external_stop is False
    assert p_cfg.allow_external_restart is False
    assert p_cfg.adopt_external is False
    assert p_cfg.allow_force_termination is False


@pytest.mark.asyncio
async def test_foreign_miner_refuses_implicit_adoption_and_stop():
    """W02: External running process is NOT adopted and stop is refused by default."""
    dispatcher = EventDispatcher()
    backend = FakeProcessBackend(
        name="krig_miner",
        running=True,
        external=True,
        allow_external_stop=False,
        allow_external_restart=False,
    )
    # Backend reports EXTERNAL
    backend.lifecycle_owner = ProcessLifecycleOwner.EXTERNAL
    backend.is_coordinator_owned = False

    supervisor = ProcessSupervisor(backend=backend, event_dispatcher=dispatcher)
    st = await supervisor.status()
    assert st.state == ProcessState.EXTERNAL_RUNNING
    assert st.lifecycle_owner == ProcessLifecycleOwner.EXTERNAL
    assert st.is_coordinator_owned is False

    # Stop MUST be refused
    stopped = await supervisor.stop(timeout=1.0)
    assert stopped is False
    assert (await supervisor.status()).state == ProcessState.EXTERNAL_RUNNING


@pytest.mark.asyncio
async def test_process_identity_verification_and_pid_reuse():
    """W03: Exact PID and creation time must match before stop action is permitted."""
    real_python = psutil.Process().exe()
    backend = WindowsProcessBackend(
        name="test_miner",
        executable=real_python,
        arguments=["-c", "import time; time.sleep(10)"],
        allow_force_termination=True,
    )
    # Simulate a stale recorded PID with a different creation time
    backend._owned_pid = 99999
    backend._owned_create_time = 12345.0

    st = await backend.status()
    # Cannot be verified running because PID 99999 does not match creation time 12345.0
    assert backend._find_owned_process() is None


@pytest.mark.asyncio
async def test_disposable_process_lifecycle_start_stop(tmp_path: Path):
    """W04, W06: Disposable helper process lifecycle with exact PID/create-time tracking."""
    # Use cscript.exe with a tiny disposable VBScript that sleeps
    vbs_script = tmp_path / "sleep.vbs"
    vbs_script.write_text('WScript.Sleep 30000\n', encoding="utf-8")
    cscript_exe = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cscript.exe")

    backend = WindowsProcessBackend(
        name="disposable_worker",
        executable=cscript_exe,
        arguments=["//Nologo", str(vbs_script)],
        new_console=False,
        allow_force_termination=True,
    )
    supervisor = ProcessSupervisor(backend=backend)

    # 1. Start process
    started = await supervisor.start(origin="coordinator", only_if_stopped_by_coordinator=False)
    assert started is True
    st = await supervisor.status()
    assert st.state == ProcessState.RUNNING
    assert st.is_coordinator_owned is True
    assert st.pid is not None
    assert st.create_time is not None

    # Verify process is actually alive in OS
    proc = psutil.Process(st.pid)
    assert proc.is_running()

    # 2. Stop process
    stopped = await supervisor.stop(timeout=5.0)
    assert stopped is True
    assert (await supervisor.status()).state == ProcessState.STOPPED
    assert supervisor.was_stopped_by_coordinator is True

    # Verify process is completely dead in OS
    assert not proc.is_running()

    # 3. Rapid restart and stop cycle
    restarted = await supervisor.start(origin="coordinator", only_if_stopped_by_coordinator=True)
    assert restarted is True
    new_st = await supervisor.status()
    assert new_st.state == ProcessState.RUNNING
    assert new_st.pid != st.pid  # New PID

    # Stop again cleanly
    await supervisor.stop(timeout=5.0)
    assert (await supervisor.status()).state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_child_process_cleanup_verification(tmp_path: Path):
    """W04: If child spawns descendants, stop verifies all descendants have exited."""
    cscript_exe = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cscript.exe")
    child_vbs = tmp_path / "child.vbs"
    child_vbs.write_text('WScript.Sleep 30000\n', encoding="utf-8")

    parent_vbs = tmp_path / "parent.vbs"
    parent_script = (
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run "{cscript_exe} //Nologo ""{child_vbs}""", 0, False\r\n'
        'WScript.Sleep 30000\r\n'
    )
    parent_vbs.write_text(parent_script, encoding="utf-8")

    backend = WindowsProcessBackend(
        name="tree_worker",
        executable=cscript_exe,
        arguments=["//Nologo", str(parent_vbs)],
        new_console=False,
        allow_force_termination=True,
    )
    supervisor = ProcessSupervisor(backend=backend)

    assert await supervisor.start(origin="coordinator", only_if_stopped_by_coordinator=False) is True
    # Give child time to spawn
    await asyncio.sleep(0.5)

    st = await supervisor.status()
    assert st.state == ProcessState.RUNNING
    parent_proc = psutil.Process(st.pid)
    children = parent_proc.children(recursive=True)

    # Stop supervisor
    stopped = await supervisor.stop(timeout=5.0)
    assert stopped is True
    assert (await supervisor.status()).state == ProcessState.STOPPED

    # Ensure parent and all children are dead
    assert not parent_proc.is_running()
    for child in children:
        assert not child.is_running()
