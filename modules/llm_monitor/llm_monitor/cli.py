"""Command line interface for read-only local LLM monitoring."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from .opencode import OpenCodeClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-monitor", description="Read-only local OpenCode and GPU status.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "sessions", "gpu"):
        command = sub.add_parser(name)
        _common(command)
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
    if args.command == "gpu":
        return _gpu(args)
    client = OpenCodeClient(args.url)
    if args.command == "status":
        return _status(client, args)
    if args.command == "sessions":
        return _sessions(client, args)
    if args.command == "watch":
        return _watch(client, args)
    return 2


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
    while True:
        discovery_error = None
        if args.session:
            session_ids = [args.session]
        else:
            session_ids, discovery_error = _session_ids(client, args.directory)
        snapshots = [client.poll(session_id, args.directory) for session_id in session_ids]
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
