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
import re
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

    base = ["rclone", "-P", "--stats=1s", "--stats-one-line", "--use-json-log"]
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


_SIZE_RE = re.compile(r"(?P<value>[\d.]+)\s*(?P<unit>[KMGTP]?i?B)", re.IGNORECASE)


def _size_to_bytes(token: str) -> float:
    token = token.strip()
    m = _SIZE_RE.match(token)
    if not m:
        return 0.0
    value = float(m.group("value"))
    unit = m.group("unit").lower()
    multipliers = {
        "b": 1,
        "kb": 1024,
        "kib": 1024,
        "mb": 1024**2,
        "mib": 1024**2,
        "gb": 1024**3,
        "gib": 1024**3,
        "tb": 1024**4,
        "tib": 1024**4,
        "pb": 1024**5,
        "pib": 1024**5,
    }
    return value * multipliers.get(unit, 1)


def _parse_eta(token: str) -> float | None:
    token = token.strip()
    if token in ("ETA -", "-"):
        return None
    # Formats like "ETA 1m23s", "ETA 4m", "ETA 2h3m4s"
    token = token.replace("ETA", "").strip()
    if token == "-":
        return None
    total = 0
    num = ""
    for ch in token:
        if ch.isdigit() or ch == ".":
            num += ch
            continue
        if not num:
            continue
        value = float(num)
        if ch == "h":
            total += value * 3600
        elif ch == "m":
            total += value * 60
        elif ch == "s":
            total += value
        num = ""
    if num:
        total += float(num)
    return total or None


def parse_stats_message(msg: str) -> dict | None:
    msg = msg.strip()
    if not msg.lower().startswith("transferred:"):
        return None
    parts = [p.strip() for p in msg.split(",")]
    if not parts:
        return None
    try:
        first = parts[0].split(":", 1)[1].strip()
        done_txt, total_txt = [s.strip() for s in first.split("/", 1)]
    except (IndexError, ValueError):
        return None

    payload: dict = {
        "bytes_done": _size_to_bytes(done_txt),
        "bytes_total": _size_to_bytes(total_txt),
    }
    if len(parts) > 1 and parts[1].endswith("%"):
        try:
            payload["percent"] = float(parts[1].rstrip("%"))
        except ValueError:
            pass
    if len(parts) > 2:
        payload["speed_text"] = parts[2]
        payload["bytes_per_s"] = _size_to_bytes(parts[2].rstrip("/s"))
    if len(parts) > 3:
        payload["eta_seconds"] = _parse_eta(parts[3])
    return payload


def run_and_stream(cmd: list[str], job_id: str) -> int:
    emit(status="running", method="rclone", transfer_id=job_id, command=" ".join(shlex.quote(c) for c in cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = evt.get("msg", "")
        parsed = parse_stats_message(msg)
        if parsed:
            emit(status="running", method="rclone", transfer_id=job_id, current_file=evt.get("object"), **parsed)
    ret = proc.wait()
    emit(status="completed" if ret == 0 else "failed", method="rclone", transfer_id=job_id, returncode=ret)
    return ret


def main() -> int:
    args = parse_args()
    spec = json.loads(Path(args.job).read_text(encoding="utf-8"))
    cmd = build_rclone_cmd(spec)
    return run_and_stream(cmd, spec.get("id", "unknown"))


if __name__ == "__main__":
    raise SystemExit(main())
