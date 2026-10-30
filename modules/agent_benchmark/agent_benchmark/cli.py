"""Explicitly authorized benchmark CLI; plan/status/cleanup preview are read-only."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import inspect
import json
import logging
import math
import os
from pathlib import Path
import sys
from typing import Any

from benchmark_core import (
    ExperimentConfig,
    TrialResult,
    format_utc_timestamp,
    generate_experiment_reports,
    load_experiment,
    load_run,
    render_experiment_comparison_md,
)
import httpx
from termdash import Table

from . import __version__
from .dashboard import ExperimentDashboard
from .diagnostic import run_diagnostic
from .evidence import EVIDENCE_LIMITS, load_task
from .identity import get_effective_lmstudio_model_ids, model_readiness
from .inference_profile import load_inference_profile, validate_context_match
from .instruction_overlay import load_instruction_append
from .logging_setup import close_run_logging, configure_run_logging
from .models_lifecycle import (
    DEFAULT_BENCHMARK_CONTEXT_LENGTH,
    get_loaded_models,
    list_codex_models,
    list_downloaded_models,
    list_gemini_models,
    resolve_model_provider_and_key,
)
from .runner import BUDGET_PROFILES, cleanup_trial, run_benchmark
from .scheduler import ExperimentScheduler, expand_experiment_plan
from .scratch import SCOPE_POLICY, SCRATCH_NAME
from .state import read_pending

logger = logging.getLogger(__name__)


def positive(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Timeouts/budgets must be finite and positive")
    return result


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Context length must be a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("Context length must be a positive integer")
    return result


def ram_percent(value: str) -> float:
    try:
        result = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("RAM percentage must be a number from 0 (exclusive) to 100") from error
    if not math.isfinite(result) or not 0 < result <= 100:
        raise argparse.ArgumentTypeError("RAM percentage must be greater than 0 and at most 100")
    return result


def _resolve_tasks(task_args: list[Path] | None) -> dict[str, Path]:
    """Resolve task paths or names into a dictionary of {task_id: Path}."""
    builtin_tasks_dir = Path(__file__).parent / "tasks"
    if not task_args:
        task_dirs: dict[str, Path] = {}
        if builtin_tasks_dir.is_dir():
            for child in sorted(builtin_tasks_dir.iterdir()):
                if child.is_dir() and (child / "task.json").is_file():
                    task_dirs[child.name] = child
        if not task_dirs and (builtin_tasks_dir / "py-grep-smoke").is_dir():
            task_dirs["py-grep-smoke"] = builtin_tasks_dir / "py-grep-smoke"
        return task_dirs

    task_dirs = {}
    for item in task_args:
        p = Path(item)
        if not p.exists():
            candidate = builtin_tasks_dir / p
            if candidate.exists():
                p = candidate

        if p.is_dir() and (p / "task.json").is_file():
            task = load_task(p)
            task_dirs[task.task_id] = p
        elif p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_dir() and (child / "task.json").is_file():
                    t = load_task(child)
                    task_dirs[t.task_id] = child
        elif p.is_file() and p.name == "task.json":
            task = load_task(p.parent)
            task_dirs[task.task_id] = p.parent
        else:
            raise ValueError(f"Task path not found or missing task.json: {item}")
    return task_dirs


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="agent-bench",
        description="Independently verify first-attempt local coding work and multi-model benchmark experiments",
    )
    root.add_argument("-V", "--version", action="version", version=__version__)
    actions = root.add_subparsers(dest="command")

    # 1. Existing single-run commands
    for name in ("plan", "run", "status", "cleanup", "smoke"):
        action = actions.add_parser(name)
        action.add_argument(
            "-s",
            "--state-dir",
            type=Path,
            default=Path.home() / ".local/share/agent-benchmark",
            help="Persistent dispatch receipts, shared across output locations",
        )
        if name in ("plan", "run"):
            action.add_argument(
                "-t",
                "--task",
                type=Path,
                default=Path(__file__).parent / "tasks/py-grep-smoke",
            )
            action.add_argument(
                "-B",
                "--budget-profile",
                choices=tuple(BUDGET_PROFILES.keys()),
                default="canonical-120s",
                help="Reproducible budget profile (default: canonical-120s)",
            )
        if name in ("status", "cleanup"):
            action.add_argument("-r", "--run-dir", type=Path)
        if name in ("run", "cleanup", "smoke"):
            action.add_argument(
                "-x",
                "--execute",
                action="store_true",
                help="Authorize execution (required for run/smoke; cleanup otherwise previews)",
            )
            action.add_argument("-u", "--base-url", default="http://127.0.0.1:4096")
            if name != "smoke":
                action.add_argument("-g", "--cancel-grace", type=positive, default=10)
            action.add_argument("-q", "--request-timeout", type=positive, default=10)
        if name in ("run", "smoke"):
            action.add_argument("-m", "--model", required=True)
            action.add_argument("-p", "--provider", default="lmstudio")
            action.add_argument(
                "-a",
                "--agent",
                choices=(
                    ("local-worker", "local-reviewer")
                    if name == "run"
                    else ("local-worker",)
                ),
                default="local-worker",
            )
            action.add_argument(
                "-o",
                "--output-dir",
                type=Path,
                default=Path("reports" if name == "run" else "integration-acceptance"),
            )
            if name == "run":
                action.add_argument("-b", "--budget", type=positive)
                action.add_argument(
                    "-v", "--verifier-timeout", type=positive, default=10
                )

    # 2. Model inventory command
    models_p = actions.add_parser(
        "models", help="Inspect local model inventory and loaded states"
    )
    models_actions = models_p.add_subparsers(dest="models_command")
    models_list = models_actions.add_parser(
        "list", help="List available models across LM Studio, Gemini (via agy), and Codex"
    )
    models_list.add_argument(
        "-p",
        "--provider",
        choices=("all", "lmstudio", "gemini", "codex"),
        default="all",
        help="Filter models by provider (default: all)",
    )
    models_list.add_argument("-u", "--base-url", default="http://127.0.0.1:1234")
    models_list.add_argument("--format", choices=("table", "json"), default="table")

    # 3. Multi-model experiment command
    exp_p = actions.add_parser(
        "experiment",
        help="Multi-model batch experimentation, planning, and reporting",
    )
    exp_actions = exp_p.add_subparsers(dest="experiment_command")

    # experiment plan
    exp_plan = exp_actions.add_parser(
        "plan", help="Dry-run plan for multi-model experiment"
    )
    exp_plan.add_argument(
        "-m",
        "--model",
        action="append",
        required=True,
        help="Model key (repeatable)",
    )
    exp_plan.add_argument(
        "-t",
        "--task",
        action="append",
        type=Path,
        help="Task path or name (repeatable)",
    )
    exp_plan.add_argument(
        "-r",
        "--repetitions",
        type=int,
        default=1,
        help="Repetitions per task/model (default: 1)",
    )
    exp_plan.add_argument(
        "-b",
        "--budget-profile",
        choices=tuple(BUDGET_PROFILES.keys()),
        default="canonical-120s",
    )
    exp_plan.add_argument("-c", "--context-length", type=positive_int, default=DEFAULT_BENCHMARK_CONTEXT_LENGTH,
                          help="Shared LM Studio context cap for all local models (default: 16384)")
    exp_plan.add_argument("-I", "--inference-profile", type=Path,
                          help="Validated per-trial OpenCode context/output/reasoning settings JSON")
    exp_plan.add_argument("-A", "--instruction-append-file", type=Path,
                          help="Append a UTF-8 task-instruction variant; record its path and SHA-256")
    exp_plan.add_argument("-u", "--base-url", default="http://127.0.0.1:4096")
    exp_plan.add_argument("--random-seed", type=int, default=None)
    exp_plan.add_argument(
        "-s",
        "--state-dir",
        type=Path,
        default=Path.home() / ".local/share/agent-benchmark",
    )
    exp_plan.add_argument("-e", "--experiment-dir", type=Path)

    # experiment run
    exp_run = exp_actions.add_parser(
        "run", help="Execute multi-model experiment sequentially"
    )
    exp_run.add_argument(
        "-x",
        "--execute",
        action="store_true",
        help="Authorize execution (required)",
    )
    exp_run.add_argument(
        "-m",
        "--model",
        action="append",
        required=True,
        help="Model key (repeatable)",
    )
    exp_run.add_argument(
        "-t",
        "--task",
        action="append",
        type=Path,
        help="Task path or name (repeatable)",
    )
    exp_run.add_argument(
        "-r",
        "--repetitions",
        type=int,
        default=1,
        help="Repetitions per task/model (default: 1)",
    )
    exp_run.add_argument(
        "-b",
        "--budget-profile",
        choices=tuple(BUDGET_PROFILES.keys()),
        default="canonical-120s",
    )
    exp_run.add_argument("-c", "--context-length", type=positive_int, default=DEFAULT_BENCHMARK_CONTEXT_LENGTH,
                         help="Shared LM Studio context cap for all local models (default: 16384)")
    exp_run.add_argument("-I", "--inference-profile", type=Path,
                         help="Validated per-trial OpenCode context/output/reasoning settings JSON")
    exp_run.add_argument("-A", "--instruction-append-file", type=Path,
                         help="Append a UTF-8 task-instruction variant; record its path and SHA-256")
    exp_run.add_argument("-P", "--pause-before-dispatch", action="store_true",
                         help="Print the prepared OpenCode endpoint/project/session, then wait for monitor attachment")
    exp_run.add_argument("--tool-profile", choices=("file-tools-v1", "retrieval-files-v1", "retrieval-structural-v1"),
                         default=None, help="Apply one identical tool profile to every task (matched intervention runs)")
    exp_run.add_argument(
        "-M",
        "--max-ram-percent",
        type=ram_percent,
        default=None,
        help="Opt in to stopping local inference at this host RAM use percentage (default: no percentage limit)",
    )
    exp_run.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("reports/experiments"),
        help="Directory to write experiment outputs (default: reports/experiments)",
    )
    exp_run.add_argument(
        "-s",
        "--state-dir",
        type=Path,
        default=Path.home() / ".local/share/agent-benchmark",
    )
    exp_run.add_argument("-u", "--base-url", default="http://127.0.0.1:4096")
    exp_run.add_argument(
        "--allow-model-transitions",
        action="store_true",
        default=True,
        help="Allow LM Studio model transitions (default: True)",
    )
    exp_run.add_argument(
        "--no-allow-model-transitions",
        dest="allow_model_transitions",
        action="store_false",
    )
    exp_run.add_argument(
        "-Q",
        "--quiet",
        action="store_true",
        default=False,
        help="Quiet mode: suppress in-place live dashboard",
    )
    exp_run.add_argument(
        "--html",
        action="store_true",
        default=True,
        help="Generate standalone interactive HTML report (default: True)",
    )
    exp_run.add_argument("--random-seed", type=int, default=None)

    # experiment status
    exp_status = exp_actions.add_parser(
        "status", help="Check status of a running or completed experiment"
    )
    exp_status.add_argument(
        "-e",
        "--experiment-dir",
        type=Path,
        required=True,
        help="Path to experiment directory",
    )
    exp_status.add_argument(
        "--format", choices=("table", "json"), default="table"
    )

    # experiment report
    exp_report = exp_actions.add_parser(
        "report",
        help="Regenerate HTML/Markdown/CSV comparison reports from experiment artifacts",
    )
    exp_report.add_argument(
        "-e",
        "--experiment-dir",
        type=Path,
        required=True,
        help="Path to experiment directory",
    )
    exp_report.add_argument(
        "--html",
        action="store_true",
        default=True,
        help="Generate standalone interactive HTML report",
    )

    # 4. External Harbor benchmark command group
    ext_p = actions.add_parser(
        "external",
        help="External Harbor-based benchmark evaluation (Aider Polyglot, Terminal-Bench)",
    )
    ext_actions = ext_p.add_subparsers(dest="external_command")

    # external list
    ext_list = ext_actions.add_parser(
        "list", help="List supported external benchmark suites and readiness"
    )
    ext_list.add_argument(
        "--format", choices=("table", "json"), default="table", help="Output format (default: table)"
    )

    # external plan
    ext_plan = ext_actions.add_parser(
        "plan", help="Resolve tasks, configuration, and projected work without execution"
    )
    ext_plan.add_argument(
        "-d", "--dataset", default="aider-polyglot", help="Dataset identifier and version"
    )
    ext_plan.add_argument(
        "-a", "--agent", default="qwen-coder", help="Agent implementation (e.g. qwen-coder, codex, antigravity-cli, opencode, oracle)"
    )
    ext_plan.add_argument(
        "-m", "--model", default="qwen38_23GB", help="Exact model identifier"
    )
    ext_plan.add_argument(
        "-u", "--base-url", default="http://host.docker.internal:1234/v1", help="Inference API base URL for agent"
    )
    ext_plan.add_argument(
        "-t", "--task", action="append", help="Specific task ID (repeatable)"
    )
    ext_plan.add_argument(
        "-k", "--repetitions", type=int, default=1, help="Number of trials per task (default: 1)"
    )
    ext_plan.add_argument(
        "-s", "--seed", type=int, default=42, help="Deterministic task selection seed"
    )
    ext_plan.add_argument(
        "-n", "--count", type=int, default=None, help="Limit number of tasks"
    )
    ext_plan.add_argument(
        "--language", help="Filter tasks by language (e.g. python, cpp, go, java, javascript, rust)"
    )
    ext_plan.add_argument(
        "--format", choices=("table", "json"), default="table"
    )

    # external run
    ext_run = ext_actions.add_parser(
        "run", help="Execute a planned external benchmark under explicit authorization"
    )
    ext_run.add_argument(
        "-x", "--execute", action="store_true", help="Explicitly authorize execution (required)"
    )
    ext_run.add_argument(
        "-d", "--dataset", default="aider-polyglot", help="Dataset identifier and version"
    )
    ext_run.add_argument(
        "-a", "--agent", default="qwen-coder", help="Agent implementation"
    )
    ext_run.add_argument(
        "-m", "--model", default="qwen38_23GB", help="Exact model identifier"
    )
    ext_run.add_argument(
        "-u", "--base-url", default="http://host.docker.internal:1234/v1", help="Inference API base URL for agent"
    )
    ext_run.add_argument(
        "-t", "--task", action="append", help="Specific task ID (repeatable)"
    )
    ext_run.add_argument(
        "-k", "--repetitions", type=int, default=1, help="Number of trials per task (default: 1)"
    )
    ext_run.add_argument(
        "-s", "--seed", type=int, default=42, help="Deterministic task selection seed"
    )
    ext_run.add_argument(
        "-n", "--count", type=int, default=None, help="Limit number of tasks"
    )
    ext_run.add_argument(
        "--language", help="Filter tasks by language (e.g. python, cpp, go, java, javascript, rust)"
    )
    ext_run.add_argument(
        "-o", "--output-dir", type=Path, default=Path("reports/harbor"), help="Directory for imported results"
    )
    ext_run.add_argument(
        "--jobs-dir", type=Path, default=Path(".harbor-jobs"), help="Directory for native Harbor job outputs"
    )
    ext_run.add_argument(
        "-s-dir", "--state-dir", dest="state_dir", type=Path, default=Path.home() / ".local/share/agent-benchmark",
        help="State directory for locks and pending receipts"
    )
    ext_run.add_argument(
        "--format", choices=("table", "json"), default="table"
    )

    # external import
    ext_import = ext_actions.add_parser(
        "import", help="Import existing Harbor job results without running inference"
    )
    ext_import.add_argument(
        "-j",
        "--job-dir",
        type=Path,
        required=True,
        help="Harbor job directory containing result.json",
    )
    ext_import.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Destination directory for benchmark_core records (default: reports/harbor/<job_id>)",
    )
    ext_import.add_argument(
        "--format", choices=("table", "json"), default="table", help="Output format (default: table)"
    )

    # external report
    ext_report = ext_actions.add_parser(
        "report", help="Rebuild leaderboard and reports from imported results"
    )
    ext_report.add_argument(
        "-o", "--output-dir", type=Path, required=True, help="Directory containing imported benchmark_core results"
    )
    ext_report.add_argument(
        "--format", choices=("table", "json", "markdown"), default="table"
    )

    return root


def _handle_models(args: argparse.Namespace) -> int:
    cmd = getattr(args, "models_command", None) or "list"
    if cmd == "list":
        prov = getattr(args, "provider", "all") or "all"

        async def _fetch():
            downloaded, loaded, gemini_list, codex_list = [], [], [], []
            if prov in ("all", "lmstudio"):
                try:
                    res_d = list_downloaded_models()
                    if inspect.isawaitable(res_d):
                        res_d = await res_d
                    downloaded = res_d
                except Exception:
                    if prov == "lmstudio":
                        raise
                try:
                    res_l = get_loaded_models()
                    if inspect.isawaitable(res_l):
                        res_l = await res_l
                    loaded = res_l
                except Exception:
                    loaded = []

            if prov in ("all", "gemini"):
                res_g = list_gemini_models()
                if inspect.isawaitable(res_g):
                    res_g = await res_g
                gemini_list = res_g

            if prov in ("all", "codex"):
                res_c = list_codex_models()
                if inspect.isawaitable(res_c):
                    res_c = await res_c
                codex_list = res_c

            return downloaded, loaded, gemini_list, codex_list

        try:
            downloaded, loaded, gemini_list, codex_list = asyncio.run(_fetch())
        except Exception as exc:
            print(f"agent-bench: model discovery failed: {exc}", file=sys.stderr)
            return 1

        if args.format == "json":
            out = {
                "downloaded_models": [asdict(m) for m in downloaded],
                "loaded_models": [asdict(m) for m in loaded],
                "gemini_models": [asdict(m) for m in gemini_list],
                "codex_models": [asdict(m) for m in codex_list],
            }
            print(json.dumps(out, indent=2))
        else:
            if not downloaded and not gemini_list and not codex_list:
                print("No models found.")
                return 0
            tbl = Table(
                headers=["Model Key", "Architecture", "Quantization", "Status"],
                style="dash",
            )
            loaded_keys = {m.model_key for m in loaded}
            for m in downloaded:
                status_str = "LOADED (active)" if m.model_key in loaded_keys else "DOWNLOADED"
                tbl.add_row(
                    m.model_key,
                    m.architecture or "N/A",
                    m.quantization or "N/A",
                    status_str,
                )
            for m in gemini_list:
                tbl.add_row(
                    m.canonical_id,
                    m.architecture or "gemini",
                    "cloud-cli",
                    m.status,
                )
            for m in codex_list:
                tbl.add_row(
                    m.canonical_id,
                    m.architecture or "gpt",
                    "cloud-cli",
                    m.status,
                )
            print(tbl.render())
        return 0
    return 0


def _handle_experiment(args: argparse.Namespace, exp_parser: argparse.ArgumentParser) -> int:
    cmd = getattr(args, "experiment_command", None)
    if cmd is None:
        exp_parser.print_help()
        return 0

    if cmd == "plan":
        task_map = _resolve_tasks(args.task)
        models = args.model if isinstance(args.model, list) else [args.model]
        profile = load_inference_profile(args.inference_profile) if args.inference_profile else None
        instruction_append = load_instruction_append(args.instruction_append_file) if args.instruction_append_file else None
        if profile is not None:
            validate_context_match(profile, args.context_length)
            if any(resolve_model_provider_and_key(model)[0] != "lmstudio" for model in models):
                raise ValueError("OpenCode inference profiles can only be used with LM Studio models")
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        exp_id = f"EXP_{now_str}"

        config = ExperimentConfig(
            experiment_id=exp_id,
            created_at=format_utc_timestamp(),
            suite_id="agent-benchmark",
            suite_version=__version__,
            task_ids=sorted(task_map.keys()),
            variant_ids=models,
            repetitions=args.repetitions,
            scoring_basis="worker_first_attempt_full_success",
            budget_profile=args.budget_profile,
            random_seed=args.random_seed,
            metadata={"requested_context_length": args.context_length,
                      "requested_inference_profile": profile.to_dict() if profile else None,
                      "instruction_append": instruction_append.to_dict() if instruction_append else None},
        )
        plan = expand_experiment_plan(config, randomize_tasks=False)
        async def _readiness():
            try:
                inventory = await list_downloaded_models()
            except Exception:
                return [
                    {"requested_id": key, "status": "unknown",
                     "reason": "LM Studio inventory could not be read; plan is expanded but run readiness is unverified.",
                     "identity": None}
                    for key in models
                ]
            provider_state = await get_effective_lmstudio_model_ids(args.base_url, directory=Path.cwd())
            configured_ids, connected = provider_state if provider_state is not None else (None, None)
            rows = []
            for key in models:
                provider, model_id = resolve_model_provider_and_key(key)
                if provider == "lmstudio":
                    row = model_readiness(model_id, inventory, configured_ids, provider_connected=connected)
                    row["requested_context_length"] = args.context_length
                    identity = row.get("identity") or {}
                    maximum = identity.get("max_context_length", 0)
                    if identity and maximum and args.context_length > maximum:
                        row["status"] = "context_too_large"
                        row["reason"] = (f"Requested context {args.context_length} exceeds model maximum "
                                          f"{maximum}; reduce -c before running.")
                    elif identity and not maximum:
                        row["status"] = "context_limit_unknown"
                        row["reason"] = "LM Studio did not report this model's maximum context; run readiness is unknown."
                    if identity:
                        row["resource_preflight"] = "checked_before_load_at_run_time"
                    rows.append(row)
                else:
                    rows.append({"requested_id": key, "status": "not_checked",
                                 "reason": f"Provider '{provider}' uses its own CLI/runtime readiness checks.",
                                 "identity": {"provider": provider, "runtime_model_id": model_id}})
            return rows

        payload = plan.to_dict()
        payload["model_readiness"] = asyncio.run(_readiness())
        print(json.dumps(payload, indent=2))
        return 0

    elif cmd == "run":
        if not args.execute:
            print(
                "agent-bench: experiment run requires explicit -x/--execute authorization",
                file=sys.stderr,
            )
            return 2

        task_map = _resolve_tasks(args.task)
        if not task_map:
            print("agent-bench: no valid tasks found", file=sys.stderr)
            return 2

        models = args.model if isinstance(args.model, list) else [args.model]
        profile = load_inference_profile(args.inference_profile) if args.inference_profile else None
        instruction_append = load_instruction_append(args.instruction_append_file) if args.instruction_append_file else None
        if profile is not None:
            validate_context_match(profile, args.context_length)
            if any(resolve_model_provider_and_key(model)[0] != "lmstudio" for model in models):
                raise ValueError("OpenCode inference profiles can only be used with LM Studio models")
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        exp_id = f"EXP_{now_str}"

        config = ExperimentConfig(
            experiment_id=exp_id,
            created_at=format_utc_timestamp(),
            suite_id="agent-benchmark",
            suite_version=__version__,
            task_ids=sorted(task_map.keys()),
            variant_ids=models,
            repetitions=args.repetitions,
            scoring_basis="worker_first_attempt_full_success",
            budget_profile=args.budget_profile,
            random_seed=args.random_seed,
            metadata={"requested_context_length": args.context_length,
                      "runtime_max_ram_percent": args.max_ram_percent,
                      "requested_inference_profile": profile.to_dict() if profile else None,
                      "instruction_append": instruction_append.to_dict() if instruction_append else None},
        )

        plan = expand_experiment_plan(config, randomize_tasks=False)
        reports_base = Path(args.output_dir)
        reports_base.mkdir(parents=True, exist_ok=True)
        exp_dir = reports_base / exp_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        log_handler = configure_run_logging(exp_dir / "benchmark.log")
        logger.info(
            "Experiment starting id=%s models=%s tasks=%s repetitions=%s budget_profile=%s context_length=%s "
            "runtime_max_ram_percent=%s",
            exp_id, models, sorted(task_map), args.repetitions, args.budget_profile, args.context_length,
            args.max_ram_percent,
            extra={"event_type": "EXPERIMENT_START"},
        )

        try:
            dashboard = ExperimentDashboard(plan=plan, quiet=args.quiet)

            def before_dispatch(details: dict[str, Any]) -> None:
                print("MONITOR_SESSION_READY " + json.dumps(details, sort_keys=True), flush=True)
                input("Attach the read-only LLM Monitor observer, then press Enter to dispatch (Ctrl+C aborts): ")

            scheduler = ExperimentScheduler(
                plan=plan,
                task_dirs=task_map,
                reports_dir=reports_base,
                state_dir=args.state_dir,
                allow_model_transitions=args.allow_model_transitions,
                max_ram_percent=args.max_ram_percent,
                tool_profile=args.tool_profile,
                inference_profile=profile.to_dict() if profile else None,
                instruction_append=instruction_append,
                before_dispatch=before_dispatch if args.pause_before_dispatch else None,
                base_url=args.base_url,
                on_trial_start=dashboard.on_trial_start,
                on_trial_complete=dashboard.on_trial_complete,
                on_model_start=dashboard.on_model_start,
                on_model_complete=dashboard.on_model_complete,
                on_experiment_complete=dashboard.on_experiment_complete,
            )

            with dashboard:
                asyncio.run(scheduler.run())
        except BaseException:
            logger.exception("Experiment command failed id=%s", exp_id,
                             extra={"event_type": "EXPERIMENT_COMMAND_ERROR"})
            print(f"Diagnostic log: {exp_dir / 'benchmark.log'}", file=sys.stderr)
            raise
        finally:
            close_run_logging(log_handler)

        print(f"\nExperiment complete: {exp_dir}")
        print(f"Diagnostic log: {exp_dir / 'benchmark.log'}")

        all_trials = [t for _, t in scheduler.executed_trials]
        all_passed = bool(
            all_trials and all(t.status == "passed" for t in all_trials)
        )
        return 0 if all_passed else 1

    elif cmd == "status":
        exp_dir = Path(args.experiment_dir)
        loaded_exp, loaded_comp = load_experiment(exp_dir)

        if args.format == "json":
            out = {
                "experiment": loaded_exp.to_dict(),
                "comparison": loaded_comp.to_dict() if loaded_comp else None,
            }
            print(json.dumps(out, indent=2))
        else:
            print(f"Experiment ID: {loaded_exp.config.experiment_id}")
            print(f"Suite:         {loaded_exp.config.suite_id} (v{loaded_exp.config.suite_version})")
            print(f"Budget:        {loaded_exp.config.budget_profile}")
            print(f"Models:        {len(loaded_exp.config.variant_ids)} ({', '.join(loaded_exp.config.variant_ids)})")
            print(f"Runs:          {len(loaded_exp.run_refs)}")
            if loaded_comp:
                print("\n" + render_experiment_comparison_md(loaded_comp))
        return 0

    elif cmd == "report":
        exp_dir = Path(args.experiment_dir)
        loaded_exp, loaded_comp = load_experiment(exp_dir)

        # Collect trials across referenced constituent runs
        constituent_trials: list[TrialResult] = []
        for ref in loaded_exp.run_refs:
            run_p = (
                exp_dir.parent / ref.run_dir
                if not Path(ref.run_dir).is_absolute()
                else Path(ref.run_dir)
            )
            if run_p.exists():
                _, trs = load_run(run_p)
                constituent_trials.extend(trs)

        if loaded_comp is not None:
            generated = generate_experiment_reports(
                comparison=loaded_comp,
                trials=constituent_trials,
                output_dir=exp_dir,
                write=True,
            )
            print(f"Reports regenerated in {exp_dir}:")
            for fname in sorted(generated.keys()):
                print(f"  - {exp_dir / fname}")
        return 0

    return 0



def _handle_external(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    cmd = getattr(args, "external_command", None)
    if not cmd:
        parser.parse_args(["external", "--help"])
        return 0

    if cmd == "list":
        from .harbor import DATASETS, SUPPORTED_HARBOR_AGENTS, check_docker_readiness, check_harbor_readiness
        harbor_ok, harbor_ver = check_harbor_readiness()
        docker_ok, docker_msg = check_docker_readiness()

        suites_info = []
        seen_ids = set()
        for d_id, desc in DATASETS.items():
            if desc.id in seen_ids:
                continue
            seen_ids.add(desc.id)
            suites_info.append({
                "id": desc.id,
                "name": desc.name,
                "version": desc.version,
                "languages": list(desc.supported_languages),
                "total_tasks": len(desc.all_tasks),
                "scoring_protocol": desc.default_scoring_protocol,
            })

        agents_info = []
        for a_id, meta in SUPPORTED_HARBOR_AGENTS.items():
            agents_info.append({
                "agent": a_id,
                "description": meta["description"],
                "requires_model": meta["requires_model"],
                "requires_credentials": meta.get("requires_credentials", False),
            })

        payload = {
            "readiness": {
                "harbor_available": harbor_ok,
                "harbor_version": harbor_ver,
                "docker_available": docker_ok,
                "docker_status": docker_msg,
            },
            "datasets": suites_info,
            "supported_agents": agents_info,
        }

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(payload, indent=2))
        else:
            h_stat = "OK" if harbor_ok else "Missing"
            d_stat = "OK" if docker_ok else "Offline"
            print(f"\nExternal Evaluation Readiness (Harbor: {h_stat}, Docker: {d_stat}):")
            tbl = Table(
                headers=["Dataset", "Version", "Tasks", "Languages"],
                style="dash",
            )
            for d in suites_info:
                tbl.add_row(d["id"], d["version"], str(d["total_tasks"]), ", ".join(d["languages"]))
            print(tbl.render())
        return 0

    elif cmd == "plan":
        from .harbor import plan_benchmark
        try:
            plan = plan_benchmark(
                args.dataset,
                agent=args.agent,
                model=args.model,
                base_url=getattr(args, "base_url", None),
                task_ids=args.task,
                language=getattr(args, "language", None),
                count=getattr(args, "count", None),
                repetitions=args.repetitions,
                seed=args.seed,
            )
        except Exception as err:
            print(f"agent-bench: planning error: {err}", file=sys.stderr)
            return 2

        plan_dict = plan.to_dict()
        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(plan_dict, indent=2))
        else:
            status_text = "READY TO RUN" if plan.readiness.is_runnable else f"BLOCKED: {'; '.join(plan.readiness.blockers)}"
            print(f"\nExternal Benchmark Plan: {plan.dataset.name}")
            tbl = Table(headers=["Property", "Value"], style="dash")
            tbl.add_row("Dataset", f"{plan.dataset.id} ({plan.dataset.version})")
            tbl.add_row("Agent", plan.agent)
            tbl.add_row("Model", plan.model)
            if plan.base_url:
                tbl.add_row("Base URL", plan.base_url)
            tbl.add_row("Selected Tasks", str(len(plan.selected_tasks)))
            tbl.add_row("Repetitions", str(plan.repetitions))
            tbl.add_row("Total Projected Trials", str(plan.projected_trials))
            tbl.add_row("Scoring Protocol", plan.scoring_protocol)
            tbl.add_row("Harbor Available", "Yes" if plan.readiness.harbor_installed else "No")
            tbl.add_row("Docker Available", "Yes" if plan.readiness.docker_available else "No (Required for run)")
            tbl.add_row("Status", status_text)
            print(tbl.render())
        return 0 if plan.readiness.is_runnable else 1

    elif cmd == "run":
        from .harbor import plan_benchmark, execute_harbor_run
        try:
            plan = plan_benchmark(
                args.dataset,
                agent=args.agent,
                model=args.model,
                base_url=getattr(args, "base_url", None),
                task_ids=args.task,
                language=getattr(args, "language", None),
                count=getattr(args, "count", None),
                repetitions=args.repetitions,
                seed=args.seed,
            )
            saved_dir, summary = execute_harbor_run(
                plan,
                execute=args.execute,
                output_dir=args.output_dir,
                jobs_dir=args.jobs_dir,
                state_dir=getattr(args, "state_dir", None),
            )
        except Exception as err:
            print(f"agent-bench: {err}", file=sys.stderr)
            return 2

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(summary, indent=2))
        else:
            print(f"Results saved to: {saved_dir}")
        return 0 if summary.get("infrastructure_error", 0) == 0 else 1

    elif cmd == "import":
        from .harbor import HarborImporter
        try:
            importer = HarborImporter(args.job_dir)
            job_result, _, _ = importer.load_job()
            out_dir = args.output_dir or (Path("reports/harbor") / str(job_result.id))
            saved_dir, summary = importer.import_to(out_dir)
        except Exception as err:
            print(f"agent-bench: import error: {err}", file=sys.stderr)
            return 2

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(summary, indent=2))
        else:
            rate_str = f"{summary['pass_rate_pct']:.2f}%" if summary["scored"] > 0 else "N/A"
            print(f"\nHarbor Import: {summary['suite_id']} (Job {summary['job_id'][:8]})")
            tbl = Table(headers=["Metric", "Value"], style="dash")
            tbl.add_row("Scheduled trials", str(summary["scheduled"]))
            tbl.add_row("Completed trials", str(summary["completed"]))
            tbl.add_row("Valid scored trials", str(summary["scored"]))
            tbl.add_row("Passed trials", str(summary["passed"]))
            tbl.add_row("Failed trials", str(summary["failed"]))
            tbl.add_row("Timed out trials", str(summary["timed_out"]))
            tbl.add_row("Infrastructure errors", str(summary["infrastructure_error"]))
            tbl.add_row("Points earned", f"{summary['points_earned']:.2f}")
            tbl.add_row("Pass rate", rate_str)
            tbl.add_row("Coverage", f"{summary['coverage_pct']:.2f}%")
            tbl.add_row("Output directory", str(saved_dir))
            print(tbl.render())
        return 0 if summary.get("infrastructure_error", 0) == 0 else 1

    elif cmd == "report":
        from .harbor import collect_run_summaries, render_leaderboard_table
        summaries = collect_run_summaries(args.output_dir)

        fmt = getattr(args, "format", "table")
        if fmt == "json":
            print(json.dumps(summaries, indent=2))
        elif fmt == "markdown":
            print(render_leaderboard_table(summaries))
        else:
            if not summaries:
                print(f"No valid benchmark_core runs found in {args.output_dir}")
                return 0
            tbl = Table(
                headers=["Agent", "Model", "Benchmark", "Score", "Pass Rate", "Coverage", "Wall Time", "Errors", "Cost"],
                style="dash",
            )
            for s in sorted(summaries, key=lambda x: (-x["pass_rate_pct"], x["errors"])):
                time_str = f"{s['median_wall_ms'] / 1000.0:.1f}s" if s["median_wall_ms"] is not None else "N/A"
                cost_str = f"${s['total_cost_usd']:.4f}" if s["total_cost_usd"] is not None else "N/A"
                tbl.add_row(
                    s["agent"],
                    s["model"],
                    s["benchmark"],
                    s["score_display"],
                    f"{s['pass_rate_pct']:.1f}%",
                    f"{s['coverage_pct']:.1f}%",
                    time_str,
                    str(s["errors"]),
                    cost_str,
                )
            print("\nExternal Benchmark Leaderboard:")
            print(tbl.render())
        return 0
    return 0

def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.command is None:
        argument_parser.print_help()
        return 0

    if args.command in ("run", "smoke") and not args.execute:
        print(
            f"agent-bench: {args.command} requires explicit -x/--execute authorization",
            file=sys.stderr,
        )
        return 2

    try:
        if args.command == "external":
            return _handle_external(args, argument_parser)
        elif args.command == "models":
            return _handle_models(args)
        elif args.command == "experiment":
            return _handle_experiment(args, argument_parser)
        elif args.command == "plan":
            task = load_task(args.task)
            print(
                json.dumps(
                    {
                        "task_id": task.task_id,
                        "category": task.category,
                        "suite_version": task.suite_version,
                        "time_budget_seconds": task.time_budget_seconds,
                        "allowed_paths": task.allowed_paths,
                        "forbidden_paths": task.forbidden_paths,
                        "scope_policy": SCOPE_POLICY,
                        "scratch_path": SCRATCH_NAME,
                        "budget_profile": args.budget_profile,
                        "budget_profiles": {
                            k: {
                                "task_seconds": v["task_seconds"],
                                "grace_seconds": v["grace_seconds"],
                                "comparison_eligible": v["comparison_eligible"],
                            }
                            for k, v in BUDGET_PROFILES.items()
                        },
                        "evidence_limits": asdict(EVIDENCE_LIMITS),
                        "pending_worker": read_pending(args.state_dir),
                    },
                    indent=2,
                )
            )
        elif args.command == "status":
            value: dict[str, Any] = {"pending_worker": read_pending(args.state_dir)}
            if args.run_dir:
                info, trials = load_run(args.run_dir)
                value.update(
                    run_id=info.run_id,
                    trials=[
                        {"trial_id": t.trial_id, "status": t.status}
                        for t in trials
                    ],
                )
            print(json.dumps(value, indent=2))
        elif args.command == "smoke":
            smoke_provider, smoke_model = resolve_model_provider_and_key(args.model, default_provider=args.provider)
            directory = asyncio.run(
                run_diagnostic(
                    output=args.output_dir,
                    state=args.state_dir,
                    model=smoke_model,
                    provider=smoke_provider,
                    agent=args.agent,
                    base_url=args.base_url,
                    request_seconds=args.request_timeout,
                )
            )
            print(directory)
            report = json.loads(
                (directory / "acceptance.json").read_text(encoding="utf-8")
            )
            return (
                0
                if report["integration_status"] == "completed_with_limitations"
                else 1
            )
        elif args.command == "run":
            directory = asyncio.run(
                run_benchmark(
                    args.task,
                    reports=args.output_dir,
                    state=args.state_dir,
                    model=args.model,
                    provider=args.provider,
                    agent=args.agent,
                    base_url=args.base_url,
                    task_seconds=args.budget,
                    budget_profile=args.budget_profile,
                    grace_seconds=args.cancel_grace,
                    request_seconds=args.request_timeout,
                    verifier_seconds=args.verifier_timeout,
                )
            )
            print(directory)
            _, trials = load_run(directory)
            return 0 if trials and all(t.status == "passed" for t in trials) else 1
        else:
            result = asyncio.run(
                cleanup_trial(
                    state=args.state_dir,
                    run_dir=args.run_dir,
                    execute=args.execute,
                    base_url=args.base_url,
                    grace_seconds=args.cancel_grace,
                    request_seconds=args.request_timeout,
                )
            )
            print(json.dumps(result, indent=2))
            if args.execute and not result.get("termination_confirmed", False):
                return 1
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(
            "agent-bench: interrupted; inspect status before dispatching again",
            file=sys.stderr,
        )
        return 130
    except Exception as error:  # CLI boundary: preserve actionable errors without credential disclosure.
        message = (
            type(error).__name__
            if isinstance(error, httpx.HTTPError)
            else str(error)
        )
        password = os.environ.get("OPENCODE_SERVER_PASSWORD")
        if password:
            message = message.replace(password, "***")
        print(f"agent-bench: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
