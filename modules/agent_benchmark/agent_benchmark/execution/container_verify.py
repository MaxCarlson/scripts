"""Secure containerized candidate execution for untrusted model-generated code.

Trust boundary
--------------
The *host* process is the only authority for pass/fail. Each test case is executed in its
own throw-away, network-less, read-only container that receives:

* ``solution.py`` (the submitted code),
* ``worker.py`` (a fixed, secret-free adapter used only for call-based problems),
* the single test *input* on stdin.

Expected outputs, hidden tests and verdict logic never enter the contestant's filesystem,
environment, or process namespace. The host never imports or executes contestant code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any
from uuid import uuid4

from ..sandbox_image import LCB_SANDBOX_IMAGE_REF


class SandboxUnavailableError(RuntimeError):
    """Raised when the container sandbox (Docker daemon or pinned image) is unavailable."""


@dataclass(frozen=True)
class SandboxConfig:
    """Security and resource limits for running untrusted model-generated code."""

    image: str = LCB_SANDBOX_IMAGE_REF
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
    """Outcome of running one candidate execution inside the container sandbox."""

    success: bool
    status: str  # "passed" | "failed" | "timed_out" | "error"
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    error_code: str | None = None
    error_detail: str | None = None


# Fixed, trusted adapter for call-based problems. Contains NO test data and NO secrets.
# Reads JSON argument list on stdin, calls the target, and emits one JSON record as the last
# stdout line. Contestant prints are diverted to stderr. Verdicts are computed by the host.
CANDIDATE_WORKER_SOURCE = '''\
import json
import os
import sys

_out = sys.stdout


def _emit(obj):
    _out.write("\\n" + json.dumps(obj, default=str) + "\\n")
    _out.flush()


def _main():
    fn = sys.argv[1]
    args = json.loads(sys.stdin.read())
    sys.stdout = sys.stderr
    sys.path.insert(0, os.getcwd())
    import solution
    target = None
    if hasattr(solution, "Solution"):
        target = getattr(solution.Solution(), fn, None)
    if target is None:
        target = getattr(solution, fn, None)
    if target is None:
        return {"error": "function_not_found"}
    res = target(*args)
    if isinstance(res, tuple):
        res = list(res)
    return {"result": res}


try:
    _rec = _main()
except SystemExit:
    _rec = {"error": "premature_exit"}
except BaseException as _exc:
    _rec = {"error": "exception: " + repr(_exc)[:300]}
sys.stdout = _out
_emit(_rec)
os._exit(0 if "result" in _rec else 1)
'''


class ContainerVerifier:
    """
    Executes untrusted code within an isolated container sandbox, one test input at a time.
    Fails closed if the container engine or the pinned image is unavailable; NEVER executes
    untrusted code on the host.

    ``mock_runner`` (tests only) replaces the Docker invocation. Its signature is
    ``(code: str, stdin_text: str, fn_name: str | None) -> SandboxExecutionResult``.
    """

    def __init__(
        self,
        config: SandboxConfig | None = None,
        *,
        mock_runner: Any = None,
    ) -> None:
        self.config = config or SandboxConfig()
        self._mock_runner = mock_runner
        self._preflight_ok = False

    # ------------------------------------------------------------------ availability
    def is_sandbox_available(self) -> bool:
        """Check whether the Docker container daemon is reachable without starting it."""
        if self._mock_runner is not None:
            return True
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5.0,
                text=True,
            )
            return res.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    def is_image_available(self) -> bool:
        """Check that exactly the configured (digest-pinned) image is present locally."""
        if self._mock_runner is not None:
            return True
        try:
            res = subprocess.run(
                ["docker", "image", "inspect", self.config.image, "--format", "{{.Id}}"],
                capture_output=True,
                timeout=10.0,
                text=True,
            )
            return res.returncode == 0 and bool(res.stdout.strip())
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    def _preflight(self, *, force: bool = False) -> None:
        if self._mock_runner is not None:
            return
        if self._preflight_ok and not force:
            return
        if not self.is_sandbox_available():
            self._preflight_ok = False
            raise SandboxUnavailableError(
                "Container sandbox is unavailable (Docker daemon not running). "
                "Execution of untrusted model code on host is strictly prohibited."
            )
        if not self.is_image_available():
            self._preflight_ok = False
            raise SandboxUnavailableError(
                f"Required verifier image {self.config.image} is not present in the local Docker daemon. "
                f"Pull it explicitly (docker pull {self.config.image}); untrusted code is never run on the host."
            )
        self._preflight_ok = True

    # ------------------------------------------------------------------ command
    def build_docker_command(
        self,
        entry_path: Path,
        container_name: str | None = None,
        work_dir: Path | None = None,
        entry_args: tuple[str, ...] = (),
    ) -> list[str]:
        """Construct the hardened Docker command. Only ``work_dir`` is mounted (read-only)."""
        cname = container_name or f"lcb-sandbox-{uuid4().hex[:12]}"
        cmd = [
            "docker", "run", "--rm",
            "--pull", "never",
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
        app_dir = (work_dir or entry_path.parent).resolve().as_posix()
        cmd.extend([
            "--user", "65534:65534",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-v", f"{app_dir}:/app:ro",
            "-w", "/app",
            self.config.image,
            "python", "-u", f"/app/{entry_path.name}", *entry_args,
        ])
        return cmd

    # ------------------------------------------------------------------ execution
    def run_candidate(
        self,
        code: str,
        stdin_text: str,
        *,
        fn_name: str | None = None,
    ) -> SandboxExecutionResult:
        """
        Run submitted ``code`` against ONE test input inside a fresh container.

        ``fn_name`` selects call-based mode (worker adapter, JSON args on stdin); otherwise the
        solution is executed as a stdin/stdout program. Returns raw execution evidence only;
        the caller (host) decides pass/fail by comparing against private expected outputs.
        """
        if self._mock_runner is not None:
            return self._mock_runner(code, stdin_text, fn_name)

        self._preflight()

        temp_dir = Path(tempfile.mkdtemp(prefix="lcb_cand_"))
        try:
            (temp_dir / "solution.py").write_text(code, encoding="utf-8")
            if fn_name:
                (temp_dir / "worker.py").write_text(CANDIDATE_WORKER_SOURCE, encoding="utf-8")
                entry = temp_dir / "worker.py"
                entry_args: tuple[str, ...] = (fn_name,)
            else:
                entry = temp_dir / "solution.py"
                entry_args = ()

            container_name = f"lcb-sandbox-{uuid4().hex[:12]}"
            docker_cmd = self.build_docker_command(
                entry, container_name=container_name, work_dir=temp_dir, entry_args=entry_args
            )

            t0 = time.monotonic()
            try:
                res = subprocess.run(
                    docker_cmd,
                    input=stdin_text,
                    capture_output=True,
                    timeout=self.config.timeout_seconds,
                    text=True,
                    errors="replace",
                )
            except subprocess.TimeoutExpired:
                duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
                self._force_remove(container_name)
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
                self._force_remove(container_name)
                return SandboxExecutionResult(
                    success=False,
                    status="error",
                    exit_code=-1,
                    stdout="",
                    stderr=str(exc),
                    duration_ms=round((time.monotonic() - t0) * 1000.0, 2),
                    error_code="VERIFIER_SANDBOX_ERROR",
                    error_detail=str(exc),
                )

            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)

            # Docker-level failures use 125-127. A contestant can also exit with those codes, so
            # only classify as infrastructure when the daemon/image check now fails.
            if res.returncode in (125, 126, 127) and (res.stderr or "").lstrip().startswith("docker:"):
                try:
                    self._preflight(force=True)
                except SandboxUnavailableError as exc:
                    return SandboxExecutionResult(
                        success=False,
                        status="error",
                        exit_code=res.returncode,
                        stdout="",
                        stderr=(res.stderr or "")[:2000],
                        duration_ms=duration_ms,
                        error_code="VERIFIER_SANDBOX_ERROR",
                        error_detail=str(exc),
                    )

            return SandboxExecutionResult(
                success=res.returncode == 0,
                status="passed" if res.returncode == 0 else "failed",
                exit_code=res.returncode,
                stdout=(res.stdout or "")[:200_000],
                stderr=(res.stderr or "")[:4000],
                duration_ms=duration_ms,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _force_remove(container_name: str) -> None:
        """Ensure outer-process timeouts/errors never leave untracked containers running."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10.0,
            )
        except Exception:
            pass
