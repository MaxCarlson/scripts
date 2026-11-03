"""Argparse interface for persistent Harbor benchmark suites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .suite import (
    COHORTS,
    DEFAULT_MONITOR_URL,
    RunStore,
    build_manifest,
    create_run,
    execute_pending,
    launch_background,
    status_run,
    summarize_run,
)
from .suite_monitor import MonitorPreflightError, host_monitor_origin, validate_monitor
from .suite_output import emit
from .suite_revision import DatasetRevisionError, include_registry_resolution, resolve_frozen_registry_snapshot

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
        parser.add_argument(
            "-A",
            "--api-format",
            choices=(
                "openai_chat_completions",
                "openai_responses",
                "anthropic_messages",
                "google_generate_content",
                "bedrock_converse",
            ),
            default=None,
        )
        parser.add_argument("-L", "--llm-monitor", action="store_true")
        parser.add_argument("-U", "--monitor-url", default=DEFAULT_MONITOR_URL)
        parser.add_argument("-H", "--monitor-host-url", default=None, help="Monitor URL reachable from this host")
        parser.add_argument("-R", "--recording", choices=("off", "metadata", "content"), default="off")
        parser.add_argument("-j", "--jobs", type=int, default=1)
        parser.add_argument(
            "-P", "--prompt-policy-file", type=Path, help="UTF-8 specification policy for the isolated OpenCode study"
        )
        parser.add_argument("-Q", "--expected-policy-sha256", help="Policy digest from the previously reviewed plan")
        parser.add_argument(
            "-S", "--spec-verification-study", action="store_true", help="Use the isolated OpenCode v1 study adapter"
        )
        parser.add_argument("-I", "--study-repetition", type=int, help="Study repetition index")
        parser.add_argument("-Z", "--study-seed", type=int, help="Study randomization seed")
        parser.add_argument(
            "-r",
            "--recover-local",
            action="store_true",
            help="Authorize bounded start of absent local managed LLM Monitor",
        )
        parser.add_argument("-F", "--llm-friendly", action="store_true")
        if execution:
            parser.add_argument("-x", "--execute", action="store_true", help="Required authorization for inference")

    plan = commands.add_parser("plan", help="Inspect cohort resolution and route readiness without execution")
    common(plan)
    run = commands.add_parser("run", help="Execute an authorized cohort")
    common(run, execution=True)
    run.add_argument(
        "-N",
        "--prepare-only",
        action="store_true",
        help="Prepare a study run for separate network qualification without dispatch",
    )
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
    resume.add_argument(
        "--recover-local", action="store_true", help="Authorize bounded start of absent local managed LLM Monitor"
    )
    resume.add_argument("-F", "--llm-friendly", action="store_true")
    resume.add_argument("--retry-invalid", action="store_true", help="Retry each infrastructure-invalid task once")
    resume.add_argument("-B", "--background", action="store_true")
    report = commands.add_parser("report", help="Aggregate an immutable run checkpoint")
    report.add_argument("-r", "--run-id", required=True)
    report.add_argument("-d", "--runs-dir", type=Path, default=DEFAULT_RUNS)
    report.add_argument("-F", "--llm-friendly", action="store_true")
    archive = commands.add_parser("archive", help="Archive and verify LLM Monitor evidence for suite runs")
    archive.add_argument(
        "action",
        nargs="?",
        choices=("create", "verify"),
        default="create",
        help="Archive action: create (default) or verify",
    )
    archive.add_argument("-r", "--run", "--run-id", dest="run", help="Run ID or path to run directory")
    archive.add_argument(
        "-R",
        "--runs-root",
        "--runs-dir",
        dest="runs_root",
        type=Path,
        default=DEFAULT_RUNS,
        help="Suite runs root directory",
    )
    archive.add_argument("-d", "--database", type=Path, help="Path to SQLite recording database")
    archive.add_argument("-H", "--monitor-host-url", help="Host-reachable LLM Monitor URL")
    archive.add_argument("-o", "--output", type=Path, help="Target archive output directory")
    archive.add_argument("-t", "--drain-timeout", type=float, default=30.0, help="Seconds to wait for recorder drain")
    archive.add_argument("-i", "--poll-interval", type=float, default=1.0, help="Seconds between drain polls")
    archive.add_argument("-P", "--allow-partial", action="store_true", help="Allow incomplete or live evidence")
    archive.add_argument(
        "-N", "--include-native", action="store_true", help="Include native Harbor job artifacts and logs"
    )
    archive.add_argument(
        "-x", "--execute", action="store_true", help="Required authorization to create archive; default is dry-run"
    )
    archive.add_argument("-p", "--archive", dest="archive", type=Path, help="Archive path to verify")
    archive.add_argument("-F", "--llm-friendly", action="store_true", help="Compact JSON output")

    doctor = commands.add_parser("doctor", help="Inspect execution context and service readiness without mutation")
    doctor.add_argument("-F", "--full", action="store_true", help="Enable additional bounded diagnostic probes")
    doctor.add_argument(
        "-f", "--format", choices=("text", "json"), default="text", help="Output format (default: text)"
    )
    doctor.add_argument("-L", "--llm-monitor", action="store_true", help="Check LLM Monitor readiness")
    doctor.add_argument("-U", "--monitor-url", default=DEFAULT_MONITOR_URL, help="Container-facing monitor gateway URL")
    doctor.add_argument("-H", "--monitor-host-url", default=None, help="Host-reachable LLM Monitor URL")
    doctor.add_argument("-e", "--endpoint", default=None, help="Inference provider endpoint (e.g. LM Studio)")
    doctor.add_argument(
        "-R", "--recording", choices=("off", "metadata", "content"), default="off", help="Expected recording mode"
    )
    doctor.add_argument("-a", "--agent", default=None, help="Agent profile to diagnose")
    doctor.add_argument("-m", "--model", default=None, help="Model selector to verify in provider")


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
    return {
        key: summary[key]
        for key in (
            "run_id",
            "state",
            "planned",
            "scored",
            "passed",
            "failed",
            "timed_out",
            "infrastructure_invalid",
            "pending",
            "pass_rate_pct",
            "coverage_pct",
        )
    } | {"report": str(run_dir / "report.json")}


def _error_code(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "EXECUTION_AUTHORIZATION_REQUIRED"
    if isinstance(error, MonitorPreflightError):
        return "MONITOR_PREFLIGHT_FAILED"
    if isinstance(error, DatasetRevisionError):
        return "DATASET_REVISION_PREFLIGHT_FAILED"
    if isinstance(error, FileNotFoundError):
        return "RUN_NOT_FOUND"
    if isinstance(error, ValueError):
        return "INVALID_SUITE_CONFIGURATION"
    if type(error).__name__ == "ArchiveError":
        return "ARCHIVE_FAILED"
    return "SUITE_COMMAND_FAILED"


def handle_suite(args: argparse.Namespace) -> int:
    command = args.suite_command
    friendly = bool(getattr(args, "llm_friendly", False))
    try:
        if command == "doctor":
            from .suite_doctor import run_doctor

            return run_doctor(args)
        if command == "list":
            rows = [
                {
                    "id": key,
                    "dataset": value["dataset"],
                    "source_revision": value["revision"],
                    "tasks": len(value["tasks"]),
                }
                for key, value in COHORTS.items()
            ]
            emit({"cohorts": rows}, llm_friendly=friendly)
            return 0
        if command in {"plan", "run"}:
            if command == "run" and not args.execute and not args.prepare_only:
                raise PermissionError("suite run requires explicit -x/--execute authorization")
            plan = build_manifest(
                cohort=args.cohort,
                manifest=args.manifest,
                agent=args.agent,
                model=args.model,
                base_url=args.base_url,
                api_format=args.api_format,
                llm_monitor=args.llm_monitor,
                recording=args.recording,
                jobs=args.jobs,
                monitor_url=args.monitor_url,
                monitor_host_url=args.monitor_host_url,
                study_adapter=args.spec_verification_study,
                prompt_policy_file=args.prompt_policy_file,
                study_repetition=args.study_repetition,
                study_seed=args.study_seed,
            )
            if command == "run" and args.prepare_only and (not plan.get("study_adapter") or args.background):
                raise ValueError("prepare-only requires a foreground specification-verification study")
            if command == "run" and plan.get("study_adapter") and not args.prepare_only:
                raise ValueError("study runs must use -N/--prepare-only, then qualify and resume")
            if (
                command == "run"
                and plan.get("study_adapter")
                and (args.study_repetition is None or args.study_seed is None)
            ):
                raise ValueError("study runs require -I/--study-repetition and -Z/--study-seed")
            if command == "run" and args.prompt_policy_file and not args.expected_policy_sha256:
                raise ValueError("policy run requires -Q/--expected-policy-sha256 from the reviewed plan")
            if args.expected_policy_sha256 and args.expected_policy_sha256 != plan.get("prompt_policy", {}).get(
                "sha256"
            ):
                raise ValueError("policy SHA-256 does not match the reviewed plan")
            if command == "plan":
                if args.llm_monitor:
                    recover_local = bool(getattr(args, "recover_local", False))
                    from .suite_recovery import recover_managed_monitor

                    host_origin = host_monitor_origin(args.monitor_url, args.monitor_host_url)
                    rec = recover_managed_monitor(
                        host_origin=host_origin,
                        recording=args.recording,
                        recover_local=recover_local,
                    )
                    route = validate_monitor(
                        agent=plan["agent"],
                        model=plan["model"],
                        monitor_url=args.monitor_url,
                        monitor_host_url=args.monitor_host_url,
                        recording=args.recording,
                        api_format=plan["provenance"]["effective_api_format"],
                    )
                    route["recovery"] = rec
                    plan["monitor_preflight"] = route
                emit({"event": "plan_ready", "plan": plan} if friendly else plan, llm_friendly=friendly)
                return 0 if plan["readiness"].get("is_runnable") else 1
            if not plan["readiness"].get("is_runnable"):
                raise RuntimeError("suite readiness blocked: " + "; ".join(plan["readiness"].get("blockers", [])))
            registry_snapshot = None
            if plan["provenance"].get("registry_revision_required"):
                harbor_dataset = plan["provenance"].get("harbor_dataset")
                if not harbor_dataset:
                    raise DatasetRevisionError(
                        "Harbor registry dataset identity is missing; no inference was dispatched"
                    )
                registry_snapshot, resolution = resolve_frozen_registry_snapshot(
                    dataset=harbor_dataset,
                    task_ids=plan["tasks"],
                    expected_revision=plan["source_revision"],
                )
                plan = include_registry_resolution(plan, resolution)
            run_dir = create_run(
                args.output_root,
                cohort=args.cohort,
                manifest=args.manifest,
                agent=args.agent,
                model=args.model,
                base_url=args.base_url,
                api_format=args.api_format,
                llm_monitor=args.llm_monitor,
                recording=args.recording,
                jobs=args.jobs,
                monitor_url=args.monitor_url,
                monitor_host_url=args.monitor_host_url,
                planned_manifest=plan,
                registry_snapshot=registry_snapshot,
                prompt_policy_file=args.prompt_policy_file,
            )
            store = RunStore(run_dir)
            if args.prepare_only:
                _emit_event("prepared", friendly=friendly, run_id=store.manifest["run_id"], run_dir=str(run_dir))
                return 0
            if args.llm_monitor:
                try:
                    recover_local = bool(getattr(args, "recover_local", False))
                    from .suite_recovery import recover_managed_monitor

                    host_origin = host_monitor_origin(args.monitor_url, args.monitor_host_url)
                    rec = recover_managed_monitor(
                        host_origin=host_origin,
                        recording=args.recording,
                        recover_local=recover_local,
                    )
                    route = validate_monitor(
                        agent=store.manifest["agent"],
                        model=store.manifest["model"],
                        monitor_url=args.monitor_url,
                        monitor_host_url=args.monitor_host_url,
                        recording=args.recording,
                        api_format=store.manifest["provenance"]["effective_api_format"],
                    )
                    route["recovery"] = rec
                    (run_dir / "monitor-preflight.json").write_text(
                        json.dumps(route, indent=2) + "\n", encoding="utf-8"
                    )
                except MonitorPreflightError as error:
                    store.set_state("blocked_monitor", error_code="MONITOR_PREFLIGHT_FAILED", error_detail=str(error))
                    raise MonitorPreflightError(
                        f"monitor preflight failed; run {store.manifest['run_id']} preserved: {error}"
                    ) from error
            if args.background:
                pid = launch_background(run_dir)
                _emit_event(
                    "started",
                    friendly=friendly,
                    run_id=store.manifest["run_id"],
                    pid=pid,
                    state="starting",
                    run_dir=str(run_dir),
                )
                return 0
            _emit_event(
                "started", friendly=friendly, run_id=store.manifest["run_id"], total=len(store.manifest["tasks"])
            )
            summary = execute_pending(
                run_dir, execute=True, on_task=lambda item: _emit_event("task_done", friendly=friendly, **item)
            )
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
            if store.manifest.get("study_adapter"):
                from .network_receipt import validate_receipt

                validate_receipt(run_dir, store.manifest)
            if store.manifest["provenance"]["llm_monitor_required"]:
                if store.manifest["agent"].lower() in ("opencode", "opencode-v2") and not store.manifest[
                    "provenance"
                ].get("effective_agent_model"):
                    raise MonitorPreflightError(
                        "legacy monitored OpenCode run has no verified provider selector; create a new run"
                    )
                recover_local = bool(getattr(args, "recover_local", False))
                from .suite_recovery import recover_managed_monitor

                host_origin = host_monitor_origin(
                    store.manifest["provenance"]["monitor_url"],
                    store.manifest["provenance"].get("monitor_host_url"),
                )
                recover_managed_monitor(
                    host_origin=host_origin,
                    recording=store.manifest["provenance"]["recording_required"],
                    recover_local=recover_local,
                )
                validate_monitor(
                    agent=store.manifest["agent"],
                    model=store.manifest["model"],
                    monitor_url=store.manifest["provenance"]["monitor_url"],
                    monitor_host_url=store.manifest["provenance"].get("monitor_host_url"),
                    recording=store.manifest["provenance"]["recording_required"],
                    api_format=store.manifest["provenance"]["effective_api_format"],
                )
            if args.background:
                pid = launch_background(run_dir, retry_invalid=args.retry_invalid)
                _emit_event("started", friendly=friendly, run_id=store.manifest["run_id"], pid=pid, state="starting")
                return 0
            _emit_event(
                "started",
                friendly=friendly,
                run_id=store.manifest["run_id"],
                total=len(store.manifest["tasks"]),
                resume=True,
            )
            summary = execute_pending(
                run_dir,
                execute=True,
                retry_invalid=args.retry_invalid,
                on_task=lambda item: _emit_event("task_done", friendly=friendly, **item),
            )
            _emit_event("finished", friendly=friendly, **_finished_payload(summary, run_dir))
            return 0 if summary["infrastructure_invalid"] == 0 else 1
        if command == "archive":
            action = getattr(args, "action", "create")
            if getattr(args, "archive", None) and not getattr(args, "run", None):
                action = "verify"
            if action == "create":
                if not getattr(args, "run", None):
                    raise ValueError("archive create requires -r/--run")
                from .suite_archive import create_archive

                return create_archive(args)
            if action == "verify":
                if not getattr(args, "archive", None):
                    raise ValueError("archive verify requires -p/--archive")
                from .suite_archive import verify_archive

                return verify_archive(args)
            raise ValueError(f"unknown archive action: {action}")
        raise ValueError("choose a suite subcommand: list, plan, run, status, resume, report, archive")
    except Exception as error:
        if friendly:
            _emit_event("error", friendly=True, code=_error_code(error), detail=str(error))
        else:
            print(f"agent-bench: {error}", file=sys.stderr)
        return 2
