"""Command line interface for read-only local LLM monitoring."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.parse import quote

from .analysis import analyze_events
from .diagnostics import diagnose_events
from .mcp import correlate_job, load_job_snapshot
from .opencode import HistoryCoverage, OpenCodeClient
from .providers import LMStudioClient, extract_opencode_model_limits


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-monitor", description="Read-only local OpenCode and GPU status.")
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
