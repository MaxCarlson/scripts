"""Explicitly authorized benchmark CLI; plan/status/cleanup preview are read-only."""

import argparse
import asyncio
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys

from benchmark_core import load_run
import httpx

from . import __version__
from .scratch import SCOPE_POLICY, SCRATCH_NAME
from .evidence import EVIDENCE_LIMITS, load_task
from .runner import cleanup_trial, run_benchmark
from .diagnostic import run_diagnostic
from .state import read_pending


def positive(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Timeouts/budgets must be finite and positive")
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="agent-bench", description="Independently verify first-attempt local coding work")
    root.add_argument("-V", "--version", action="version", version=__version__)
    actions = root.add_subparsers(dest="command")
    for name in ("plan", "run", "status", "cleanup", "smoke"):
        action = actions.add_parser(name)
        action.add_argument("-s", "--state-dir", type=Path, default=Path.home() / ".local/share/agent-benchmark",
                            help="Persistent dispatch receipts, shared across output locations")
        if name in ("plan", "run"):
            action.add_argument("-t", "--task", type=Path, default=Path(__file__).parent / "tasks/py-grep-smoke")
        if name in ("status", "cleanup"):
            action.add_argument("-r", "--run-dir", type=Path)
        if name in ("run", "cleanup", "smoke"):
            action.add_argument("-x", "--execute", action="store_true", help="Authorize execution (required for run/smoke; cleanup otherwise previews)")
            action.add_argument("-u", "--base-url", default="http://127.0.0.1:4096")
            if name != "smoke":
                action.add_argument("-g", "--cancel-grace", type=positive, default=10)
            action.add_argument("-q", "--request-timeout", type=positive, default=10)
        if name in ("run", "smoke"):
            action.add_argument("-m", "--model", required=True)
            action.add_argument("-p", "--provider", default="lmstudio")
            action.add_argument("-a", "--agent", choices=("local-worker", "local-reviewer") if name == "run" else ("local-worker",), default="local-worker")
            action.add_argument("-o", "--output-dir", type=Path, default=Path("reports" if name == "run" else "integration-acceptance"))
            if name == "run":
                action.add_argument("-b", "--budget", type=positive)
                action.add_argument("-v", "--verifier-timeout", type=positive, default=10)
    return root


def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.command is None:
        argument_parser.print_help()
        return 0
    if args.command in ("run", "smoke") and not args.execute:
        print(f"agent-bench: {args.command} requires explicit -x/--execute authorization", file=sys.stderr)
        return 2
    try:
        if args.command == "plan":
            task = load_task(args.task)
            print(json.dumps({"task_id": task.task_id, "category": task.category, "suite_version": task.suite_version,
                              "time_budget_seconds": task.time_budget_seconds, "allowed_paths": task.allowed_paths,
                              "forbidden_paths": task.forbidden_paths,
                              "scope_policy": SCOPE_POLICY, "scratch_path": SCRATCH_NAME,
                              "evidence_limits": asdict(EVIDENCE_LIMITS), "pending_worker": read_pending(args.state_dir)}, indent=2))
        elif args.command == "status":
            value = {"pending_worker": read_pending(args.state_dir)}
            if args.run_dir:
                info, trials = load_run(args.run_dir)
                value.update(run_id=info.run_id, trials=[{"trial_id": t.trial_id, "status": t.status} for t in trials])
            print(json.dumps(value, indent=2))
        elif args.command == "smoke":
            directory = asyncio.run(run_diagnostic(output=args.output_dir, state=args.state_dir, model=args.model,
                                                   provider=args.provider, agent=args.agent, base_url=args.base_url,
                                                   request_seconds=args.request_timeout))
            print(directory)
            report = json.loads((directory / "acceptance.json").read_text(encoding="utf-8"))
            return 0 if report["integration_status"] == "completed_with_limitations" else 1
        elif args.command == "run":
            directory = asyncio.run(run_benchmark(
                args.task, reports=args.output_dir, state=args.state_dir, model=args.model, provider=args.provider,
                agent=args.agent, base_url=args.base_url, task_seconds=args.budget, grace_seconds=args.cancel_grace,
                request_seconds=args.request_timeout, verifier_seconds=args.verifier_timeout,
            ))
            print(directory)
            _, trials = load_run(directory)
            return 0 if trials and all(t.status == "passed" for t in trials) else 1
        else:
            result = asyncio.run(cleanup_trial(state=args.state_dir, run_dir=args.run_dir, execute=args.execute,
                                              base_url=args.base_url, grace_seconds=args.cancel_grace,
                                              request_seconds=args.request_timeout))
            print(json.dumps(result, indent=2))
            if args.execute and not result.get("termination_confirmed", False):
                return 1
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("agent-bench: interrupted; inspect status before dispatching again", file=sys.stderr)
        return 130
    except Exception as error:  # CLI boundary: preserve actionable errors without credential disclosure.
        message = type(error).__name__ if isinstance(error, httpx.HTTPError) else str(error)
        password = os.environ.get("OPENCODE_SERVER_PASSWORD")
        if password:
            message = message.replace(password, "***")
        print(f"agent-bench: {message}", file=sys.stderr)
        return 2
