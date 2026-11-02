"""Argparse interface for persistent Harbor benchmark suites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .suite import (
    COHORTS, DEFAULT_MONITOR_URL, RunStore, build_manifest, create_run,
    execute_pending, launch_background, status_run, summarize_run,
)
from .suite_monitor import MonitorPreflightError, validate_monitor
from .suite_output import emit

DEFAULT_RUNS = Path("reports/agent-bench-suite")


def add_suite_parser(actions: Any) -> None:
    suite = actions.add_parser("suite", help="Plan, execute, resume and report persistent Harbor cohorts")
    commands = suite.add_subparsers(dest="suite_command")
    list_parser = commands.add_parser("list", help="List verified cohorts")
    list_parser.add_argument("-F", "--llm-friendly", action="store_true")

    def common(parser: argparse.ArgumentParser, *, execution: bool = False) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("-c", "--cohort", choices=sorted(COHORTS))
        group.add_argument("-M", "--manifest", type=Path, help="User cohort manifest JSON")
        parser.add_argument("-a", "--agent", default="qwen-coder")
        parser.add_argument("-m", "--model", default=None)
        parser.add_argument("-u", "--base-url", default=None)
        parser.add_argument("-A", "--api-format", choices=("openai_chat_completions", "openai_responses", "anthropic_messages", "google_generate_content", "bedrock_converse"), default=None)
        parser.add_argument("-L", "--llm-monitor", action="store_true")
        parser.add_argument("-U", "--monitor-url", default=DEFAULT_MONITOR_URL)
        parser.add_argument("-R", "--recording", choices=("off", "metadata", "content"), default="off")
        parser.add_argument("-j", "--jobs", type=int, default=1)
        parser.add_argument("-F", "--llm-friendly", action="store_true")
        if execution:
            parser.add_argument("-x", "--execute", action="store_true", help="Required authorization for inference")

    plan = commands.add_parser("plan", help="Inspect cohort resolution and route readiness without execution")
    common(plan)
    run = commands.add_parser("run", help="Execute an authorized cohort")
    common(run, execution=True)
    run.add_argument("-B", "--background", action="store_true")
    run.add_argument("-o", "--output-root", type=Path, default=DEFAULT_RUNS)
    lookup = commands.add_parser("status", help="Show one run checkpoint")
    lookup.add_argument("-r", "--run-id", required=True)
    lookup.add_argument("-d", "--runs-dir", type=Path, default=DEFAULT_RUNS)
    lookup.add_argument("-F", "--llm-friendly", action="store_true")
    resume = commands.add_parser("resume", help="Resume pending or explicitly retried infrastructure attempts")
    resume.add_argument("-r", "--run-id", required=True)
    resume.add_argument("-d", "--runs-dir", type=Path, default=DEFAULT_RUNS)
    resume.add_argument("-x", "--execute", action="store_true", help="Required authorization for inference")
    resume.add_argument("-F", "--llm-friendly", action="store_true")
    resume.add_argument("--retry-invalid", action="store_true", help="Retry each infrastructure-invalid task once")
    resume.add_argument("-B", "--background", action="store_true")
    report = commands.add_parser("report", help="Aggregate an immutable run checkpoint")
    report.add_argument("-r", "--run-id", required=True)
    report.add_argument("-d", "--runs-dir", type=Path, default=DEFAULT_RUNS)
    report.add_argument("-F", "--llm-friendly", action="store_true")


def _run_dir(runs_dir: Path, run_id: str) -> Path:
    candidate = Path(run_id)
    if candidate.is_dir():
        return candidate.resolve()
    path = runs_dir.expanduser().resolve() / run_id
    if not (path / "manifest.json").is_file():
        raise FileNotFoundError(f"suite run not found: {run_id}")
    return path


def _emit_event(event: str, *, friendly: bool, **data: Any) -> None:
    emit({"event": event, **data}, llm_friendly=friendly)


def _finished_payload(summary: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Keep the live completion event small; suite report retains full detail."""
    return {key: summary[key] for key in (
        "run_id", "state", "planned", "scored", "passed", "failed", "timed_out",
        "infrastructure_invalid", "pending", "pass_rate_pct", "coverage_pct",
    )} | {"report": str(run_dir / "report.json")}


def _error_code(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "EXECUTION_AUTHORIZATION_REQUIRED"
    if isinstance(error, MonitorPreflightError):
        return "MONITOR_PREFLIGHT_FAILED"
    if isinstance(error, FileNotFoundError):
        return "RUN_NOT_FOUND"
    if isinstance(error, ValueError):
        return "INVALID_SUITE_CONFIGURATION"
    return "SUITE_COMMAND_FAILED"


def handle_suite(args: argparse.Namespace) -> int:
    command = args.suite_command
    friendly = bool(getattr(args, "llm_friendly", False))
    try:
        if command == "list":
            rows = [{"id": key, "dataset": value["dataset"], "source_revision": value["revision"],
                     "tasks": len(value["tasks"])} for key, value in COHORTS.items()]
            emit({"cohorts": rows}, llm_friendly=friendly)
            return 0
        if command in {"plan", "run"}:
            if command == "run" and not args.execute:
                raise PermissionError("suite run requires explicit -x/--execute authorization")
            plan = build_manifest(cohort=args.cohort, manifest=args.manifest, agent=args.agent,
                                  model=args.model, base_url=args.base_url, api_format=args.api_format,
                                  llm_monitor=args.llm_monitor, recording=args.recording,
                                  jobs=args.jobs, monitor_url=args.monitor_url)
            if command == "plan":
                if args.llm_monitor:
                    route = validate_monitor(agent=plan["agent"], model=plan["model"],
                                             monitor_url=args.monitor_url, recording=args.recording,
                                             api_format=plan["provenance"]["effective_api_format"])
                    plan["monitor_preflight"] = route
                emit({"event": "plan_ready", "plan": plan} if friendly else plan, llm_friendly=friendly)
                return 0 if plan["readiness"].get("is_runnable") else 1
            if not plan["readiness"].get("is_runnable"):
                raise RuntimeError("suite readiness blocked: " + "; ".join(plan["readiness"].get("blockers", [])))
            run_dir = create_run(args.output_root, cohort=args.cohort, manifest=args.manifest,
                                 agent=args.agent, model=args.model, base_url=args.base_url,
                                 api_format=args.api_format, llm_monitor=args.llm_monitor,
                                 recording=args.recording, jobs=args.jobs, monitor_url=args.monitor_url)
            store = RunStore(run_dir)
            if args.llm_monitor:
                try:
                    route = validate_monitor(agent=store.manifest["agent"], model=store.manifest["model"],
                                             monitor_url=args.monitor_url, recording=args.recording,
                                             api_format=store.manifest["provenance"]["effective_api_format"])
                    (run_dir / "monitor-preflight.json").write_text(json.dumps(route, indent=2) + "\n", encoding="utf-8")
                except MonitorPreflightError as error:
                    store.set_state("blocked_monitor", error_code="MONITOR_PREFLIGHT_FAILED", error_detail=str(error))
                    raise RuntimeError(f"monitor preflight failed; run {store.manifest['run_id']} preserved: {error}") from error
            if args.background:
                pid = launch_background(run_dir)
                _emit_event("started", friendly=friendly, run_id=store.manifest["run_id"], pid=pid,
                            state="starting", run_dir=str(run_dir))
                return 0
            _emit_event("started", friendly=friendly, run_id=store.manifest["run_id"], total=len(store.manifest["tasks"]))
            summary = execute_pending(run_dir, execute=True,
                                      on_task=lambda item: _emit_event("task_done", friendly=friendly, **item))
            _emit_event("finished", friendly=friendly, **_finished_payload(summary, run_dir))
            return 0 if summary["infrastructure_invalid"] == 0 else 1
        if command in {"status", "report"}:
            run_dir = _run_dir(args.runs_dir, args.run_id)
            result = status_run(run_dir) if command == "status" else summarize_run(RunStore(run_dir).read())
            emit(result, llm_friendly=friendly)
            return 0
        if command == "resume":
            if not args.execute:
                raise PermissionError("suite resume requires explicit -x/--execute authorization")
            run_dir = _run_dir(args.runs_dir, args.run_id)
            store = RunStore(run_dir)
            if store.manifest["provenance"]["llm_monitor_required"]:
                validate_monitor(agent=store.manifest["agent"], model=store.manifest["model"],
                                 monitor_url=store.manifest["provenance"]["monitor_url"],
                                 recording=store.manifest["provenance"]["recording_required"],
                                 api_format=store.manifest["provenance"]["effective_api_format"])
            if args.background:
                pid = launch_background(run_dir, retry_invalid=args.retry_invalid)
                _emit_event("started", friendly=friendly, run_id=store.manifest["run_id"], pid=pid, state="starting")
                return 0
            _emit_event("started", friendly=friendly, run_id=store.manifest["run_id"],
                        total=len(store.manifest["tasks"]), resume=True)
            summary = execute_pending(
                run_dir, execute=True, retry_invalid=args.retry_invalid,
                on_task=lambda item: _emit_event("task_done", friendly=friendly, **item),
            )
            _emit_event("finished", friendly=friendly, **_finished_payload(summary, run_dir))
            return 0 if summary["infrastructure_invalid"] == 0 else 1
        raise ValueError("choose a suite subcommand: list, plan, run, status, resume, report")
    except Exception as error:
        if friendly:
            _emit_event("error", friendly=True, code=_error_code(error), detail=str(error))
        else:
            print(f"agent-bench: {error}", file=sys.stderr)
        return 2
