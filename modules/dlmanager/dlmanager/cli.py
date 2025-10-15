#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dlmanager CLI entry point.

Design goals:
- One long-running "manager" process monitors a filesystem-backed job queue (~/.dlmanager/queue).
- Users can:
  1) Start the manager TUI/process: `dlmanager --manager`
  2) Enqueue a new transfer: `dlmanager add --src ... --dst ... [--dst-path ...] [--method auto|rsync|rclone|scp] ...`
- If a manager is already running, new jobs are picked up automatically.
- If no manager is running, jobs are still written to the queue and a hint is printed.

IPC model:
- Queue: JSON job files dropped in ~/.dlmanager/queue/*.json
- Workers: separate scripts that stream JSON status lines to stdout, which the manager consumes.

Cross-platform:
- Windows 11 (PowerShell/WSL), Linux (WSL2/Ubuntu), Android Termux.
- No privileged operations required.

All public CLI args expose both short and long flags.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from .manager import Manager, DEFAULT_POLL_INTERVAL
from .utils import (
    ensure_runtime_dirs,
    guess_local_platform,
    which_or_none,
    now_iso,
)

APP_NAME = "dlmanager"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dlmanager",
        description="Multi-method transfer manager (rsync, rclone, scp, ...).",
    )
    sub = p.add_subparsers(dest="command", required=False)

    # Start manager (foreground)
    mgr = sub.add_parser("manager", help="Run the manager (foreground TUI).")
    mgr.add_argument(
        "-i",
        "--poll_interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Job-queue poll interval seconds (default {DEFAULT_POLL_INTERVAL}).",
    )

    # Add a new transfer job
    add = sub.add_parser("add", help="Enqueue a new transfer.")
    add.add_argument("-s", "--src", required=True, help="Source path (local) or spec.")
    add.add_argument(
        "-d",
        "--dst",
        required=True,
        help="Destination host spec. "
             "Local path is allowed; remote forms: user@host, ssh alias, or rclone remote:",
    )
    add.add_argument(
        "-p",
        "--dst_path",
        default="~",
        help="Destination path (default: ~/). For rclone, can be 'remote:path'.",
    )
    add.add_argument(
        "-m",
        "--method",
        choices=["auto", "rsync", "rclone", "scp"],
        default="auto",
        help="Transfer method to use. 'auto' will try best-to-worst.",
    )
    add.add_argument(
        "-r", "--replace",
        action="store_true",
        help="Replace/overwrite existing destination files when conflicts occur.",
    )
    add.add_argument(
        "-x", "--delete_source",
        action="store_true",
        help="Delete source files after successful transfer (move semantics).",
    )
    add.add_argument(
        "-R", "--resume",
        action="store_true",
        help="Allow partial/resumable transfers if supported by method.",
    )
    add.add_argument(
        "-n", "--dry_run",
        action="store_true",
        help="Plan but do not execute the transfer.",
    )
    add.add_argument(
        "-t", "--tags",
        nargs="*",
        default=[],
        help="Optional tags/labels for this job (e.g., 'termux', 'home->w11').",
    )
    add.add_argument(
        "-o", "--dst_os",
        choices=["auto", "linux", "windows-cygwin", "windows-native"],
        default="auto",
        help="Destination OS for path normalization and rsync/scp flags.",
    )
    add.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose manager logs for this job.",
    )
    add.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Reduce console noise.",
    )

    # Show environment / diagnostics
    diag = sub.add_parser("doctor", help="Environment checks & diagnostics.")
    diag.add_argument("-v", "--verbose", action="store_true", help="Verbose output.")

    # Convenience: default to help if no subcommand
    return p


def cmd_manager(args: argparse.Namespace) -> int:
    ensure_runtime_dirs()
    m = Manager(poll_interval=args.poll_interval)
    # Foreground run with a simple TUI-ish printer
    try:
        m.run_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Manager stopping (Ctrl-C).")
    return 0


def generate_job(args: argparse.Namespace) -> dict:
    # Normalize/prepare a job descriptor
    job = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "src": args.src,
        "dst": args.dst,
        "dst_path": args.dst_path,
        "method": args.method,
        "replace": bool(args.replace),
        "delete_source": bool(args.delete_source),
        "resume": bool(args.resume),
        "dry_run": bool(args.dry_run),
        "dst_os": args.dst_os,
        "tags": args.tags,
        "verbose": bool(args.verbose),
        "quiet": bool(args.quiet),
        "submitter_platform": guess_local_platform(),
        "status": "queued",
    }
    return job


def write_job_to_queue(job: dict, queue_dir: Path) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    job_path = queue_dir / f"job_{job['id']}.json"
    with job_path.open("w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)
    return job_path


def cmd_add(args: argparse.Namespace) -> int:
    ensure_runtime_dirs()
    from .manager import QUEUE_DIR, PID_FILE

    job = generate_job(args)
    job_path = write_job_to_queue(job, QUEUE_DIR)

    # Give user feedback
    print(f"[INFO] Enqueued job: {job['id']}")
    print(f"[INFO] Queue file: {job_path}")

    # Hint about manager
    if PID_FILE.exists():
        print("[INFO] Manager appears to be running. It will pick up this job shortly.")
    else:
        print("[WARN] No running manager detected.")
        print("       Start it with:  dlmanager manager")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print("== dlmanager doctor ==")
    print(f"- Platform guess: {guess_local_platform()}")
    for tool in ("rsync", "rclone", "scp", "ssh"):
        path = which_or_none(tool)
        print(f"- which {tool}: {path or 'NOT FOUND'}")
    print(f"- Runtime dir: {ensure_runtime_dirs()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "manager":
        return cmd_manager(args)
    if args.command == "add":
        return cmd_add(args)
    if args.command == "doctor":
        return cmd_doctor(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
