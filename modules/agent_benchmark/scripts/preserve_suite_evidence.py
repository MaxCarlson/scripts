#!/usr/bin/env python3
"""Preserve and verify LLM Monitor evidence for Agent Benchmark suite runs.

Requires Python 3.10+; uses only the standard library.

Examples:
    python preserve_suite_evidence.py create -r suite-ID -H http://127.0.0.1:8789
    python preserve_suite_evidence.py create -r suite-ID -H http://127.0.0.1:8789 -x
    python preserve_suite_evidence.py create -r suite-ID -d monitor.sqlite3 -x --allow-partial
    python preserve_suite_evidence.py verify -p path/to/archive

Authentication:
    LLM_MONITOR_SESSION_COOKIE: complete Cookie header value
    LLM_MONITOR_AUTHORIZATION: complete Authorization header value

Archives can contain full model prompts, responses, tools, and private data.
Store them only in a protected, Git-ignored location.
"""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure agent_benchmark package root is in sys.path when executed directly
_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from agent_benchmark.suite_archive import (  # noqa: E402
    ENDPOINTS,
    ArchiveError,
    create_archive,
    main,
    parser_factory,
    reconcile_tasks,
    safe_origin,
    sha256_file,
    sqlite_inspect,
    sqlite_online_backup,
    verify_archive,
)

__all__ = [
    "ENDPOINTS",
    "ArchiveError",
    "create_archive",
    "main",
    "parser_factory",
    "reconcile_tasks",
    "safe_origin",
    "sha256_file",
    "sqlite_inspect",
    "sqlite_online_backup",
    "verify_archive",
]

if __name__ == "__main__":
    sys.exit(main())
