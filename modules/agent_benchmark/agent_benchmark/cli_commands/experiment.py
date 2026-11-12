"""CLI definitions and handlers for multi-model experiment commands."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import inspect
import json
import logging
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

from .. import __version__
from ..dashboard import ExperimentDashboard
from ..identity import get_effective_lmstudio_model_ids, model_readiness
from ..inference_profile import load_inference_profile, validate_context_match
from ..instruction_overlay import load_instruction_append
from ..logging_setup import close_run_logging, configure_run_logging
from ..models_lifecycle import (
    DEFAULT_BENCHMARK_CONTEXT_LENGTH,
    list_downloaded_models,
    resolve_model_provider_and_key,
)
from ..runner import BUDGET_PROFILES
from ..scheduler import ExperimentScheduler, expand_experiment_plan
from .common import positive_int, ram_percent, resolve_tasks

logger = logging.getLogger(__name__)


def add_experiment_parser(actions: Any) -> None:
    """Add multi-model experiment subparser."""
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
    exp_plan.add_argument(
        "-c",
        "--context-length",
        type=positive_int,
        default=DEFAULT_BENCHMARK_CONTEXT_LENGTH,
        help="Shared LM Studio context cap for all local models (default: 16384)",
    )
    exp_plan.add_argument(
        "-I",
        "--inference-profile",
        type=Path,
        help="Validated per-trial OpenCode context/output/reasoning settings JSON",
    )
    exp_plan.add_argument(
        "-A",
        "--instruction-append-file",
        type=Path,
        help="Append a UTF-8 task-instruction variant; record its path and SHA-256",
    )
    exp_plan.add_argument("-u", "--base-url", default="http://127.0.0.1:4096")
    exp_plan.add_argument("--random-seed", type=int, default=None)

    # experiment run
    exp_run = exp_actions.add_parser(
        "run", help="Execute an authorized multi-model experiment"
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
    exp_run.add_argument(
        "-c",
        "--context-length",
        type=positive_int,
        default=DEFAULT_BENCHMARK_CONTEXT_LENGTH,
        help="Shared LM Studio context cap for all local models (default: 16384)",
    )
    exp_run.add_argument(
        "-M",
        "--max-ram-percent",
        type=ram_percent,
        default=None,
        help="Stop before transition if host RAM percent is at/above this value (e.g. 80.0)",
    )
    exp_run.add_argument(
        "-I",
        "--inference-profile",
        type=Path,
        help="Validated per-trial OpenCode context/output/reasoning settings JSON",
    )
    exp_run.add_argument(
        "-A",
        "--instruction-append-file",
        type=Path,
        help="Append a UTF-8 task-instruction variant; record its path and SHA-256",
    )
    exp_run.add_argument(
        "-P",
        "--pause-before-dispatch",
        action="store_true",
        help="Pause after OpenCode session creation for LLM Monitor attachment before dispatch",
    )
    exp_run.add_argument(
        "--tool-profile",
        choices=("file-tools-v1", "retrieval-files-v1", "retrieval-structural-v1"),
        default=None,
        help="Apply one identical tool profile to every task (matched intervention runs)",
    )
    exp_run.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory where experiment artifacts and reports are saved",
    )
    exp_run.add_argument(
        "-s",
        "--state-dir",
        type=Path,
        default=Path.home() / ".local/share/agent-benchmark",
        help="Persistent dispatch receipts, shared across output locations",
    )
    exp_run.add_argument("-u", "--base-url", default="http://127.0.0.1:4096")
    exp_run.add_argument(
        "--allow-model-transitions",
        action="store_true",
        default=True,
        help="Allow automated model unload/load cycles via LM Studio (default: True)",
    )
    exp_run.add_argument(
        "-Q", "--quiet", action="store_true", help="Suppress terminal dashboard"
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


def handle_experiment(args: argparse.Namespace, exp_parser: argparse.ArgumentParser) -> int:
    cmd = getattr(args, "experiment_command", None)
    if cmd is None:
        exp_parser.print_help()
        return 0

    if cmd == "plan":
        task_map = resolve_tasks(args.task)
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
            metadata={
                "requested_context_length": args.context_length,
                "requested_inference_profile": profile.to_dict() if profile else None,
                "instruction_append": instruction_append.to_dict() if instruction_append else None,
            },
        )
        plan = expand_experiment_plan(config, randomize_tasks=False)

        import agent_benchmark.cli as cli_mod
        fetch_downloaded = getattr(cli_mod, "list_downloaded_models", list_downloaded_models)
        fetch_effective_ids = getattr(cli_mod, "get_effective_lmstudio_model_ids", get_effective_lmstudio_model_ids)

        async def _readiness():
            try:
                res = fetch_downloaded()
                if inspect.isawaitable(res):
                    res = await res
                inventory = res
            except Exception:
                return [
                    {
                        "requested_id": key,
                        "status": "unknown",
                        "reason": "LM Studio inventory could not be read; plan is expanded but run readiness is unverified.",
                        "identity": None,
                    }
                    for key in models
                ]
            res_state = fetch_effective_ids(args.base_url, directory=Path.cwd())
            if inspect.isawaitable(res_state):
                res_state = await res_state
            provider_state = res_state
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
                        row["reason"] = (
                            f"Requested context {args.context_length} exceeds model maximum "
                            f"{maximum}; reduce -c before running."
                        )
                    elif identity and not maximum:
                        row["status"] = "context_limit_unknown"
                        row["reason"] = "LM Studio did not report this model's maximum context; run readiness is unknown."
                    if identity:
                        row["resource_preflight"] = "checked_before_load_at_run_time"
                    rows.append(row)
                else:
                    rows.append({
                        "requested_id": key,
                        "status": "not_checked",
                        "reason": f"Provider '{provider}' uses its own CLI/runtime readiness checks.",
                        "identity": {"provider": provider, "runtime_model_id": model_id},
                    })
            return rows

        payload = plan.to_dict()
        payload["model_readiness"] = asyncio.run(_readiness(), loop_factory=asyncio.SelectorEventLoop)
        print(json.dumps(payload, indent=2))
        return 0

    elif cmd == "run":
        if not args.execute:
            print(
                "agent-bench: experiment run requires explicit -x/--execute authorization",
                file=sys.stderr,
            )
            return 2

        task_map = resolve_tasks(args.task)
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
            metadata={
                "requested_context_length": args.context_length,
                "runtime_max_ram_percent": args.max_ram_percent,
                "requested_inference_profile": profile.to_dict() if profile else None,
                "instruction_append": instruction_append.to_dict() if instruction_append else None,
            },
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
            exp_id,
            models,
            sorted(task_map),
            args.repetitions,
            args.budget_profile,
            args.context_length,
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
            logger.exception(
                "Experiment command failed id=%s", exp_id, extra={"event_type": "EXPERIMENT_COMMAND_ERROR"}
            )
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
