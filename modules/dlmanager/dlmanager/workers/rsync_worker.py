#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rsync worker: runs rsync and parses --info=progress2 output.

Requirements:
- rsync must be installed locally.
- For remote Windows (Cygwin), ensure ssh server + cygwin rsync are available.

We use a JSON job file produced by the manager. The worker resolves flags based
on job options (replace/resume/delete_source/etc).

Parsing:
- With --info=progress2, rsync prints lines like:
    1,234,567  12%   12.34MB/s    0:01:23 (xfr#5, to-chk=10/123)
- We'll also attempt to parse per-file lines when available.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from .base_worker import emit, RateCounter
from ..utils import normalize_path_for_remote

PROGRESS_RE = re.compile(
    r"^\s*(?P<bytes>\d+)\s+(?P<pct>\d+)%\s+(?P<rate>[\d\.]+)(?P<rate_unit>[KMG]?B)/s\s+(?P<eta>\S+)\s+\(xfr#(?P<xfr>\d+),\s+to-chk=(?P<tochk>\d+)/(?P<total>\d+)\)"
)
FILE_LINE_RE = re.compile(r"^\s*(?P<size>\d+)\s+(?P<path>.+)$")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="rsync worker")
    ap.add_argument("--job", required=True, help="Path to job JSON.")
    return ap.parse_args()


def kb_to_bytes(val: float, unit: str) -> int:
    unit = unit.upper()
    mult = 1
    if unit == "KB":
        mult = 1024
    elif unit == "MB":
        mult = 1024 ** 2
    elif unit == "GB":
        mult = 1024 ** 3
    return int(val * mult)


def build_rsync_cmd(spec: dict) -> list[str]:
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


def run_and_stream(cmd: list[str]) -> int:
    # Emit starting status
    emit(status="running", method="rsync", command=" ".join(shlex.quote(c) for c in cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    ratec = RateCounter()
    total_bytes = 0
    files_done = 0
    files_total = None

    assert proc.stdout is not None
    for line in proc.stdout:
        s = line.strip()
        if not s:
            continue

        # Parse combined progress line
        m = PROGRESS_RE.match(s.replace(",", ""))
        if m:
            b = int(m.group("bytes"))
            pct = int(m.group("pct"))
            rate_val = float(m.group("rate"))
            rate_unit = m.group("rate_unit")
            rate_bps = kb_to_bytes(rate_val, rate_unit)
            tochk = int(m.group("tochk"))
            total = int(m.group("total"))
            files_total = total
            files_done = total - tochk
            total_bytes = b
            emit(
                bytes_done=b,
                bytes_total=None,  # rsync doesn't always provide global total
                bytes_per_s=rate_bps,
                files_done=files_done,
                files_total=files_total,
            )
            continue

        # Try to catch per-file summaries (size + path)
        fm = FILE_LINE_RE.match(s.replace(",", ""))
        if fm:
            sz = int(fm.group("size"))
            path = fm.group("path")
            total_bytes += 0  # unknown increment robustly; leave counter to PROGRESS_RE
            emit(current_file=path, last_file_bytes=sz)
            continue

        # Emit raw line as 'note' occasionally
        # (Avoid flooding; only on interesting markers)
        if s.lower().startswith("sending") or s.lower().startswith("sent "):
            emit(note=s)

    ret = proc.wait()
    if ret == 0:
        emit(status="completed")
    else:
        emit(status="failed", returncode=ret)
    return ret


def main() -> int:
    args = parse_args()
    spec = json.loads(Path(args.job).read_text(encoding="utf-8"))
    cmd = build_rsync_cmd(spec)
    return run_and_stream(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
