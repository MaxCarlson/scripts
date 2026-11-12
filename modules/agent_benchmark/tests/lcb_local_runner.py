"""TEST-ONLY local candidate runner (never imported by production code).

Mirrors the container file layout: a throw-away directory holding only ``solution.py`` (and the
fixed ``worker.py`` for call-based problems). Hidden expected outputs live only in the test
process memory and are never written here. Used to exercise host-side orchestration logic where
Docker is unavailable; real isolation guarantees are asserted by the Docker-gated test.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from agent_benchmark.execution.container_verify import CANDIDATE_WORKER_SOURCE, SandboxExecutionResult


def run_candidate_locally(code: str, stdin_text: str, fn_name: str | None) -> SandboxExecutionResult:
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH") if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="lcb_local_") as td:
        tdp = Path(td)
        (tdp / "solution.py").write_text(code, encoding="utf-8")
        if fn_name:
            (tdp / "worker.py").write_text(CANDIDATE_WORKER_SOURCE, encoding="utf-8")
            argv = [sys.executable, "-u", str(tdp / "worker.py"), fn_name]
        else:
            argv = [sys.executable, "-u", str(tdp / "solution.py")]
        t0 = time.monotonic()
        try:
            res = subprocess.run(
                argv, input=stdin_text, capture_output=True, text=True, timeout=10.0, cwd=td, env=env,
            )
        except subprocess.TimeoutExpired:
            return SandboxExecutionResult(
                False, "timed_out", -1, "", "timeout", round((time.monotonic() - t0) * 1000, 2),
                error_code="VERIFIER_TIMEOUT",
            )
        return SandboxExecutionResult(
            success=res.returncode == 0,
            status="passed" if res.returncode == 0 else "failed",
            exit_code=res.returncode,
            stdout=res.stdout,
            stderr=res.stderr,
            duration_ms=round((time.monotonic() - t0) * 1000, 2),
        )
