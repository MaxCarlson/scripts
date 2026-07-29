"""Command-line interface for development-ledger operations."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from development_ledger.analysis import build_manual_event, build_validation_event
from development_ledger.ledger import LedgerError, append_event, git_provenance, read_events
from development_ledger.models import VALID_MANUAL_STATES
from development_ledger.plan import PlanValidationError, load_plan, render_plan_template
from development_ledger.render import render_progress, write_projections
from development_ledger.results import ResultParseError, parse_junit_xml, parse_script_results, parse_transcript
from development_ledger.setup import SUPPORTED_AGENTS, SetupResult, apply_setup, plan_repository_setup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="development-ledger",
        description="Create plan-aware validation history and hybrid/local LLM handoff artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="Bootstrap development-ledger instructions and docs in a repository.")
    setup.add_argument("-r", "--repo-root", type=Path, required=True, help="Target repository root.")
    setup.add_argument(
        "-s", "--scope", action="append", default=[], help="Repository-relative independent planning scope; repeatable."
    )
    setup.add_argument(
        "-m", "--module", action="append", default=[], help="Module name below modules/; repeatable convenience option."
    )
    setup.add_argument("-A", "--all-modules", action="store_true", help="Add every immediate directory below modules/.")
    setup.add_argument(
        "-a",
        "--agent",
        action="append",
        choices=SUPPORTED_AGENTS,
        default=[],
        help="Agent instruction target; repeatable. Defaults to all supported agents.",
    )
    setup.add_argument("-N", "--repository-name", default="", help="Display name; defaults to root directory name.")
    setup.add_argument("-f", "--force", action="store_true", help="Replace conflicting setup-managed documents.")
    setup.add_argument("-F", "--format", choices=("text", "json"), default="text", help="Result format.")
    setup.add_argument("-w", "--write", action="store_true", help="Apply changes; otherwise show a dry-run plan.")
    setup.set_defaults(handler=_handle_setup)

    validate = subparsers.add_parser("validate-plan", help="Validate the structured state in a plan document.")
    validate.add_argument("-p", "--plan", type=Path, required=True, help="Markdown plan containing ledger state.")
    validate.add_argument("-f", "--format", choices=("text", "json"), default="text", help="Output format.")
    validate.set_defaults(handler=_handle_validate_plan)

    init = subparsers.add_parser("init-plan", help="Create or preview a plan template.")
    init.add_argument("-p", "--plan", type=Path, required=True, help="Plan path to create.")
    init.add_argument("-i", "--plan-id", required=True, help="Stable plan identifier.")
    init.add_argument("-t", "--title", required=True, help="Human-readable plan title.")
    init.add_argument("-r", "--project-root", required=True, help="Repository-relative project root.")
    init.add_argument("-w", "--write", action="store_true", help="Write the file; otherwise print a preview.")
    init.set_defaults(handler=_handle_init_plan)

    record = subparsers.add_parser("record", help="Create a normalized validation-run event.")
    record.add_argument("-p", "--plan", type=Path, required=True, help="Active Markdown plan.")
    record.add_argument("-o", "--output-dir", type=Path, required=True, help="Plan ledger output directory.")
    record.add_argument("-r", "--repo-root", type=Path, required=True, help="Git repository root.")
    record.add_argument("-j", "--junit", action="append", type=Path, default=[], help="JUnit XML file; repeatable.")
    record.add_argument(
        "-s", "--script-result", action="append", type=Path, default=[], help="Generic script-result JSON; repeatable."
    )
    record.add_argument(
        "-t", "--transcript", action="append", type=Path, default=[], help="Legacy text transcript; repeatable."
    )
    record.add_argument("-a", "--actor", default="", help="Override plan session actor.")
    record.add_argument("-m", "--mode", default="", help="Override plan session mode.")
    record.add_argument("-i", "--run-id", default="", help="Explicit immutable event ID.")
    record.add_argument("-w", "--write", action="store_true", help="Append the event and regenerate projections.")
    record.set_defaults(handler=_handle_record)

    summarize = subparsers.add_parser("summarize", help="Regenerate or preview projections from the event ledger.")
    summarize.add_argument("-p", "--plan", type=Path, required=True, help="Active Markdown plan.")
    summarize.add_argument("-o", "--output-dir", type=Path, required=True, help="Plan ledger output directory.")
    summarize.add_argument("-w", "--write", action="store_true", help="Write projections; otherwise print PROGRESS.md.")
    summarize.set_defaults(handler=_handle_summarize)

    manual = subparsers.add_parser("manual", help="Record a manual-check result as an immutable event.")
    manual.add_argument("-p", "--plan", type=Path, required=True, help="Active Markdown plan.")
    manual.add_argument("-o", "--output-dir", type=Path, required=True, help="Plan ledger output directory.")
    manual.add_argument("-r", "--repo-root", type=Path, default=Path.cwd(), help="Git repository root.")
    manual.add_argument("-i", "--check-id", required=True, help="Manual check ID.")
    manual.add_argument("-s", "--status", choices=sorted(VALID_MANUAL_STATES), required=True, help="Check result.")
    manual.add_argument("-n", "--note", default="", help="Evidence or concise result note.")
    manual.add_argument("-a", "--actor", default="user", help="Actor recording the result.")
    manual.add_argument("-e", "--event-id", default="", help="Explicit immutable event ID.")
    manual.add_argument("-w", "--write", action="store_true", help="Append the event and regenerate projections.")
    manual.set_defaults(handler=_handle_manual)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (PlanValidationError, ResultParseError, LedgerError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _handle_setup(args: argparse.Namespace) -> int:
    result = plan_repository_setup(
        args.repo_root,
        scopes=args.scope,
        modules=args.module,
        all_modules=args.all_modules,
        agents=args.agent,
        repository_name=args.repository_name,
        force=args.force,
    )
    if args.write:
        apply_setup(result)
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=4, ensure_ascii=False))
    else:
        _print_setup_result(result, write=args.write)
    return 2 if result.has_conflicts else 0


def _handle_validate_plan(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    if args.format == "json":
        print(json.dumps(plan.to_dict(), indent=4, ensure_ascii=False))
    else:
        print(f"VALID: {plan.plan_id} · {len(plan.items)} item(s) · {len(plan.manual_checks)} manual check(s)")
    return 0


def _handle_init_plan(args: argparse.Namespace) -> int:
    content = render_plan_template(plan_id=args.plan_id, title=args.title, project_root=args.project_root)
    if not args.write:
        print(content, end="")
        return 0
    if args.plan.exists():
        raise ValueError(f"Refusing to overwrite existing plan: {args.plan}")
    args.plan.parent.mkdir(parents=True, exist_ok=True)
    args.plan.write_text(content, encoding="utf-8", newline="\n")
    print(f"CREATED: {args.plan}")
    return 0


def _handle_record(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    prior_events = read_events(args.output_dir)
    previous_validation = next(
        (event for event in reversed(prior_events) if event.get("event_type") == "validation_run"), None
    )
    baseline_commit = str(previous_validation.get("provenance", {}).get("commit", "")) if previous_validation else ""
    provenance = git_provenance(args.repo_root, baseline_commit=baseline_commit)

    tests = []
    artifacts: list[str] = []
    transcript_metrics: dict[str, int | float] = {}
    for path in args.junit:
        tests.extend(parse_junit_xml(path))
        artifacts.append(str(path))
    for path in args.script_result:
        tests.extend(parse_script_results(path))
        artifacts.append(str(path))
    for path in args.transcript:
        transcript_tests, metrics = parse_transcript(path)
        tests.extend(transcript_tests)
        transcript_metrics.update(metrics)
        artifacts.append(str(path))

    timestamp = _timestamp()
    event_id = args.run_id or _event_id("run", timestamp, provenance.get("commit", ""))
    event = build_validation_event(
        event_id=event_id,
        timestamp=timestamp,
        plan=plan,
        tests=tests,
        provenance=provenance,
        prior_events=prior_events,
        transcript_metrics=transcript_metrics,
        artifacts=artifacts,
        actor=args.actor,
        mode=args.mode,
    )
    if not args.write:
        print(json.dumps(event, indent=4, ensure_ascii=False))
        return 1 if event["test_summary"].get("failed", 0) or event["test_summary"].get("errors", 0) else 0

    append_event(args.output_dir, event)
    events = prior_events + [event]
    write_projections(args.output_dir, plan, events)
    _print_run_summary(event, args.output_dir)
    return 1 if event["test_summary"].get("failed", 0) or event["test_summary"].get("errors", 0) else 0


def _handle_summarize(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    events = read_events(args.output_dir)
    if args.write:
        write_projections(args.output_dir, plan, events)
        print(f"UPDATED: {args.output_dir}")
    else:
        print(render_progress(plan, events), end="")
    return 0


def _handle_manual(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    events = read_events(args.output_dir)
    provenance = git_provenance(args.repo_root)
    timestamp = _timestamp()
    event = build_manual_event(
        event_id=args.event_id or _event_id("manual", timestamp, provenance.get("commit", "")),
        timestamp=timestamp,
        plan=plan,
        check_id=args.check_id,
        status=args.status,
        note=args.note,
        provenance=provenance,
        actor=args.actor,
    )
    if not args.write:
        print(json.dumps(event, indent=4, ensure_ascii=False))
        return 0
    append_event(args.output_dir, event)
    write_projections(args.output_dir, plan, events + [event])
    print(f"RECORDED: {args.check_id} -> {args.status}")
    return 0


def _print_setup_result(result: SetupResult, *, write: bool) -> None:
    mode = "APPLY" if write else "DRY-RUN"
    print(f"{mode}: {result.repo_root}")
    print(f"SCOPES: {', '.join(result.scopes)}")
    print(f"AGENTS: {', '.join(result.agents)}")
    for operation in result.operations:
        print(f"{operation.action.upper():9} {operation.path} — {operation.reason}")
    print(f"CHANGES: {result.changed_count}")
    if result.has_conflicts:
        print("CONFLICTS: resolve conflicts or rerun with an appropriate explicit --force.")


def _print_run_summary(event: dict[str, object], output_dir: Path) -> None:
    summary = event["test_summary"]
    progress = event["progress"]
    routing = event["routing"]
    assert isinstance(summary, dict)
    assert isinstance(progress, dict)
    assert isinstance(routing, dict)
    print(f"RUN: {event['event_id']}")
    print(
        f"TESTS: {summary.get('passed', 0)} passed · {summary.get('failed', 0)} failed · "
        f"{summary.get('errors', 0)} errors · {summary.get('skipped', 0)} skipped"
    )
    print(f"PROGRESS: {progress.get('classification', 'unknown')}")
    print(f"ROUTING: {routing.get('decision', 'unknown')}")
    print(f"SUMMARY: {output_dir / 'PROGRESS.md'}")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _event_id(prefix: str, timestamp: str, commit: str) -> str:
    compact = timestamp.replace("+00:00", "Z").replace("-", "").replace(":", "").replace(".", "")
    commit_part = commit[:8] if commit else "no-commit"
    return f"{prefix}-{compact}-{commit_part}-{uuid.uuid4().hex[:6]}"
