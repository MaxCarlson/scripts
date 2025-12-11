#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rsync worker: runs rsync and parses --info=progress2 output using procparsers.

Requirements:
- rsync must be installed locally.
- For remote Windows (Cygwin), ensure ssh server + cygwin rsync are available.

Uses procparsers.iter_parsed_events() for robust parsing of rsync output.
Emits JSONL progress updates to stdout for the manager to consume.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

try:
    from procparsers import iter_parsed_events
    PROCPARSERS_AVAILABLE = True
except ImportError:
    PROCPARSERS_AVAILABLE = False

from .base_worker import emit
from ..utils import normalize_path_for_remote, LOGS_DIR


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="rsync worker")
    ap.add_argument("-j", "--job", required=True, help="Path to job JSON.")
    return ap.parse_args()


def build_rsync_cmd(spec: dict) -> list[str]:
    """Build rsync command from job spec."""
    src = spec["src"]
    dst = spec["dst"]
    dst_path = normalize_path_for_remote(spec.get("dst_path", "~"), spec.get("dst_os", "auto"))
    replace = bool(spec.get("replace", False))
    delete_source = bool(spec.get("delete_source", False))
    resume = bool(spec.get("resume", True))  # rsync supports partials well
    dry = bool(spec.get("dry_run", False))

    # Destination rsync target (ssh remote or local)
    # If dst contains '@' or ':' assume remote. Else, local path copy.
    if ("@" in dst) or (":" in dst and not dst.startswith("rclone:")):
        target = f"{dst}:{dst_path}"
    else:
        target = dst_path  # local destination dir

    base_flags = [
        "rsync",
        "-a",            # archive (perm/time/links)
        "-h",            # human-readable
        "--info=progress2",
    ]

    if replace:
        # allow overwrite (default). If we wanted skip-existing: use --ignore-existing
        pass
    else:
        base_flags.append("--ignore-existing")

    if resume:
        base_flags.extend(["--partial", "--append-verify"])

    if delete_source:
        base_flags.append("--remove-source-files")

    if dry:
        base_flags.append("--dry-run")

    # Preserve extended attributes if possible (best-effort)
    # (On some Android/Termux, may not apply; harmless if unsupported)
    base_flags.append("-X")

    cmd = base_flags + [src.rstrip("/"), target]
    return cmd


def run_and_stream(cmd: list[str], job_id: str) -> int:
    """
    Run rsync command and stream progress events.

    Uses procparsers to parse rsync output and emit normalized JSONL events.
    """
    # Emit starting status
    emit(
        event="start",
        status="running",
        transfer_id=job_id,
        method="rsync",
        command=" ".join(shlex.quote(c) for c in cmd),
    )

    # Start rsync process
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    if not PROCPARSERS_AVAILABLE:
        # Fallback: just relay raw output
        assert proc.stdout is not None
        for line in proc.stdout:
            emit(event="raw", line=line.strip())
        ret = proc.wait()
        emit(
            event="finish",
            status="completed" if ret == 0 else "failed",
            returncode=ret,
            method="rsync",
        )
        return ret

    # Use procparsers for robust parsing
    raw_log_path = LOGS_DIR / f"{job_id}.rsync.raw.log"
    assert proc.stdout is not None

    try:
        for evt in iter_parsed_events("rsync", proc.stdout, raw_log_path=raw_log_path, heartbeat_secs=0.5):
            # Skip heartbeat events (internal to procparsers)
            if evt.get("event") == "heartbeat":
                continue

            # Enrich event with transfer metadata
            evt["transfer_id"] = job_id
            evt["method"] = "rsync"

            # Map procparser events to worker event types
            event_type = evt.get("event")

            if event_type == "progress":
                emit(
                    event="progress",
                    status="running",
                    transfer_id=job_id,
                    method="rsync",
                    percent=evt.get("percent"),
                    bytes_dl=evt.get("downloaded"),
                    total_bytes=evt.get("total"),
                    speed_bps=evt.get("speed_bps"),
                    eta_s=evt.get("eta_s"),
                    files_done=evt.get("files_done"),
                    files_total=evt.get("files_total"),
                )

            elif event_type == "file":
                # Emit file transfer event
                emit(
                    event="file",
                    transfer_id=job_id,
                    method="rsync",
                    current_file=evt.get("path"),
                )

            elif event_type == "summary":
                # Emit summary stats
                emit(
                    event="summary",
                    transfer_id=job_id,
                    method="rsync",
                    files_transferred=evt.get("files_transferred"),
                    total_size=evt.get("total_size"),
                )

    except Exception as e:
        emit(
            event="error",
            transfer_id=job_id,
            method="rsync",
            error=str(e),
        )
        try:
            proc.kill()
        except Exception:
            pass
        return 1

    # Wait for process completion
    ret = proc.wait()

    # Emit final status
    emit(
        event="finish",
        transfer_id=job_id,
        method="rsync",
        status="completed" if ret == 0 else "failed",
        returncode=ret,
    )

    return ret


def main() -> int:
    args = parse_args()

    # Load job spec
    spec = json.loads(Path(args.job).read_text(encoding="utf-8"))
    job_id = spec.get("id", "unknown")

    # Build and run rsync command
    cmd = build_rsync_cmd(spec)
    return run_and_stream(cmd, job_id)


if __name__ == "__main__":
    raise SystemExit(main())
