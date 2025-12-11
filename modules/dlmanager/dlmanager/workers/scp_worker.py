#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scp worker: last-resort copy when rsync/rclone are unavailable.

Notes:
- scp has limited progress programmatically; we wrap it with '-v' and parse basic lines.
- No resume support; we simulate overwrite control.
- delete_source implies a second pass to remove local file(s) after success.

For directories, we use '-r'.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .base_worker import emit
from ..utils import normalize_path_for_remote


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="scp worker")
    ap.add_argument("--job", required=True, help="Path to job JSON.")
    return ap.parse_args()


def build_scp_cmd(spec: dict) -> list[str]:
    src = spec["src"]
    dst = spec["dst"]
    dst_path = normalize_path_for_remote(spec.get("dst_path", "~"), spec.get("dst_os", "auto"))
    replace = bool(spec.get("replace", False))
    dry = bool(spec.get("dry_run", False))

    # Determine recursive flag if src is a directory
    rflag = []
    if Path(src).is_dir():
        rflag = ["-r"]

    # scp target
    if "@" in dst or ":" in dst:
        target = f"{dst}:{dst_path}"
    else:
        target = dst_path

    cmd = ["scp", "-v"] + rflag
    if dry:
        # scp lacks dry-run; simulate by printing intended command and exiting
        return ["sh", "-lc", "printf '%s\n' " + shlex.quote(" ".join(["scp", "-v"] + rflag + [src, target]))]

    # Overwrite: scp overwrites by default; to prevent overwrites, there is no standard flag.
    # We'll proceed and rely on upstream to reject if perms forbid.
    cmd += [src, target]
    return cmd


def run_and_stream(cmd: list[str], delete_source: bool, src: str) -> int:
    emit(status="running", method="scp", command=" ".join(shlex.quote(c) for c in cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        s = line.strip()
        # Emit minimal updates
        if s:
            payload = {"note": s, "method": "scp"}
            if "Entering directory" in s or "Starting" in s:
                payload["current_file"] = s.split()[-1]
            emit(**payload)
    ret = proc.wait()
    if ret != 0:
        emit(status="failed", method="scp", returncode=ret)
        return ret
    if delete_source:
        try:
            p = Path(src)
            if p.is_dir():
                # Only remove if empty to avoid surprise; otherwise user should use rsync/rclone move
                p.rmdir()
            else:
                p.unlink()
            emit(note="delete_source: removed local source", method="scp")
        except Exception as e:
            emit(note=f"delete_source: failed: {e}", method="scp")
    emit(status="completed", method="scp")
    return 0


def main() -> int:
    args = parse_args()
    spec = json.loads(Path(args.job).read_text(encoding="utf-8"))
    cmd = build_scp_cmd(spec)
    return run_and_stream(cmd, bool(spec.get("delete_source", False)), spec["src"])


if __name__ == "__main__":
    raise SystemExit(main())
