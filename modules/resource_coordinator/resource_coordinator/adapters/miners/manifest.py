"""
Miner launch manifest resolution and safe process configuration.

Separates stable miner binary path, arguments, working directory, and environment
from interactive launcher scripts. Redacts wallet and pool account credentials for logs.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

if TYPE_CHECKING:
    from resource_coordinator.config import ProcessConfig

logger = logging.getLogger(__name__)


def redact_miner_args(args: Sequence[str]) -> List[str]:
    """Redact sensitive wallet/user credentials from arguments for safe logging."""
    redacted: List[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            redacted.append("[REDACTED]")
            skip_next = False
            continue
        if arg in {"--user", "--wallet", "-u", "-w", "--password", "-p"}:
            redacted.append(arg)
            skip_next = True
        elif any(arg.startswith(prefix) for prefix in ("--user=", "--wallet=", "--password=")):
            flag, _ = arg.split("=", 1)
            redacted.append(f"{flag}=[REDACTED]")
        else:
            redacted.append(arg)
    return redacted


@dataclass(frozen=True)
class MinerManifest:
    """Stable, non-interactive manifest for launching a coordinator-owned miner process."""

    miner_type: str  # "krig" | "srbminer"
    executable: str
    arguments: List[str]
    working_directory: str
    power_limit_watts: int = 0
    core_clock_mhz: int = 0
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def redacted_arguments(self) -> List[str]:
        """Arguments with sensitive account/wallet identifiers replaced with [REDACTED]."""
        return redact_miner_args(self.arguments)

    def to_process_config(
        self,
        name: str = "krig_miner",
        stop_timeout_seconds: float = 10.0,
        new_console: bool = False,
        allow_force_termination: bool = False,
    ) -> ProcessConfig:
        """Convert manifest to a ProcessConfig suitable for resource_coordinator."""
        from resource_coordinator.config import ProcessConfig

        return ProcessConfig(
            name=name,
            backend="windows" if os.name == "nt" else "fake",
            executable=self.executable,
            arguments=list(self.arguments),
            working_directory=self.working_directory,
            stop_timeout_seconds=stop_timeout_seconds,
            new_console=new_console,
            allow_external_stop=False,
            allow_external_restart=False,
            adopt_external=False,
            allow_force_termination=allow_force_termination,
        )

    @classmethod
    def from_preview_text(
        cls,
        preview_text: str,
        miner_type: str = "krig",
        working_directory: Optional[str] = None,
        power_limit_watts: int = 0,
        core_clock_mhz: int = 0,
    ) -> MinerManifest:
        """Parse the output of `start-prl.ps1 -Preview` to build a verified manifest."""
        exe_match = re.search(r"Executable:\s*(.+)$", preview_text, re.MULTILINE)
        args_match = re.search(r"Arguments:\s*(.+)$", preview_text, re.MULTILINE)

        if not exe_match:
            raise ValueError("Could not find 'Executable:' in preview output")
        if not args_match:
            raise ValueError("Could not find 'Arguments:' in preview output")

        executable = exe_match.group(1).strip()
        raw_args = args_match.group(1).strip()

        # Parse command line arguments safely
        # Note: on Windows shlex.split with posix=False handles Windows quoting
        args = shlex.split(raw_args, posix=False) if os.name == "nt" else shlex.split(raw_args)

        cwd = working_directory or str(Path(executable).parent)

        return cls(
            miner_type=miner_type,
            executable=executable,
            arguments=args,
            working_directory=cwd,
            power_limit_watts=power_limit_watts,
            core_clock_mhz=core_clock_mhz,
        )

    @classmethod
    def resolve_from_mining_repo(
        cls,
        mining_repo: str | Path,
        miner_type: str = "krig",
        power_limit_watts: int = 0,
        krig_core_clock_mhz: int = 0,
        kryptex_username: Optional[str] = None,
        worker_name: Optional[str] = None,
        use_preview_invocation: bool = True,
    ) -> MinerManifest:
        """
        Resolve manifest from a local Mining repository.
        If use_preview_invocation is True and pwsh is available, executes `start-prl.ps1 -Preview`.
        Otherwise, builds the configuration deterministically from known vendor paths.
        """
        repo_path = Path(mining_repo).resolve()
        script_path = repo_path / "start-prl.ps1"

        if use_preview_invocation and script_path.exists():
            cmd = ["pwsh", "-NoProfile", "-File", str(script_path), "-Preview", "-Miner", miner_type]
            if power_limit_watts > 0:
                cmd.extend(["-PowerLimitWatts", str(power_limit_watts)])
            if kryptex_username:
                cmd.extend(["-KryptexUsername", kryptex_username])
            if worker_name:
                cmd.extend(["-WorkerName", worker_name])

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15.0,
                )
                return cls.from_preview_text(
                    proc.stdout,
                    miner_type=miner_type,
                    power_limit_watts=power_limit_watts,
                    core_clock_mhz=0,
                )
            except Exception as exc:
                raise RuntimeError(f"Failed running start-prl.ps1 -Preview: {exc}") from exc

        # Direct static resolution fallback
        if miner_type == "krig":
            rel_exe = Path("vendor") / "krig-miner-1.5.6" / "krig-miner.exe"
            exe_path = repo_path / rel_exe
            wallet = kryptex_username or "krxXPVG8JN"
            worker = worker_name or "Xeres"
            args = [
                "--coin",
                "pearl",
                "--url",
                "stratum+ssl://prl-us.kryptex.network:8048",
                "--user",
                f"{wallet}/{worker}",
            ]
            if power_limit_watts > 0:
                args.extend(["--gpu-plimit", str(power_limit_watts)])
        else:
            rel_exe = Path("vendor") / "srbminer-3.7.5" / "SRBMiner-Multi-3-7-5" / "SRBMiner-MULTI.exe"
            exe_path = repo_path / rel_exe
            wallet = kryptex_username or "krxXPVG8JN"
            worker = worker_name or "Xeres"
            args = [
                "--disable-cpu",
                "--algorithm",
                "pearlhash",
                "--pool",
                "prl-us.kryptex.network:8048",
                "--tls",
                "true",
                "--wallet",
                f"{wallet}/{worker}",
                "--password",
                "x",
                "--gpu-id",
                "1",
            ]
            if power_limit_watts > 0:
                args.extend(["--gpu-plimit0", str(power_limit_watts)])
            else:
                args.append("--gpu-disable-oc")

        return cls(
            miner_type=miner_type,
            executable=str(exe_path),
            arguments=args,
            working_directory=str(exe_path.parent),
            power_limit_watts=power_limit_watts,
            core_clock_mhz=0,
        )
