"""CLI definitions and handlers for single-run task commands."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from benchmark_core import load_run

from ..diagnostic import run_diagnostic
from ..evidence import EVIDENCE_LIMITS, load_task
from ..models_lifecycle import resolve_model_provider_and_key
from ..runner import BUDGET_PROFILES, cleanup_trial, run_benchmark
from ..scratch import SCOPE_POLICY, SCRATCH_NAME
from ..state import read_pending
from .common import positive


def setup_task_action_args(action: argparse.ArgumentParser, name: str) -> None:
    """Add standard arguments for task actions (plan, run, status, cleanup, smoke)."""
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
            default=Path(__file__).parent.parent / "tasks/py-grep-smoke",
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


def add_root_task_parsers(actions: Any) -> None:
    """Add legacy root aliases for plan, run, status, cleanup, smoke."""
    for name in ("plan", "run", "status", "cleanup", "smoke"):
        action = actions.add_parser(name)
        setup_task_action_args(action, name)


def add_task_parser(actions: Any) -> None:
    """Add canonical 'task' command group."""
    task_p = actions.add_parser(
        "task",
        help="Single-task benchmark planning, execution, status, and verification",
    )
    sub = task_p.add_subparsers(dest="task_command")
    for name in ("plan", "run", "status", "cleanup", "smoke"):
        action = sub.add_parser(name, help=f"Execute {name} action for a task")
        setup_task_action_args(action, name)


def handle_task(args: argparse.Namespace, cmd: str | None = None) -> int:
    """Handle task execution for root aliases or 'task' subcommands."""
    command = cmd or getattr(args, "task_command", None) or getattr(args, "command", None)
    if not command:
        return 0

    if command in ("run", "smoke") and not getattr(args, "execute", False):
        print(
            f"agent-bench: {command} requires explicit -x/--execute authorization",
            file=sys.stderr,
        )
        return 2

    if command == "plan":
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
        return 0
    elif command == "status":
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
        return 0
    elif command == "smoke":
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
        return 0 if report["integration_status"] == "completed_with_limitations" else 1
    elif command == "run":
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
    elif command == "cleanup":
        if not getattr(args, "execute", False) and not getattr(args, "run_dir", None):
            pending = read_pending(args.state_dir)
            if pending is None:
                print(json.dumps({"removed": False, "diagnostic": "No pending worker; specify --run-dir for completed workspace cleanup"}, indent=2))
                return 0
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

    return 0
