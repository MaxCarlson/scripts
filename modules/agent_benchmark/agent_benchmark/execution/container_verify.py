"""Secure containerized code verification sandbox for untrusted model execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from uuid import uuid4


class SandboxUnavailableError(RuntimeError):
    """Raised when the container sandbox (e.g. Docker daemon) is unavailable."""


@dataclass(frozen=True)
class SandboxConfig:
    """Security and resource limits for running untrusted model-generated code."""

    image: str = "python:3.11-slim"
    timeout_seconds: float = 10.0
    memory_limit: str = "512m"
    cpu_limit: str = "1.0"
    pids_limit: int = 64
    network_disabled: bool = True
    read_only_rootfs: bool = True
    cap_drop_all: bool = True
    no_new_privileges: bool = True


@dataclass(frozen=True)
class SandboxExecutionResult:
    """Outcome of running code inside the container sandbox."""

    success: bool
    status: str  # "passed" | "failed" | "timed_out" | "error"
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    error_code: str | None = None
    error_detail: str | None = None


class ContainerVerifier:
    """
    Executes untrusted code within an isolated container sandbox.
    Fails closed if container engine is unavailable; NEVER executes untrusted code on host.
    """

    def __init__(
        self,
        config: SandboxConfig | None = None,
        *,
        mock_runner: Any = None,
    ) -> None:
        self.config = config or SandboxConfig()
        self._mock_runner = mock_runner

    def is_sandbox_available(self) -> bool:
        """Check whether the Docker container daemon is reachable without starting it."""
        if self._mock_runner is not None:
            return True
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=3.0,
                text=True,
            )
            return res.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    def build_docker_command(
        self,
        script_path: Path,
        container_name: str | None = None,
        work_dir: Path | None = None,
    ) -> list[str]:
        """Construct the hardened Docker execution command with all security constraints."""
        cname = container_name or f"lcb-sandbox-{uuid4().hex[:12]}"
        cmd = [
            "docker", "run", "--rm",
            "--name", cname,
            "-i",
            "--network", "none",
            "--memory", self.config.memory_limit,
            "--cpus", self.config.cpu_limit,
            "--pids-limit", str(self.config.pids_limit),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
        ]
        if self.config.read_only_rootfs:
            cmd.extend(["--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])
        app_dir = (work_dir or script_path.parent).resolve().as_posix()
        cmd.extend([
            "--user", "65534:65534",
            "-v", f"{app_dir}:/app:ro",
            "-w", "/app",
            self.config.image,
            "python", "-u", f"/app/{script_path.name}",
        ])
        return cmd

    def execute_code(
        self,
        code_to_run: str,
        test_code: str,
        *,
        scratch_dir: Path | None = None,
    ) -> SandboxExecutionResult:
        """
        Execute candidate code along with verification tests inside an isolated container.
        FAILS CLOSED if sandbox is unavailable.
        """
        if self._mock_runner is not None:
            return self._mock_runner(code_to_run, test_code)

        if not self.is_sandbox_available():
            raise SandboxUnavailableError(
                "Container sandbox is unavailable (Docker daemon not running). "
                "Execution of untrusted model code on host is strictly prohibited."
            )

        temp_dir = scratch_dir or Path(f".tmp_sandbox_{uuid4().hex[:12]}")
        temp_dir.mkdir(parents=True, exist_ok=True)
        solution_file = temp_dir / "solution.py"
        solution_file.write_text(code_to_run, encoding="utf-8")
        runner_file = temp_dir / "runner.py"
        runner_file.write_text(test_code, encoding="utf-8")

        container_name = f"lcb-sandbox-{uuid4().hex[:12]}"
        docker_cmd = self.build_docker_command(runner_file, container_name=container_name, work_dir=temp_dir)

        t0 = time.monotonic()
        try:
            res = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                text=True,
            )
            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            passed = res.returncode == 0
            status = "passed" if passed else "failed"
            return SandboxExecutionResult(
                success=passed,
                status=status,
                exit_code=res.returncode,
                stdout=res.stdout[:4000],
                stderr=res.stderr[:4000],
                duration_ms=duration_ms,
                error_code="VERIFIER_TEST_FAILED" if not passed else None,
            )
        except subprocess.TimeoutExpired:
            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            # Ensure outer-process timeouts do not leave untracked containers running
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    timeout=5.0,
                )
            except Exception:
                pass
            return SandboxExecutionResult(
                success=False,
                status="timed_out",
                exit_code=-1,
                stdout="",
                stderr=f"Solution timed out after {self.config.timeout_seconds}s",
                duration_ms=duration_ms,
                error_code="VERIFIER_TIMEOUT",
                error_detail=f"Execution exceeded budget {self.config.timeout_seconds}s",
            )
        except Exception as exc:
            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            return SandboxExecutionResult(
                success=False,
                status="error",
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
                error_code="VERIFIER_SANDBOX_ERROR",
                error_detail=str(exc),
            )
        finally:
            if scratch_dir is None:
                shutil.rmtree(temp_dir, ignore_errors=True)
