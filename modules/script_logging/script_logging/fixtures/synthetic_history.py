"""Synthetic history dataset generator for consumer contract and integration testing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from script_logging.invocation_store import InvocationStore


def generate_synthetic_database(path: Path | str) -> Dict[str, Any]:
    """Populate a SQLite database with deterministic, reproducible synthetic invocation history.

    Generates records across multiple programs with varied origins, exit codes, durations,
    and sensitive parameters to verify consumer integration (e.g. for scripts_help).

    Args:
        path: Destination path for SQLite database.

    Returns:
        Dictionary containing summary metadata and expected counts for verification.
    """
    store = InvocationStore(path)
    base_time = datetime(2026, 10, 24, 8, 0, 0, tzinfo=timezone.utc)

    records = [
        # Program: module:mangadl (5 invocations, 4 patterns, 3 successes, 2 failures)
        {
            "program_id": "module:mangadl",
            "invoked_name": "mangadl",
            "argv": ("mangadl", "run", "--quiet"),
            "cwd": "/work/manga",
            "origin": "launcher",
            "delta_sec": 10,
            "duration_ms": 1200,
            "exit_code": 0,
            "status": "exited",
        },
        {
            "program_id": "module:mangadl",
            "invoked_name": "mangadl",
            "argv": ("mangadl", "run", "--quiet"),
            "cwd": "/work/manga",
            "origin": "launcher",
            "delta_sec": 20,
            "duration_ms": 950,
            "exit_code": 0,
            "status": "exited",
        },
        {
            "program_id": "module:mangadl",
            "invoked_name": "mangadl",
            "argv": ("mangadl", "run", "--token=supersecret123"),
            "cwd": "/work/manga",
            "origin": "launcher",
            "delta_sec": 30,
            "duration_ms": 300,
            "exit_code": 1,
            "status": "exited",
        },
        {
            "program_id": "module:mangadl",
            "invoked_name": "mdl",
            "argv": ("mdl", "status"),
            "cwd": "/work/manga",
            "origin": "inspection",
            "delta_sec": 40,
            "duration_ms": 150,
            "exit_code": 0,
            "status": "exited",
        },
        {
            "program_id": "module:mangadl",
            "invoked_name": "mangadl",
            "argv": ("mangadl", "invalid-cmd"),
            "cwd": "/work/manga",
            "origin": "launcher",
            "delta_sec": 50,
            "duration_ms": 80,
            "exit_code": 2,
            "status": "exited",
        },
        # Program: module:compresser (3 invocations, 3 patterns, 2 successes, 1 failure)
        {
            "program_id": "module:compresser",
            "invoked_name": "compresser",
            "argv": ("compresser", "zip", "/docs"),
            "cwd": "/work/docs",
            "origin": "launcher",
            "delta_sec": 60,
            "duration_ms": 4500,
            "exit_code": 0,
            "status": "exited",
        },
        {
            "program_id": "module:compresser",
            "invoked_name": "compress",
            "argv": ("compress", "tar", "/data"),
            "cwd": "/work/data",
            "origin": "launcher",
            "delta_sec": 70,
            "duration_ms": 3200,
            "exit_code": 0,
            "status": "exited",
        },
        {
            "program_id": "module:compresser",
            "invoked_name": "compresser",
            "argv": ("compresser", "broken"),
            "cwd": "/work/docs",
            "origin": "launcher",
            "delta_sec": 80,
            "duration_ms": 10,
            "exit_code": None,
            "status": "launch_failed",
        },
        # Program: pyscript:pyscripts/run_history_process.py (2 invocations, 2 patterns, 1 success, 1 failure)
        {
            "program_id": "pyscript:pyscripts/run_history_process.py",
            "invoked_name": "run_history_process",
            "argv": ("python", "run_history_process.py", "--batch"),
            "cwd": "/work",
            "origin": "launcher",
            "delta_sec": 90,
            "duration_ms": 2500,
            "exit_code": 0,
            "status": "exited",
        },
        {
            "program_id": "pyscript:pyscripts/run_history_process.py",
            "invoked_name": "run_history_process",
            "argv": ("python", "run_history_process.py", "--interactive"),
            "cwd": "/work",
            "origin": "launcher",
            "delta_sec": 100,
            "duration_ms": 12000,
            "exit_code": 130,
            "status": "interrupted",
        },
    ]

    for rec in records:
        start_time = base_time + timedelta(seconds=rec["delta_sec"])
        inv_id = store.start_invocation(
            program_id=rec["program_id"],
            invoked_name=rec["invoked_name"],
            argv=rec["argv"],
            cwd=rec["cwd"],
            origin=rec["origin"],
            started_at_utc=start_time.isoformat(),
        )
        finish_time = start_time + timedelta(milliseconds=rec["duration_ms"])
        store.finish_invocation(
            inv_id,
            exit_code=rec["exit_code"],
            status=rec["status"],
            finished_at_utc=finish_time.isoformat(),
        )

    return {
        "programs": {
            "module:mangadl": {
                "total_starts": 5,
                "success_count": 3,
                "failure_count": 2,
                "pattern_count": 4,
            },
            "module:compresser": {
                "total_starts": 3,
                "success_count": 2,
                "failure_count": 1,
                "pattern_count": 3,
            },
            "pyscript:pyscripts/run_history_process.py": {
                "total_starts": 2,
                "success_count": 1,
                "failure_count": 1,
                "pattern_count": 2,
            },
        },
        "pattern_count": 9,
        "total_invocations": len(records),
    }
