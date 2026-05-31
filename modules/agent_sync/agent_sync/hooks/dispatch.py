"""Hook dispatcher — CLI entry point for shell wrappers.

Usage:
    python -m agent_sync.hooks.dispatch --provider claude --event SessionStart \\
        --repo-root /path/to/repo

Reads JSON payload from stdin, normalizes it, calls the appropriate handler,
and prints a JSON response to stdout (used by providers that consume hook output).
"""
import argparse
import json
import sys
from pathlib import Path

from .normalize import normalize_payload
from .handlers import session_start, pre_tool, post_tool, stop

_HANDLERS = {
    "SessionStart": session_start.handle,
    "PreToolUse": pre_tool.handle,
    "PostToolUse": post_tool.handle,
    "Stop": stop.handle,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="agent_sync hook dispatcher",
        prog="python -m agent_sync.hooks.dispatch",
    )
    parser.add_argument("-P", "--provider", required=True,
                        choices=["claude", "codex", "gemini", "local"])
    parser.add_argument("-e", "--event", required=True)
    parser.add_argument("-r", "--repo-root", required=True)
    args = parser.parse_args(argv)

    raw = json.loads(sys.stdin.read() or "{}")
    raw["repo_root"] = args.repo_root

    event = normalize_payload(args.provider, args.event, raw)

    db_path = Path(args.repo_root) / "agent_sync" / "db" / "state.sqlite3"
    handler = _HANDLERS.get(args.event)
    if handler is None:
        print("{}", flush=True)
        return 0

    result = handler(event, db_path)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
