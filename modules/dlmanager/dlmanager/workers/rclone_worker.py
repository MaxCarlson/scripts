#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rclone worker: uses rclone to copy/move with progress parsing.

Supports:
- Local -> remote (e.g., gdrive:bucket/path) or remote -> local
- Overwrite control
- Move semantics (delete_source)

We prefer `rclone copy` for safety; if delete_source is requested, we use `rclone move`.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from .base_worker import emit
from ..utils import normalize_path_for_remote


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="rclone worker")
    ap.add_argument("--job", required=True, help="Path to job JSON.")
    return ap.parse_args()


def build_rclone_cmd(spec: dict) -> list[str]:
    src = spec["src"]
    dst = spec["dst"]
    dst_path = normalize_path_for_remote(spec.get("dst_path", "~"), spec.get("dst_os", "auto"))
    replace = bool(spec.get("replace", False))
    delete_source = bool(spec.get("delete_source", False))
    dry = bool(spec.get("dry_run", False))

    # For rclone: dst may already be like "gdrive:folder"
    # If not, compose "dst:dst_path" when dst looks like rclone remote.
    if ":" in dst and not dst.startswith(("ssh://", "http://", "https://")):
        target = f"{dst}:{dst_path}" if ":" not in dst_path else dst_path
    else:
        # local path (or mount)
        target = dst_path

    base = ["rclone", "-P"]
    if delete_source:
        op = "move"
    else:
        op = "copy"
    cmd = base + [op]

    if replace:
        # default is overwrite-if-newer; to force overwrite use --ignore-times?
        # We'll keep default; add flag for overwrite aggressively:
        cmd.append("--ignore-times")
    else:
        cmd.append("--ignore-existing")

    if dry:
        cmd.append("--dry-run")

    # Robust retries and chunk sizes (esp. for Drive)
    cmd += ["--retries", "10", "--low-level-retries", "20", "--drive-chunk-size", "128M"]

    # Accept SRC as-is (can be local path or remote:)
    cmd += [src, target]
    return cmd


def parse_progress(line: str) -> dict:
    """
    `rclone -P` emits lines like:
    *   current_file:  12% /123.456M, 1.234M/s, ETA 01:23
    *   Transferred:    3.456 GiB / 10.000 GiB, 34%, 5.210 MiB/s, ETA 20m37s
    We'll extract the aggregate "Transferred:" line if present.
    """
    line = line.strip()
    out: dict = {}
    if line.lower().startswith("transferred:"):
        # Try to parse "X / Y, PCT, RATE, ETA"
        # Keep a light touch: just surface the line to the UI
        out["aggregate"] = line
    elif "%" in line and "/s" in line and "," in line:
        # Heuristic: current file progress
        out["current_line"] = line
    return out


def run_and_stream(cmd: list[str]) -> int:
    emit(status="running", method="rclone", command=" ".join(shlex.quote(c) for c in cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        data = parse_progress(line)
        if data:
            emit(**data)
    ret = proc.wait()
    if ret == 0:
        emit(status="completed")
    else:
        emit(status="failed", returncode=ret)
    return ret


def main() -> int:
    args = parse_args()
    spec = json.loads(Path(args.job).read_text(encoding="utf-8"))
    cmd = build_rclone_cmd(spec)
    return run_and_stream(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
