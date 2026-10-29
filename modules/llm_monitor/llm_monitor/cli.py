"""Command line interface for read-only local LLM monitoring."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .analysis import analyze_events
from .alerts import AlertEngine, DEFAULT_RULES
from .diagnostics import diagnose_events
from .history_analysis import analyze_stored_session, compare_stored_sessions
from .mcp import correlate_job, load_job_snapshot
from .opencode import HistoryCoverage, OpenCodeClient
from .observability import (
    Freshness, ObservabilityService, ProviderStatus, SessionSummary, SystemSnapshot, SystemSummary,
)
from .providers import LMStudioClient, extract_opencode_model_limits
from .recording import Recorder
from .storage import TelemetryStore, TelemetryStoreError, default_database_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-monitor", description="Local LLM monitoring and historical telemetry.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "sessions", "gpu"):
        command = sub.add_parser(name)
        _common(command)
    for name in ("diagnose", "report"):
        command = sub.add_parser(name)
        _common(command)
        command.add_argument("-s", "--session", required=True)
        command.add_argument("-l", "--lmstudio-url", default="http://127.0.0.1:1234")
        command.add_argument("-m", "--mcp-jobs", help="Optional read-only JSON snapshot of MCP jobs")
    watch = sub.add_parser("watch")
    _common(watch)
    watch.add_argument("-s", "--session")
    watch.add_argument("-a", "--all", action="store_true")
    watch.add_argument("-i", "--interval", type=float, default=2.0)
    record = sub.add_parser("record", help="Persist read-only monitoring observations")
    selector = record.add_mutually_exclusive_group(required=True)
    selector.add_argument("-s", "--session")
    selector.add_argument("-a", "--all", action="store_true")
    record.add_argument("-i", "--interval", type=float, default=2.0)
    record.add_argument("-d", "--database", type=Path)
    record.add_argument("-f", "--format", choices=("text", "json"), default="text")
    record.add_argument("-v", "--verbose", action="store_true")
    record.add_argument("-u", "--url", default="http://127.0.0.1:4096")
    record.add_argument("-p", "--project-directory")
    record.add_argument("-l", "--lmstudio-url", default="http://127.0.0.1:1234")
    record.add_argument("-m", "--mcp-jobs", help="Optional read-only JSON snapshot of MCP jobs")
    record.add_argument("-g", "--hardware", action="store_true", help="Sample optional GPU telemetry per cycle")

    history = sub.add_parser("history", help="Query recorded telemetry without provider access")
    history.add_argument("-s", "--session")
    history.add_argument("-d", "--database", type=Path)
    history.add_argument("-u", "--url", help="Disambiguate a session recorded from another OpenCode endpoint")
    history.add_argument("-f", "--format", choices=("text", "json"), default="text")
    history.add_argument("-v", "--verbose", action="store_true")

    database = sub.add_parser("db", help="Inspect or safely prune the local telemetry database")
    db_sub = database.add_subparsers(dest="db_command", required=True)
    for name in ("info", "check"):
        command = db_sub.add_parser(name)
        command.add_argument("-d", "--database", type=Path)
        command.add_argument("-f", "--format", choices=("text", "json"), default="text")
    prune = db_sub.add_parser("prune")
    prune.add_argument("-d", "--database", type=Path)
    prune.add_argument("-r", "--older-than-days", required=True, type=int)
    prune.add_argument("-w", "--write", action="store_true", help="Apply the previewed deletions")
    prune.add_argument("-f", "--format", choices=("text", "json"), default="text")
    prune.add_argument("-v", "--verbose", action="store_true")

    for command in (sub.choices["report"],):
        command.add_argument("-D", "--database", type=Path)
        command.add_argument("-H", "--history", action="store_true", help="Use persisted telemetry only")
    compare = sub.add_parser("compare", help="Compare two or more stored sessions offline")
    compare.add_argument("-s", "--session", action="append", required=True)
    compare.add_argument("-e", "--endpoint", action="append", help="Provider endpoint; repeat in session order")
    compare.add_argument("-d", "--database", type=Path)
    compare.add_argument("-f", "--format", choices=("text", "json"), default="text")

    export = sub.add_parser("export", help="Create or verify a sanitized evidence package")
    export.add_argument("-a", "--action", choices=("create", "verify"), default="create")
    export.add_argument("-s", "--session", action="append")
    export.add_argument("-d", "--database", type=Path)
    export.add_argument("-e", "--endpoint", action="append", help="Provider endpoint; repeat in session order")
    export.add_argument("-o", "--output", type=Path, required=True)
    export.add_argument("-w", "--write", action="store_true", help="Write the package")
    export.add_argument("-F", "--events-format", choices=("jsonl", "json", "csv"), default="jsonl")
    export.add_argument("-f", "--format", choices=("text", "json"), default="text")
    export.add_argument("-v", "--verbose", action="store_true")

    visualize = sub.add_parser("visualize", help="Preview or write a static historical visualization")
    visualize.add_argument("-s", "--session", action="append", required=True)
    visualize.add_argument("-d", "--database", type=Path)
    visualize.add_argument("-e", "--endpoint", action="append", help="Provider endpoint; repeat in session order")
    visualize.add_argument("-o", "--output", type=Path, required=True)
    visualize.add_argument("-w", "--write", action="store_true", help="Write the visualization")
    visualize.add_argument("-f", "--format", choices=("svg", "html"), default="svg")
    visualize.add_argument("-v", "--verbose", action="store_true")

    tui = sub.add_parser("tui", help="Open the interactive read-only monitoring dashboard")
    selection = tui.add_mutually_exclusive_group()
    selection.add_argument("-s", "--session", help="Focus the dashboard on one session")
    selection.add_argument("-a", "--all", action="store_true", help="Show all discovered sessions")
    tui.add_argument("-d", "--database", type=Path, help="Optional telemetry database for historical sessions")
    tui.add_argument("-i", "--interval", type=float, default=2.0)
    tui.add_argument("-u", "--url", default="http://127.0.0.1:4096", help="OpenCode server URL")
    tui.add_argument("-l", "--lmstudio-url", default="http://127.0.0.1:1234")
    tui.add_argument("-p", "--project-directory", help="OpenCode project directory header")
    tui.add_argument("-P", "--persist-alerts", action="store_true",
                     help="Persist local alert state in the telemetry database")
    tui.add_argument("-v", "--verbose", action="store_true")

    alerts = sub.add_parser("alerts", help="Inspect, test, or acknowledge local diagnostic alerts")
    alert_sub = alerts.add_subparsers(dest="alert_command", required=True)
    alert_list = alert_sub.add_parser("list")
    alert_list.add_argument("-d", "--database", type=Path)
    alert_list.add_argument("-s", "--status", choices=("active", "acknowledged", "resolved"))
    alert_list.add_argument("-f", "--format", choices=("text", "json"), default="text")
    alert_rules = alert_sub.add_parser("rules")
    alert_rules.add_argument("-f", "--format", choices=("text", "json"), default="text")
    alert_test = alert_sub.add_parser("test", help="Evaluate alerts against stored session history without writing")
    alert_test.add_argument("-s", "--session", required=True)
    alert_test.add_argument("-d", "--database", type=Path)
    alert_test.add_argument("-e", "--endpoint", help="Provider endpoint for disambiguation")
    alert_test.add_argument("-f", "--format", choices=("text", "json"), default="text")
    alert_ack = alert_sub.add_parser("acknowledge")
    alert_ack.add_argument("-i", "--id", required=True)
    alert_ack.add_argument("-d", "--database", type=Path)
    alert_ack.add_argument("-f", "--format", choices=("text", "json"), default="text")
    return parser


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    parser.add_argument("-u", "--url", default="http://127.0.0.1:4096", help="OpenCode server URL")
    parser.add_argument("-d", "--directory", help="OpenCode project directory header")
    parser.add_argument("-v", "--verbose", action="store_true")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "gpu":
            return _gpu(args)
        if args.command == "db":
            return _database_command(args)
        if args.command == "history":
            return _history_command(args)
        if args.command == "record":
            return _record(args)
        if args.command == "compare":
            return _compare(args)
        if args.command == "export":
            return _export_command(args)
        if args.command == "visualize":
            return _visualize_command(args)
        if args.command == "tui":
            return _tui(args)
        if args.command == "alerts":
            return _alerts_command(args)
        if args.command == "report" and args.history:
            return _historical_report(args)
        client = OpenCodeClient(args.url)
        if args.command == "status":
            return _status(client, args)
        if args.command == "sessions":
            return _sessions(client, args)
        if args.command == "watch":
            return _watch(client, args)
        if args.command in {"diagnose", "report"}:
            return _analyze_session(client, args, report=args.command == "report")
        return 2
    except KeyboardInterrupt:
        return 130
    except (TelemetryStoreError, sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
        print(f"llm-monitor: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _status(client: OpenCodeClient, args: argparse.Namespace) -> int:
    health = client.get_json("/global/health", args.directory)
    sessions = client.sessions(args.directory)
    result = {
        "opencode": {"available": health.error is None, "health": health.data, "error": health.error},
        "sessions": {"count": len(sessions.data) if isinstance(sessions.data, list) else None, "error": sessions.error},
    }
    _emit(result, args.format)
    return 0 if health.error is None and sessions.error is None else 1


def _sessions(client: OpenCodeClient, args: argparse.Namespace) -> int:
    result = client.sessions(args.directory)
    if result.error:
        _emit({"error": result.error, "sessions": None}, args.format)
        return 1
    statuses = client.get_json("/session/status", args.directory)
    rows = []
    for session in result.data if isinstance(result.data, list) else []:
        if not isinstance(session, dict):
            continue
        session_id = session.get("id")
        rows.append(
            {
                "session_id": session_id,
                "title": session.get("title"),
                "directory": session.get("directory"),
                "time": session.get("time"),
                "state": statuses.data.get(session_id) if isinstance(statuses.data, dict) else None,
            }
        )
    _emit({"sessions": rows, "status_error": statuses.error}, args.format)
    return 0


def _watch(client: OpenCodeClient, args: argparse.Namespace) -> int:
    if not args.session and not args.all:
        print("watch requires --session SESSION_ID or --all", file=sys.stderr)
        return 2
    if args.interval <= 0:
        print("--interval must be greater than zero", file=sys.stderr)
        return 2
    prior_states: dict[str, str | None] = {}
    while True:
        discovery_error = None
        if args.session:
            session_ids = [args.session]
        else:
            session_ids, discovery_error = _session_ids(client, args.directory)
        snapshots = [client.poll(session_id, args.directory) for session_id in session_ids]
        for snapshot in snapshots:
            session_id = snapshot["session_id"]
            state = snapshot.get("normalized_state")
            previous = prior_states.get(session_id)
            snapshot["state_transition"] = (
                {"from": previous, "to": state} if previous is not None and previous != state else None
            )
            prior_states[session_id] = state
            if hasattr(client, "events_for_session"):
                raw_coverage = snapshot.get("history_coverage") or {}
                try:
                    coverage = HistoryCoverage(**raw_coverage)
                    events = client.events_for_session(session_id)
                    analysis = analyze_events(session_id, events, coverage=coverage)
                    snapshot["diagnostic_findings"] = diagnose_events(
                        session_id, events, analysis, coverage=coverage
                    )
                except (TypeError, ValueError):
                    snapshot["diagnostic_findings"] = []
        record: Any = snapshots[0] if args.session and snapshots else {"sessions": snapshots}
        if discovery_error:
            record["error"] = discovery_error
        if args.format == "json":
            print(json.dumps(record, ensure_ascii=False), flush=True)
        else:
            if args.all:
                print("\033[2J\033[H", end="")
            if discovery_error:
                print(f"Session discovery failed: {discovery_error}")
            for snapshot in snapshots:
                print(_format_snapshot(snapshot, verbose=args.verbose))
        time.sleep(args.interval)


def _session_ids(client: OpenCodeClient, directory: str | None) -> tuple[list[str], str | None]:
    result = client.sessions(directory)
    if result.error:
        return [], result.error
    if not isinstance(result.data, list):
        return [], "OpenCode returned an unsupported session-list response"
    return [item["id"] for item in result.data if isinstance(item, dict) and item.get("id")], None


def _format_snapshot(snapshot: dict[str, Any], *, verbose: bool = False) -> str:
    tokens = snapshot.get("last_assistant_tokens") or {}
    line = (
        f"Session {snapshot['session_id']} state={snapshot.get('session_state') or 'idle/unknown'} "
        f"messages={snapshot['total_messages']} assistant={snapshot['assistant_messages']} "
        f"compactions={snapshot['compaction_count']} permissions={snapshot['pending_permissions']} "
        f"questions={snapshot['pending_questions']} last_finish={snapshot.get('last_assistant_finish')} "
        f"tokens={tokens} polled_at={snapshot['polled_at']}"
    )
    if verbose:
        line += (
            f"\n  last_id={snapshot.get('last_assistant_id')} agent={snapshot.get('last_assistant_agent')}"
            f" model={snapshot.get('last_assistant_model')} complete={snapshot.get('last_assistant_is_complete')}"
            f" compaction_parts={snapshot.get('compaction_parts')}"
            f" history={snapshot.get('message_counts_scope')} elapsed={snapshot.get('elapsed_sec')}s"
        )
        latest = snapshot.get("latest_completed_inference") or {}
        if latest:
            line += (f"\n  latest_completed_input={latest.get('tokens', {}).get('input')}"
                     f" output={latest.get('tokens', {}).get('output')}"
                     f" reasoning={latest.get('tokens', {}).get('reasoning')}"
                     f" completed_at={latest.get('completed_at')}")
        if snapshot.get("latest_tool"):
            tool = snapshot["latest_tool"]
            line += f"\n  latest_tool={tool.get('tool_name')} outcome={tool.get('outcome')} at={tool.get('timestamp')}"
        findings = snapshot.get("diagnostic_findings") or []
        if findings:
            line += "\n  diagnostics=" + "; ".join(
                f"{item['severity']}:{item['code']}" for item in findings
            )
        if snapshot.get("state_transition"):
            transition = snapshot["state_transition"]
            line += f"\n  transition={transition['from']}->{transition['to']}"
        line += f"\n  freshness={'stale' if snapshot.get('stale') else 'fresh'}"
        if snapshot.get("errors"):
            line += f"\n  errors={snapshot['errors']}"
    return line


def _gpu(args: argparse.Namespace) -> int:
    try:
        from resource_metrics.gpu import gpu_devices, gpu_process_memory

        result = {
            "scope": "point_in_time_device_measurement",
            "devices": gpu_devices(),
            "process_memory": gpu_process_memory(),
        }
    except ImportError:
        result = {
            "scope": "point_in_time_device_measurement",
            "devices": [],
            "process_memory": [],
            "error": "resource_metrics is not installed",
        }
    _emit(result, args.format)
    return 0 if "error" not in result else 1


def _selected_database(args: argparse.Namespace) -> Path:
    selected = getattr(args, "database", None)
    return Path(selected) if selected is not None else default_database_path()


def _compare(args: argparse.Namespace) -> int:
    with TelemetryStore(_selected_database(args), readonly=True) as store:
        comparison = compare_stored_sessions(
            store, args.session, endpoints=args.endpoint
        )
    if args.format == "json":
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
    else:
        print(f"Comparison baseline: {comparison['baseline_session_id']}")
        metric_names = list(comparison["differences"])
        for name in metric_names:
            values = [entry["baseline"] for entry in comparison["differences"][name][:1]]
            values.extend(entry["value"] for entry in comparison["differences"][name])
            display = " | ".join("unknown" if value is None else str(round(value, 3) if isinstance(value, float) else value)
                                 for value in values)
            deltas = ", ".join(
                "unknown" if item["percent"] is None else f"{item['percent']:+.2f}%"
                for item in comparison["differences"][name]
            )
            print(f"{name}: {display}" + (f" | delta {deltas}" if deltas else ""))
        print("Warnings:")
        for warning in comparison["warnings"]:
            print(f"- [{warning['classification']}] {warning['code']}: {warning['summary']}")
    return 0


def _format_history_analytics(analysis: dict[str, Any]) -> str:
    metrics = analysis.get("metrics", {})
    execution = metrics.get("execution", {})
    inference = metrics.get("inference", {})
    tokens = metrics.get("tokens", {})
    context = metrics.get("context", {})
    compactions = metrics.get("compactions", {})
    tools = metrics.get("tools", {})
    def value(item: Any) -> str:
        if item is None:
            return "unknown"
        if isinstance(item, dict):
            result = item.get("value")
            return "unknown" if result is None else str(result)
        return str(item)
    rows = [
        "Historical analytics:",
        f"  Observed duration: {value(execution.get('observed_wall_seconds'))} s",
        f"  Inferences: {inference.get('count', 'unknown')} (completed {inference.get('completed_count', 'unknown')})",
        f"  Context peak: {value(context.get('maximum_observed_utilization_percent'))}%",
        f"  Unique compactions: {compactions.get('unique_cycles', 'unknown')} "
        f"(raw parts {compactions.get('raw_parts', 'unknown')})",
        f"  Tool calls: {tools.get('invocations', 'unknown')}; reads {tools.get('read_calls', 'unknown')}; "
        f"edits {tools.get('edit_attempts', 'unknown')}",
        f"  Token totals: {json.dumps(tokens.get('observed_completed_totals', {}), sort_keys=True)}",
        f"  History coverage: {analysis.get('coverage', {}).get('status', 'unknown')}",
    ]
    findings = analysis.get("findings", [])
    if findings:
        rows.append("  Historical findings:")
        rows.extend(f"    [{item.get('classification')}] {item.get('code')}: {item.get('summary')}" for item in findings)
    return "\n".join(rows)


def _export_command(args: argparse.Namespace) -> int:
    from .evidence_export import preview_evidence_package, verify_evidence_package, write_evidence_package

    if args.action == "verify":
        result = verify_evidence_package(args.output)
    else:
        if not args.session:
            print("export create requires at least one --session", file=sys.stderr)
            return 2
        with TelemetryStore(_selected_database(args), readonly=True) as store:
            options = {"store": store, "session_ids": args.session, "endpoints": args.endpoint,
                       "output_path": args.output, "events_format": args.events_format}
            result = (write_evidence_package(**options) if args.write else preview_evidence_package(**options))
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.action == "verify":
            print(f"Verification: {'valid' if result['ok'] else 'invalid'}; files checked={result['files_checked']}")
            if result.get("errors"):
                for error in result["errors"]:
                    print(f"- {error}")
        else:
            action = "Wrote" if args.write else "Preview"
            print(f"{action} sanitized package: {args.output}; sessions={len(args.session)}; "
                  f"records={result.get('record_count', 'unknown')}; bytes={result.get('size_bytes')}")
    return 0 if result.get("ok", True) else 1


def _visualize_command(args: argparse.Namespace) -> int:
    from .visualization import render_comparison, render_session, write_visualization

    with TelemetryStore(_selected_database(args), readonly=True) as store:
        if len(args.session) == 1:
            analysis = analyze_stored_session(store, args.session[0], endpoint=(args.endpoint or [None])[0])
            content = render_session(analysis, output_format=args.format)
        else:
            comparison = compare_stored_sessions(store, args.session, endpoints=args.endpoint)
            content = render_comparison(comparison, output_format=args.format)
    if args.write:
        write_visualization(args.output, content)
        result = {"written": True, "output": str(args.output), "format": args.format,
                  "characters": len(content), "sessions": args.session}
    else:
        result = {"written": False, "output": str(args.output), "format": args.format,
                  "characters": len(content), "sessions": args.session}
    if args.verbose:
        result["preview"] = content if not args.write else None
    _emit(result, "json" if args.verbose else "text")
    if not args.verbose and not args.write:
        print("No file written; pass --write to create the visualization.")
    return 0


def _tui(args: argparse.Namespace) -> int:
    if args.interval <= 0:
        print("--interval must be greater than zero", file=sys.stderr)
        return 2
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("tui requires an interactive terminal; use status, watch, or report for non-interactive output")
    from .tui import run_dashboard

    client = OpenCodeClient(args.url)
    lmstudio = LMStudioClient(args.lmstudio_url)
    loaded_cache: dict[str, Any] = {}

    def model_metadata(session_id: str, snapshot: dict[str, Any]):
        return _model_metadata(client, lmstudio, session_id, snapshot, args.project_directory, loaded_cache)

    database_path = args.database or default_database_path()
    service = ObservabilityService(
        client,
        directory=args.project_directory,
        database_path=database_path,
        hardware_provider=_hardware_snapshot,
        model_metadata_provider=model_metadata,
        session_filter=args.session,
    )
    alert_store = TelemetryStore(database_path) if args.persist_alerts else None
    try:
        return run_dashboard(service, interval=args.interval, initial_session=args.session, alert_store=alert_store,
                             verbose=args.verbose)
    finally:
        if alert_store:
            alert_store.__exit__(None, None, None)


def _alerts_command(args: argparse.Namespace) -> int:
    if args.alert_command == "rules":
        result = {"schema_version": 1, "rules": [
            {"rule_id": rule.rule_id, "category": rule.category, "severity": rule.severity,
             "classification": rule.classification, "finding_codes": list(rule.finding_codes),
             "threshold": rule.threshold, "minimum_observations": rule.minimum_observations,
             "window_seconds": rule.window_seconds, "cooldown_seconds": rule.cooldown_seconds}
            for rule in DEFAULT_RULES
        ]}
        if args.format == "json":
            _emit(result, args.format)
        else:
            for rule in result["rules"]:
                threshold = f" threshold={rule['threshold']}" if rule["threshold"] is not None else ""
                print(f"{rule['rule_id']} [{rule['severity']}/{rule['classification']}]"
                      f"{threshold} cooldown={rule['cooldown_seconds']}s")
        return 0
    if args.alert_command == "list":
        path = _selected_database(args)
        if path.is_file():
            with TelemetryStore(path, readonly=True) as store:
                rows = store.list_alert_states(status=args.status)
        else:
            rows = []
        result = {"schema_version": 1, "database": str(path), "alerts": rows}
        if args.format == "json":
            _emit(result, args.format)
        else:
            print(f"Persisted alerts in {path}:")
            for item in rows:
                print(f"[{item['status']}/{item['severity']}/{item['classification']}] "
                      f"{item['session_id']} {item['rule_id']}: {item['summary']}")
            if not rows:
                print("No persisted alert states.")
        return 0
    if args.alert_command == "acknowledge":
        path = _selected_database(args)
        if not path.is_file():
            raise TelemetryStoreError(f"telemetry database does not exist: {path}")
        with TelemetryStore(path) as store:
            row = store.acknowledge_alert(args.id)
        if args.format == "json":
            _emit({"schema_version": 1, "alert": row}, args.format)
        else:
            print(f"Acknowledged {row['alert_id']} ({row['session_id']} {row['rule_id']}).")
        return 0
    if args.alert_command == "test":
        with TelemetryStore(_selected_database(args), readonly=True) as store:
            analysis = analyze_stored_session(store, args.session, endpoint=args.endpoint)
            context = store.session_context(args.session, endpoint=args.endpoint)
        session = analysis["session"]
        metrics = analysis["metrics"]
        markers = metrics["timeline"]["markers"]
        latest = next((item for item in reversed(markers) if item.get("category") == "inference"), None)
        recent_context = [{"event_id": item.get("event_id"), "timestamp": item.get("timestamp"),
                           "utilization_percent": item.get("context_utilization_percent")}
                          for item in markers if item.get("category") == "inference"]
        capacity = metrics["context"]["effective_capacity_tokens"].get("maximum")
        summary = SessionSummary(
            provider_instance_id=session.get("provider_instance") or "unknown",
            session_id=args.session,
            job_id=next((job.get("job_id") for job in context["jobs"] if job.get("correlation") == "exact"), None),
            model=session.get("model"), agent=session.get("agent"), context_capacity=capacity,
            state="unknown", last_observed_state="historical", state_confidence="observed",
            state_source="telemetry_store", last_activity_at=session.get("last_observed"),
            freshness=Freshness("historical", session.get("last_observed"), None, "telemetry_store"),
            coverage=analysis["coverage"], latest_inference=latest,
            cumulative_tokens={key: value.get("value") for key, value in metrics["tokens"]["observed_completed_totals"].items()},
            compaction_count=metrics["compactions"]["unique_cycles"], current_tool=None,
            blockers={"permissions": None, "questions": None}, diagnostic_severity={}, is_live=False,
            last_error_sources=[], diagnostic_findings=analysis["findings"],
            recent_context_utilization=recent_context,
        )
        now = datetime.now(timezone.utc)
        snapshot = SystemSnapshot(
            1, now.isoformat(), ProviderStatus(summary.provider_instance_id, "unavailable", now.isoformat(),
                                               "offline historical evaluation"),
            SystemSummary(1, 0, 0, 0, 0, [summary.model] if summary.model else [], "not_started_by_dashboard"),
            [summary], None, str(_selected_database(args)),
        )
        batch = AlertEngine().evaluate(snapshot, now=now)
        result = {"schema_version": 1, "session_id": args.session, "source": "persisted_telemetry",
                  "history_coverage": analysis["coverage"], "alerts": [item.to_dict() for item in batch.active],
                  "transitions": [{"transition": item.transition, "alert_id": item.alert.alert_id,
                                   "notify": item.notify} for item in batch.transitions], "written": False}
        if args.format == "text":
            print(f"Alert evaluation for {args.session}; coverage={analysis['coverage'].get('status')}; writes=none")
            for item in batch.active:
                print(f"[{item.severity}/{item.classification}] {item.rule_id}: {item.summary}")
            if not batch.active:
                print("No alert rules matched the available evidence.")
        else:
            _emit(result, args.format)
        return 0
    return 2


def _database_command(args: argparse.Namespace) -> int:
    path = _selected_database(args)
    if args.db_command == "prune" and not path.is_file():
        raise TelemetryStoreError(f"telemetry database does not exist: {path}")
    writable_prune = args.db_command == "prune" and args.write
    with TelemetryStore(path, readonly=not writable_prune) as store:
        if args.db_command == "info":
            result = store.database_info()
        elif args.db_command == "check":
            result = store.check_integrity()
        else:
            if args.older_than_days <= 0:
                print("--older-than-days must be greater than zero", file=sys.stderr)
                return 2
            cutoff = (datetime.now(timezone.utc) - timedelta(days=args.older_than_days)).isoformat()
            result = store.prune_before(cutoff, write=args.write)
    _emit(result, args.format)
    return 0 if result.get("ok", True) else 1


def _public_session(row: dict[str, Any]) -> dict[str, Any]:
    coverage = row.get("coverage_json")
    if isinstance(coverage, str):
        try:
            coverage = json.loads(coverage)
        except json.JSONDecodeError:
            coverage = None
    return {key: row.get(key) for key in (
        "session_id", "provider_type", "endpoint", "first_seen", "last_seen", "state", "agent", "model"
    )} | {"coverage": coverage}


def _history_command(args: argparse.Namespace) -> int:
    with TelemetryStore(_selected_database(args), readonly=True) as store:
        if not args.session:
            result = {"schema_version": 1, "sessions": [_public_session(row) for row in store.list_sessions()]}
        else:
            bundle = store.history_bundle(args.session, endpoint=args.url, limit=1000)
            if bundle is None:
                _emit({"session_id": args.session, "found": False}, args.format)
                return 1
            result = {
                "schema_version": 1,
                "session": _public_session(bundle["session"]),
                "coverage": bundle["coverage"],
                "page": bundle["page"],
                "gaps": bundle["gaps"],
                "jobs": bundle["jobs"],
                "model_configurations": bundle["model_configurations"],
            }
            if args.verbose:
                result["timeline"] = bundle["event_records"]
                result["hardware_samples"] = bundle["hardware_samples"]
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif "sessions" in result:
        for row in result["sessions"]:
            print(f"{row['session_id']} {row.get('provider_type')} {row.get('last_seen')} "
                  f"model={row.get('model') or 'unknown'} state={row.get('state') or 'unknown'}")
    else:
        session = result["session"]
        print(f"Session {session['session_id']} provider={session.get('endpoint')} model={session.get('model') or 'unknown'}")
        print(f"Observed {result['page']['total']} events; coverage={result['coverage'].get('status')}; "
              f"gaps={len(result['gaps'])}; jobs={len(result['jobs'])}")
    return 0


def _model_metadata(client: OpenCodeClient, lmstudio: LMStudioClient, session_id: str,
                    snapshot: dict[str, Any], directory: str | None,
                    loaded_cache: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    info = snapshot.get("session_info") if isinstance(snapshot.get("session_info"), dict) else {}
    model_id = info.get("model") if isinstance(info.get("model"), str) else None
    provider_id = info.get("provider") if isinstance(info.get("provider"), str) else None
    now = time.monotonic()
    limits_key = (model_id, provider_id)
    limits_cache = loaded_cache.setdefault("limits", {})
    cached_limits = limits_cache.get(limits_key)
    if not cached_limits or now - cached_limits["checked_at"] >= 300:
        limits_response = client.get_json("/config/providers", directory)
        limits = extract_opencode_model_limits(limits_response.data, model_id, provider_id=provider_id) if model_id else None
        limits_cache[limits_key] = {"checked_at": now, "limits": limits}
    else:
        limits = cached_limits["limits"]
    if now - loaded_cache.get("checked_at", 0) >= 300:
        try:
            loaded_cache["models"] = lmstudio.list_models()
        except (OSError, RuntimeError, ValueError):
            loaded_cache["models"] = []
        loaded_cache["checked_at"] = now
    loaded = next((model for model in loaded_cache.get("models", [])
                   if model.get("id") == model_id and model.get("state") == "loaded"), None)
    return limits, loaded


def _hardware_snapshot() -> dict[str, Any]:
    try:
        from resource_metrics.gpu import gpu_devices, gpu_process_memory
    except ImportError:
        return {"available": False, "reason_code": "not_installed", "devices": [], "process_memory": []}
    devices = gpu_devices()
    process_memory = gpu_process_memory()
    return {"available": bool(devices or process_memory), "devices": devices,
            "process_memory": process_memory, "scope": "point_in_time"}


def _record(args: argparse.Namespace) -> int:
    if args.interval <= 0:
        print("--interval must be greater than zero", file=sys.stderr)
        return 2
    path = _selected_database(args)
    client = OpenCodeClient(args.url)
    lmstudio = LMStudioClient(args.lmstudio_url)
    loaded_cache: dict[str, Any] = {}
    model_provider = lambda sid, snapshot: _model_metadata(
        client, lmstudio, sid, snapshot, args.project_directory, loaded_cache
    )
    job_provider = lambda: load_job_snapshot(args.mcp_jobs) if args.mcp_jobs else None
    with TelemetryStore(path) as store:
        recorder = Recorder(
            client, store, endpoint=args.url, interval=args.interval, directory=args.project_directory,
            model_metadata_provider=model_provider, mcp_snapshot_provider=job_provider if args.mcp_jobs else None,
            hardware_provider=_hardware_snapshot if args.hardware else None,
        )
        while True:
            discovery_error = None
            if args.session:
                session_ids = [args.session]
            else:
                sessions = client.sessions(args.project_directory)
                if sessions.error:
                    session_ids = [row["session_id"] for row in store.list_sessions(
                        provider_type="opencode", endpoint=args.url
                    )]
                    discovery_error = "session_discovery_unavailable"
                elif not isinstance(sessions.data, list):
                    session_ids = [row["session_id"] for row in store.list_sessions(
                        provider_type="opencode", endpoint=args.url
                    )]
                    discovery_error = "unsupported_session_list"
                else:
                    session_ids = [item["id"] for item in sessions.data
                                   if isinstance(item, dict) and isinstance(item.get("id"), str)]
            progress = recorder.collect_cycle(session_ids)
            if args.hardware:
                progress["hardware_samples"] += recorder.sample_hardware()
            record = {"schema_version": 1, "command": "record", "database": str(path), **progress}
            if discovery_error:
                record["discovery_error"] = discovery_error
            if args.format == "json":
                print(json.dumps(record, ensure_ascii=False), flush=True)
            else:
                print(f"Recording {len(session_ids)} sessions to {path}: "
                      f"new={progress['inserted']} updated={progress['updated']} "
                      f"duplicates={progress['duplicates']} unavailable={progress['unavailable']} "
                      f"gaps/errors={progress['errors']} hardware_samples={progress['hardware_samples']}"
                      + (f" discovery={discovery_error}" if discovery_error else ""), flush=True)
            time.sleep(args.interval)


def _historical_report(args: argparse.Namespace) -> int:
    path = _selected_database(args)
    with TelemetryStore(path, readonly=True) as store:
        initial = store.history_bundle(args.session, endpoint=args.url, limit=1)
        if initial is None:
            _emit({"session_id": args.session, "history_available": False}, args.format)
            return 1
        offset = max(0, initial["page"]["total"] - 10000)
        bundle = store.history_bundle(args.session, endpoint=args.url, limit=10000, offset=offset)
        advanced = analyze_stored_session(store, args.session, endpoint=args.url)
    return _emit_historical_report(bundle, args, advanced=advanced)


def _emit_historical_report(bundle: dict[str, Any], args: argparse.Namespace,
                            *, advanced: dict[str, Any] | None = None) -> int:
    source_coverage = bundle["coverage"]
    gaps = bundle["gaps"]
    has_more = bundle["page"]["has_more"] or bundle["page"]["offset"] > 0
    incomplete_gaps = [gap for gap in gaps if gap["category"] in
                       {"provider_error", "coverage", "monitor_offline", "retention_pruned"}]
    coverage_status = "partial" if source_coverage.get("status") != "complete" or has_more or incomplete_gaps else "complete"
    coverage = HistoryCoverage(
        status=coverage_status,
        source=source_coverage.get("source", "persisted"),
        pages=source_coverage.get("pages") or 0,
        limit=source_coverage.get("limit") or 0,
        suspected_gap=bool(source_coverage.get("suspected_gap") or has_more or incomplete_gaps),
        reason="persisted_history_gaps" if incomplete_gaps else "report_event_window_limited" if has_more else None,
    )
    events = bundle["analysis_events"]
    completed = [event for event in events if event.category == "inference" and event.outcome == "completed"]
    latest = completed[-1] if completed else None
    applicable = None
    if latest:
        candidates = [row for row in bundle["model_configurations"]
                      if row.get("model_id") == latest.model and row.get("observed_at")
                      and latest.timestamp and row["observed_at"] <= latest.timestamp
                      and row.get("loaded_state") == "loaded" and row.get("loaded_context")]
        if candidates:
            applicable = candidates[-1]
    limits = {"context": applicable.get("configured_context"), "output": applicable.get("configured_output")} \
        if applicable else None
    loaded = {"id": applicable.get("model_id"), "context_length": applicable.get("loaded_context"),
              "state": applicable.get("loaded_state")} if applicable else None
    analysis = analyze_events(args.session, events, coverage=coverage, limits=limits, loaded_model=loaded,
                              session_state=bundle["session"].get("state"))
    inference_totals: dict[str, float] = {}
    for event in completed:
        for token_name, value in (event.tokens or {}).items():
            if token_name in {"input", "output", "reasoning"}:
                inference_totals[token_name] = inference_totals.get(token_name, 0) + value
    context_trend = _context_trend(completed, bundle["model_configurations"])
    analysis["context"]["trend"] = context_trend
    analysis["observed_token_totals"] = {
        "scope": "sum_of_recorded_completed_inferences",
        "input": inference_totals.get("input"),
        "output": inference_totals.get("output"),
        "reasoning": inference_totals.get("reasoning"),
    }
    findings = diagnose_events(args.session, events, analysis, coverage=coverage)
    session_row = bundle["session"]
    result = {
        "schema_version": 1,
        "source": "persisted_telemetry",
        "history_coverage": {**coverage.__dict__, "event_total": bundle["page"]["total"],
                              "reported_window": bundle["page"], "gaps": gaps},
        "session": {"session_id": args.session, "provider": session_row.get("endpoint"),
                    "first_observed": session_row.get("first_seen"), "last_observed": session_row.get("last_seen"),
                    "monitoring_span_seconds": _elapsed_between(session_row.get("first_seen"), session_row.get("last_seen")),
                    "last_state": session_row.get("state"), "model": session_row.get("model"),
                    "agent": session_row.get("agent"), "session_completion": "unknown",
                    "work_product_completion": "unverified", "task_acceptance": "unverified"},
        "analysis": analysis,
        "findings": findings,
        "jobs": bundle["jobs"],
        "model_configurations": bundle["model_configurations"],
        "hardware_samples": bundle["hardware_samples"],
        "timeline": [row["payload"] for row in bundle["event_records"]],
        "historical_analytics": advanced,
    }
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_analysis({"session": {"session_id": args.session, "state": session_row.get("state"),
                                             "provider_id": None, "model_id": session_row.get("model"),
                                             "agent": session_row.get("agent")},
                               "analysis": analysis, "findings": findings,
                               "source_errors": {}, "mcp_correlation": None}, include_timeline=True))
        print(f"Persisted coverage: {coverage_status}; observed {bundle['page']['returned']} of "
              f"{bundle['page']['total']} events across {len(gaps)} collection gaps.")
        print(f"Hardware samples: {len(bundle['hardware_samples'])} device/process observations; "
              "not attributed to this session.")
        if advanced:
            print(_format_history_analytics(advanced))
    return 0


def _context_trend(inferences: list[Any], configurations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trend = []
    for event in inferences:
        candidates = [row for row in configurations if row.get("model_id") == event.model
                      and row.get("observed_at") and event.timestamp and row["observed_at"] <= event.timestamp
                      and row.get("loaded_state") == "loaded" and row.get("loaded_context")]
        config = candidates[-1] if candidates else None
        capacity = None
        utilization = None
        tokens = (event.tokens or {}).get("input")
        if config and config.get("configured_context"):
            effective = min(config["configured_context"], config["loaded_context"])
            capacity = max(0, effective - (config.get("configured_output") or 0))
            if isinstance(tokens, (int, float)) and capacity > 0:
                utilization = round(tokens / capacity * 100, 1)
        trend.append({"event_id": event.event_id, "timestamp": event.timestamp, "model": event.model,
                      "input_tokens": tokens, "usable_input_capacity": capacity,
                      "utilization_percent": utilization, "status": "observed" if utilization is not None else "unknown"})
    return trend


def _elapsed_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(start.replace("Z", "+00:00"))
        right = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if left.tzinfo is None:
            left = left.replace(tzinfo=timezone.utc)
        if right.tzinfo is None:
            right = right.replace(tzinfo=timezone.utc)
        return max(0.0, round((right - left).total_seconds(), 3))
    except ValueError:
        return None


def _analyze_session(client: OpenCodeClient, args: argparse.Namespace, *, report: bool) -> int:
    history = client.collect_history(args.session, args.directory)
    session_response = client.get_json(f"/session/{quote(args.session, safe='')}", args.directory)
    status_response = client.get_json("/session/status", args.directory)
    config_response = client.get_json("/config/providers", args.directory)
    session = session_response.data if isinstance(session_response.data, dict) else {}
    model = session.get("model") if isinstance(session.get("model"), dict) else {}
    latest_model = next((event.model for event in reversed(history.events)
                         if event.category == "inference" and event.model), None)
    model_id = latest_model or model.get("id")
    provider_id = model.get("providerID") if isinstance(model.get("providerID"), str) else None
    limits = extract_opencode_model_limits(config_response.data, model_id, provider_id=provider_id) if model_id else None
    source_errors = {}
    for name, result in (("session", session_response), ("status", status_response), ("config", config_response)):
        if result.error:
            source_errors[name] = result.error
    loaded_models = []
    try:
        loaded_models = LMStudioClient(args.lmstudio_url).list_models()
    except (OSError, RuntimeError, ValueError) as exc:
        source_errors["lmstudio"] = str(exc)
    loaded_model = next((item for item in loaded_models if item.get("id") == model_id and item.get("state") == "loaded"), None)
    cumulative_tokens = session.get("tokens") if isinstance(session.get("tokens"), dict) else None
    status = status_response.data.get(args.session) if isinstance(status_response.data, dict) else None
    analysis = analyze_events(
        args.session,
        history.events,
        coverage=history.coverage,
        limits=limits,
        loaded_model=loaded_model,
        cumulative_tokens=cumulative_tokens,
        session_state=status,
    )
    findings = diagnose_events(args.session, history.events, analysis, coverage=history.coverage)
    result = {
        "schema_version": 1,
        "session": _safe_session_summary(session, status),
        "analysis": analysis,
        "findings": findings,
        "source_errors": source_errors,
        "mcp_correlation": None,
    }
    if args.mcp_jobs:
        snapshot = load_job_snapshot(args.mcp_jobs)
        result["mcp_correlation"] = correlate_job(
            args.session, session.get("directory"), snapshot
        )
        correlation = result["mcp_correlation"]
        if correlation.get("status") == "correlated" and isinstance(correlation.get("job"), dict):
            job_id = correlation["job"].get("jobId")
            for finding in findings:
                finding["job_id"] = job_id
    if report:
        result["timeline"] = [event.to_dict() for event in history.events]
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_analysis(result, include_timeline=report))
    return 1 if history.coverage.status == "unavailable" else 0


def _safe_session_summary(session: dict[str, Any], status: Any) -> dict[str, Any]:
    model = session.get("model") if isinstance(session.get("model"), dict) else {}
    return {
        "session_id": session.get("id"),
        "title": session.get("title"),
        "directory": session.get("directory"),
        "agent": session.get("agent"),
        "model_id": model.get("id"),
        "provider_id": model.get("providerID"),
        "state": status,
        "session_completion": "unknown",
        "work_product_completion": "unverified",
        "task_acceptance": "unverified",
    }


def _format_analysis(result: dict[str, Any], *, include_timeline: bool) -> str:
    session = result["session"]
    analysis = result["analysis"]
    context = analysis["context"]
    latest = analysis["inference"].get("latest_completed") or {}
    mcp = result.get("mcp_correlation")
    lines = [
        f"Session {session.get('session_id')} state={session.get('state') or 'unknown'}",
        f"History: {analysis['coverage']['status']} via {analysis['coverage']['source']} "
        f"({analysis['coverage'].get('reason') or 'coverage observed'})",
        f"Model: {session.get('provider_id') or 'unknown'}/{session.get('model_id') or 'unknown'}; "
        f"agent={session.get('agent') or 'unknown'}",
        f"Inference: {analysis['inference']['completed_count']}/{analysis['inference']['count']} completed; "
        f"latest input/output/reasoning={latest.get('input_tokens')}/{latest.get('output_tokens')}/"
        f"{latest.get('reasoning_tokens')}; observed end-to-end rate="
        f"{latest.get('observed_end_to_end_tokens_per_second')} tokens/s; "
        f"capacity={context.get('effective_capacity')}; utilization={context.get('utilization_percent')}%",
        f"Compactions: {analysis['compactions']['unique_count']} unique, "
        f"{analysis['compactions']['raw_parts']} raw parts; measured durations="
        f"{analysis['compactions']['measured_duration_seconds']}",
        f"Tools: {analysis['tools']['count']} calls, {analysis['tools']['failed_count']} failures, "
        f"{analysis['tools']['edit_attempts']} edits ({analysis['tools']['edit_verification']})",
    ]
    lines.append("Findings:")
    if result["findings"]:
        lines.extend(f"- [{item['severity']}/{item['classification']}] {item['code']}: {item['summary']}"
                     for item in result["findings"])
    else:
        lines.append("- None supported by the available evidence.")
    if mcp is not None:
        job = mcp.get("job") or {}
        lines.append(f"MCP: {mcp.get('status')} job={job.get('jobId') or 'unknown'} "
                     f"confidence={mcp.get('classification')}")
    if include_timeline:
        lines.append("Timeline:")
        lines.extend(f"- {event.get('timestamp') or 'time unknown'} {event['category']}/{event.get('subtype')}"
                     for event in result.get("timeline", []))
    if result.get("source_errors"):
        lines.append(f"Unavailable sources: {result['source_errors']}")
    return "\n".join(lines)


def _emit(data: Any, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, dict):
        for key, value in data.items():
            print(f"{key}: {value}")
    else:
        print(data)


if __name__ == "__main__":
    raise SystemExit(main())
