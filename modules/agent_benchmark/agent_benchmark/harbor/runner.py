"""Controlled subprocess execution for Harbor benchmark evaluations."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from uuid import uuid4

import json
import logging
import sys

try:
    from ..state import command_lock
except ImportError:
    command_lock = None  # type: ignore[assignment]
from .importer import HarborImporter
from .models import HarborJobResult, JobStats
from .planner import BenchmarkPlan, check_docker_readiness, check_harbor_readiness

logger = logging.getLogger(__name__)


def find_harbor_opencode_adapters() -> list[Path]:
    """Find installed or cached Harbor opencode adapter script paths."""
    candidates: list[Path] = []
    uv_cache = os.environ.get("UV_CACHE_DIR")
    if uv_cache and os.path.isdir(uv_cache):
        candidates.append(Path(uv_cache))
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "uv" / "cache")
    else:
        candidates.append(Path.home() / ".cache" / "uv")

    try:
        import site
        for sp in site.getsitepackages():
            candidates.append(Path(sp))
    except Exception:
        pass
    candidates.append(Path(sys.prefix))

    found: set[Path] = set()
    for base in candidates:
        if base.is_dir():
            try:
                for p in base.glob("**/harbor/agents/installed/opencode.py"):
                    found.add(p.resolve())
            except Exception:
                pass
    return sorted(found)


def ensure_harbor_opencode_compatibility(adapter_paths: list[Path] | None = None) -> list[Path]:
    """Ensure installed or cached Harbor OpenCode adapters do not crash with EPIPE on non-git repos.

    Harbor 0.25.0 unconditionally sets OPENCODE_FAKE_VCS="git" on agent execution.
    In benchmark environments where the workspace is not a git repository (such as
    Aider Polyglot benchmark tasks), OpenCode 1.19.5's internal git operations fail
    with exit 128 (fatal: not a git repository). The abrupt closure of git's stream
    triggers an unhandled EPIPE exception in Node/Bun stream lifecycle on stdout write,
    scheduling process exit code 1 (NonZeroAgentExitCodeError) even when all agent steps
    succeed.

    This function searches the uv cache and Python environment for
    harbor/agents/installed/opencode.py and ensures OPENCODE_FAKE_VCS is only set
    if explicitly passed in the environment.
    """
    targets = adapter_paths if adapter_paths is not None else find_harbor_opencode_adapters()
    patched: list[Path] = []
    target_needle = 'env["OPENCODE_FAKE_VCS"] = "git"'
    replacement = (
        '        # Compatibility fix for issue #4019 (uncaught EPIPE broken pipe crash):\n'
        '        # Do not force OPENCODE_FAKE_VCS="git" on non-git directories.\n'
        '        if os.environ.get("OPENCODE_FAKE_VCS"):\n'
        '            env["OPENCODE_FAKE_VCS"] = os.environ["OPENCODE_FAKE_VCS"]'
    )
    for path in targets:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            needs_patch = target_needle in content
            needs_import_os = "import os" not in content
            modified = False
            if needs_patch:
                content = content.replace(target_needle, replacement)
                modified = True
            if needs_import_os and (needs_patch or 'if os.environ.get("OPENCODE_FAKE_VCS"):' in content):
                content = "import os\n" + content
                modified = True
            if modified:
                path.write_text(content, encoding="utf-8")
                patched.append(path)
                logger.info("Patched Harbor OpenCode adapter for non-git compatibility: %s", path)
        except Exception as exc:
            logger.warning("Could not patch Harbor OpenCode adapter %s: %s", path, exc)
    return patched


class ExecutionAuthorizationError(RuntimeError):
    """Raised when execution is attempted without explicit -x/--execute authorization."""


class PreflightCheckError(RuntimeError):
    """Raised when environment prerequisites (Docker, Harbor) fail."""


def build_harbor_command(
    plan: BenchmarkPlan,
    *,
    jobs_dir: Path,
    job_name: str | None = None,
    n_concurrent: int = 1,
    max_retries: int = 0,
    quiet: bool = False,
    registry_path: Path | None = None,
) -> list[str]:
    """Build an exact subprocess argument list for harbor run (no shell interpolation)."""
    # Prefer native harbor executable, fallback to uv tool run
    if shutil.which("harbor"):
        cmd = ["harbor", "run"]
    elif shutil.which("uv"):
        cmd = ["uv", "tool", "run", "--from", "harbor==0.25.0", "harbor", "run"]
    else:
        raise PreflightCheckError("Neither 'harbor' nor 'uv' CLI binary is available on PATH")

    harbor_ds = plan.dataset.harbor_dataset
    if not harbor_ds:
        raise ValueError(f"Dataset {plan.dataset.id!r} has no Harbor registry identity")
    cmd.extend(["--dataset", harbor_ds])
    if registry_path is not None:
        cmd.extend(["--registry-path", str(registry_path.resolve())])
    agent_arg = (
        "agent_benchmark.harbor.opencode_v2:OpenCodeV2"
        if plan.agent == "opencode-v2"
        else plan.agent
    )
    cmd.extend(["--agent", agent_arg])
    if plan.model and plan.model not in ("default", "none") and plan.agent not in ("oracle", "nop"):
        cmd.extend(["--model", plan.model])

    if plan.base_url and plan.agent not in ("oracle", "nop"):
        cmd.extend(["--base-url", plan.base_url])

    if plan.model_api_format and plan.agent not in ("oracle", "nop"):
        cmd.extend(["--api-format", plan.model_api_format])

    for task_id in plan.selected_tasks:
        cmd.extend(["--include-task-name", task_id])

    cmd.extend(["--n-attempts", str(plan.repetitions)])
    cmd.extend(["--n-concurrent", str(n_concurrent)])
    cmd.extend(["--max-retries", str(max_retries)])
    cmd.extend(["--jobs-dir", str(jobs_dir)])

    if job_name:
        cmd.extend(["--job-name", job_name])

    if quiet:
        cmd.append("--quiet")

    return cmd


def execute_harbor_run(
    plan: BenchmarkPlan,
    *,
    execute: bool,
    output_dir: Path,
    jobs_dir: Path = Path(".harbor-jobs"),
    state_dir: Path | None = None,
    n_concurrent: int = 1,
    quiet: bool = False,
    registry_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Execute a planned Harbor benchmark under explicit authorization and import results.

    Requirements:
    - execute must be True (-x/--execute)
    - Docker daemon must be active (fails closed if unreachable)
    - Reconciles receipts and holds command lock
    """
    if not execute:
        raise ExecutionAuthorizationError(
            "Benchmark execution refused without -x/--execute authorization. "
            "Use 'agent-bench external plan' to inspect without execution."
        )

    # Preflight 0: Blockers
    if not plan.readiness.is_runnable:
        raise PreflightCheckError(
            f"Cannot execute benchmark due to readiness blockers: {"; ".join(plan.readiness.blockers)}"
        )

    # Preflight 1: Docker
    docker_ok, docker_msg = check_docker_readiness()
    if not docker_ok:
        raise PreflightCheckError(
            f"Cannot run external benchmark without container isolation: {docker_msg}"
        )

    # Preflight 2: Harbor / uv
    harbor_ok, _ = check_harbor_readiness()
    if not harbor_ok:
        raise PreflightCheckError("Harbor runner is not installed and uv is not available")

    resolved_jobs_dir = jobs_dir.resolve()
    resolved_jobs_dir.mkdir(parents=True, exist_ok=True)
    resolved_output_dir = output_dir.resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    state = (state_dir or (Path.home() / ".local/share/agent-benchmark")).resolve()
    state.mkdir(parents=True, exist_ok=True)

    # Generate explicit, unique job name to eliminate race conditions
    job_name = f"harbor_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    job_dir = resolved_jobs_dir / job_name

    cmd = build_harbor_command(
        plan,
        jobs_dir=resolved_jobs_dir,
        job_name=job_name,
        n_concurrent=n_concurrent,
        max_retries=0,
        quiet=quiet,
        registry_path=registry_path,
    )

    run_env = os.environ.copy()
    if os.name == "nt":
        run_env["PYTHONUTF8"] = "1"
        run_env["PYTHONIOENCODING"] = "utf-8"
    if plan.agent in ("qwen-coder", "opencode", "opencode-v2") and "OPENAI_API_KEY" not in run_env:
        run_env["OPENAI_API_KEY"] = "lm-studio"
    if plan.agent == "opencode-v2":
        agent_bench_root = str(Path(__file__).resolve().parent.parent.parent)
        current_pythonpath = run_env.get("PYTHONPATH", "")
        run_env["PYTHONPATH"] = (
            f"{agent_bench_root}{os.pathsep}{current_pythonpath}"
            if current_pythonpath
            else agent_bench_root
        )

    if plan.agent == "opencode":
        ensure_harbor_opencode_compatibility()

    lock_cm = command_lock
    if lock_cm is None:
        from ..state import command_lock as lock_cm

    with lock_cm(state):
        try:
            # Execute Harbor subprocess
            proc = subprocess.run(
                cmd,
                env=run_env,
                text=True,
                capture_output=False,  # Stream output to terminal for transparency
            )
        except (KeyboardInterrupt, Exception) as exc:
            raise RuntimeError(f"Harbor run interrupted or aborted: {exc}") from exc

    # Validate that job directory exists
    if not job_dir.is_dir():
        raise RuntimeError(
            f"Harbor evaluation process failed with exit code {proc.returncode} and produced no job directory: {job_dir}"
            if proc.returncode != 0
            else f"Harbor job directory was not created: {job_dir}"
        )

    result_file = job_dir / "result.json"
    if not result_file.is_file():
        raise RuntimeError(
            f"Harbor evaluation process failed with exit code {proc.returncode} and produced no result.json in {job_dir}"
            if proc.returncode != 0
            else f"No result.json was produced in {job_dir}"
        )

    # If Harbor exited with a nonzero returncode, inspect the result artifact before accepting
    if proc.returncode != 0:
        try:
            job_data = json.loads(result_file.read_text(encoding="utf-8", errors="replace"))
            job_res = HarborJobResult.model_validate(job_data)
        except Exception as exc:
            raise RuntimeError(
                f"Harbor evaluation process failed with exit code {proc.returncode} "
                f"and produced an unparseable result.json: {exc}"
            ) from exc

        actual_trials = len(job_res.trial_results)
        expected_trials = plan.projected_trials
        pending_trials = 0
        running_trials = 0
        if isinstance(job_res.stats, JobStats):
            pending_trials = job_res.stats.n_pending_trials
            running_trials = job_res.stats.n_running_trials
        elif isinstance(job_res.stats, dict):
            pending_trials = job_res.stats.get("n_pending_trials", 0)
            running_trials = job_res.stats.get("n_running_trials", 0)

        if actual_trials < expected_trials or pending_trials > 0 or running_trials > 0:
            raise RuntimeError(
                f"Harbor evaluation process failed with exit code {proc.returncode} "
                f"leaving job incomplete ({actual_trials}/{expected_trials} trials recorded, "
                f"{pending_trials} pending, {running_trials} running)"
            )

        logger.warning(
            "Harbor evaluation process exited with nonzero code %d, but all %d projected trials completed.",
            proc.returncode,
            expected_trials,
        )

    # Import the job artifacts
    importer = HarborImporter(job_dir)
    target_dir = resolved_output_dir / job_dir.name
    saved_dir, summary = importer.import_to(target_dir, process_returncode=proc.returncode)

    return saved_dir, summary
