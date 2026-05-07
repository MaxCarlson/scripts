#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Master downloader that coordinates multiple dlscript.py workers.

- Scans URL files under ./files/downloads/ae-stars and ./files/downloads/stars
- Runs up to -t workers (each runs dlscript.py on one URL file at a time)
- Prioritises URL files using urlscan metrics (ratio/remaining/etc) and optional -p list
- Enforces a per-assignment time limit (-T seconds; -1 disables)
- Tracks per-worker progress by reading dlscript NDJSON and renders a live dashboard
- Records finished URL files in a log so they are not reassigned
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import random
import signal
import subprocess
import sys
import datetime
import threading
import time
import traceback
import types
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

# Import EnforcedArgumentParser with fallback
try:
    from argparse_enforcer import EnforcedArgumentParser

    ENFORCER_AVAILABLE = True
except ImportError:
    EnforcedArgumentParser = argparse.ArgumentParser
    ENFORCER_AVAILABLE = False

from . import archive_builder, urlscan, yt_grid
from .domain_index import DomainIndex, ScanLogEntry, _extract_domain as _domain_of_url
from .downloader import MAX_RESOLUTION_CHOICES
from .mp4_watcher import MP4Watcher, WatcherConfig, WatcherSnapshot
from termdash import utils as td_utils

MP4_VALID_OPERATIONS = ("copy", "move")
WATCHER_LOG_STATUS_COLOURS = {
    "MOVE": "green",
    "COPY": "cyan",
    "DELETE": "red",
    "REPLACE": "magenta",
    "SKIP": "yellow",
    "START": "cyan",
    "FINISH": "green",
    "FINISH_BAD": "red",
    "INFO": "bright",
    "ERROR": "red",
    "DRYRUN": "yellow",
    "SCAN": "cyan",
    "PLAN": "cyan",
    "WARN": "yellow",
    "MODE": "cyan",
    "LIMIT": "yellow",
    "TRIGGER": "yellow",
    "STATE": "cyan",
    "AUTO": "magenta",
    "CONFIG": "bright",
}
GIB = 1024**3
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
SIZE_RE = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[kmgtp]?i?b)?\s*$", re.I)
URL_PANEL_AUTO_INTERVAL = 10.0
URL_PANEL_SORT_CYCLE = (
    ("ratio", False),
    ("ratio", True),
    ("stars", False),
    ("remaining", False),
    ("gb", False),
    ("unique", False),
)

# Use TermDash for robust in-place dashboard rendering
# We avoid TermDash here for maximal compatibility across shells; do manual frames


class ManagerLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, msg: str) -> None:
        # Best-effort cross-process lock
        try:
            import msvcrt  # type: ignore
        except Exception:
            msvcrt = None  # type: ignore
        try:
            import fcntl  # type: ignore
        except Exception:
            fcntl = None  # type: ignore
        with self.path.open("a", encoding="utf-8") as f:
            try:
                if msvcrt and os.name == "nt":
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1_000_000)
                elif fcntl and os.name != "nt":
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            try:
                f.write(msg + "\n")
                f.flush()
            finally:
                try:
                    if msvcrt and os.name == "nt":
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1_000_000)
                    elif fcntl and os.name != "nt":
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

    def info(self, msg: str) -> None:
        t = time.strftime("%H:%M:%S")
        self._write(f"{t}|INFO|{msg}")

    def error(self, msg: str) -> None:
        t = time.strftime("%H:%M:%S")
        self._write(f"{t}|ERROR|{msg}")


def _read_urls(path: Path) -> List[str]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(";") or s.startswith("]"):
            continue
        out.append(s.split("  #", 1)[0].split("  ;", 1)[0].strip())
    # stable de-dup
    return list(dict.fromkeys(out))


def _top_domain(url: Optional[str]) -> str:
    if not url:
        return "-"
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return "-"
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return "-"
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host or "-"


def _domains_for_urls(urls: Sequence[str]) -> set[str]:
    return {domain for domain in (_top_domain(url) for url in urls) if domain != "-"}


def _domains_for_urlfile(path: Path) -> set[str]:
    try:
        return _domains_for_urls(_read_urls(path))
    except Exception:
        return set()


def _domain_diversity_score(path: Path, active_domains: set[str], candidate_domains: Dict[str, set[str]]) -> int:
    domains = candidate_domains.get(str(path.resolve()), set())
    if not domains:
        return 0
    return len(domains - active_domains)


def _choose_domain_diverse_candidate(
    candidates: List[Path],
    rankings: Dict[str, int],
    candidate_domains: Dict[str, set[str]],
    active_domains: set[str],
    temperature: float,
    *,
    rng=random,
) -> Path:
    if not candidates:
        raise ValueError("No URL candidates to choose from")
    scored = sorted(
        candidates,
        key=lambda p: (
            -_domain_diversity_score(p, active_domains, candidate_domains),
            rankings.get(str(p.resolve()), len(candidates)),
            str(p),
        ),
    )
    if temperature <= 0:
        return scored[0]
    weights = []
    for idx, path in enumerate(scored):
        score = _domain_diversity_score(path, active_domains, candidate_domains)
        weights.append(math.exp(((score * 4.0) - idx) / max(temperature, 1e-9)))
    total = sum(weights)
    pick = rng.random() * total
    cumulative = 0.0
    for candidate, weight in zip(scored, weights):
        cumulative += weight
        if pick <= cumulative:
            return candidate
    return scored[-1]


def _human_bytes(b: Optional[float | int]) -> str:
    if b is None:
        return "?"
    v = float(b)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    while v >= 1024.0 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    return f"{v:.2f}{units[i]}"


def _parse_size_bytes(value: str) -> Optional[int]:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"0", "none", "off", "disable", "disabled", "unlimited"}:
        return None
    match = SIZE_RE.match(raw)
    if not match:
        raise argparse.ArgumentTypeError("expected a size like 1024MB, 100GB, or unlimited")
    number = float(match.group("value"))
    unit = (match.group("unit") or "B").lower()
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
    if unit not in multipliers:
        raise argparse.ArgumentTypeError("expected units B, KB, MB, GB, TB, KiB, MiB, GiB, or TiB")
    bytes_value = int(number * multipliers[unit])
    return bytes_value if bytes_value > 0 else None


def _parse_url_pick_temperature(value: str) -> float:
    try:
        temperature = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("expected a non-negative number") from exc
    if temperature < 0:
        raise argparse.ArgumentTypeError("expected a non-negative number")
    return temperature


def _cycle_url_sort(current_key: str, current_ascending: bool) -> tuple[str, bool]:
    current = (current_key, current_ascending)
    try:
        idx = URL_PANEL_SORT_CYCLE.index(current)
    except ValueError:
        idx = -1
    return URL_PANEL_SORT_CYCLE[(idx + 1) % len(URL_PANEL_SORT_CYCLE)]


def _weighted_rank_choice(
    candidates: List[Path],
    rankings: Dict[str, int],
    temperature: float,
    *,
    rng=random,
) -> Path:
    ordered = sorted(
        candidates,
        key=lambda p: (rankings.get(str(p.resolve()), len(candidates)), str(p)),
    )
    if not ordered:
        raise ValueError("No URL candidates to choose from")
    if temperature <= 0:
        return ordered[0]
    weights = [math.exp(-(idx / max(temperature, 1e-9))) for idx, _ in enumerate(ordered)]
    total = sum(weights)
    pick = rng.random() * total
    cumulative = 0.0
    for candidate, weight in zip(ordered, weights):
        cumulative += weight
        if pick <= cumulative:
            return candidate
    return ordered[-1]


def _format_download_bytes(value: Optional[int | float]) -> str:
    return td_utils.format_bytes_binary(value)


def _format_download_rate(value: Optional[int | float]) -> str:
    return td_utils.format_rate_bps(value)


def _format_disk_bytes(value: Optional[int | float]) -> str:
    return td_utils.format_bytes_decimal(value)


def _human_short_bytes(b: Optional[int]) -> str:
    if b is None:
        return "?"
    return td_utils.format_bytes_binary(b).replace(" ", "")


def _hms(elapsed_s: float) -> str:
    s = int(elapsed_s) % 60
    m = (int(elapsed_s) // 60) % 60
    h = int(elapsed_s) // 3600
    return f"{h:02d}:{m:02d}:{s:02d}"


def _watcher_bytes(value: Optional[int | float]) -> str:
    if not isinstance(value, (int, float)) or value < 0:
        return "0 B"
    return td_utils.format_bytes_binary(value)


def _watcher_rate(bps: Optional[float]) -> str:
    return td_utils.format_rate_bps(bps)


def _watcher_duration(seconds: Optional[float]) -> str:
    return td_utils.format_duration_hms(seconds)


def _watcher_trigger_label(value: Optional[int]) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return "disabled"
    gib = float(value) / (1024**3)
    return f"{gib:.1f} GiB"


def _controlled_quit_eta_label(workers: Sequence["WorkerState"]) -> str:
    active = [worker for worker in workers if worker.proc and not worker.is_paused]
    if not active:
        return "0s"
    if any(not isinstance(worker.eta_s, (int, float)) for worker in active):
        return "?"
    eta_s = max(0, int(round(max(float(worker.eta_s or 0) for worker in active))))
    return f"{eta_s}s"


def _controlled_quit_complete(enabled: bool, workers: Sequence["WorkerState"]) -> bool:
    return bool(enabled) and all(worker.proc is None for worker in workers)


def _downloads_footer_text() -> str:
    return (
        "Keys: w=watcher, u=url stats, d=downloads, Up/Down=select worker, "
        "P=toggle selected, p=pause/unpause all, x=controlled quit, h=toggle status, "
        "q=quit, v=cycle verbose, digit=prompt worker number"
    )


def _watcher_keep_source_label(config: WatcherConfig) -> str:
    label = td_utils.color_text("on", "green") if config.keep_source else td_utils.color_text("off", "yellow")
    return label


def _colorize_log_continuation(clean: str) -> str:
    """Apply semantic colours to a log continuation line (one not starting with '[')."""
    stripped = clean.lstrip()
    indent = clean[: len(clean) - len(stripped)]
    if stripped.startswith("KEEP") or stripped.startswith("KEPT"):
        tag, rest = stripped[:4], stripped[4:]
        return indent + td_utils.color_text(tag, "green") + rest
    if stripped.startswith("DEL"):
        tag, rest = stripped[:3], stripped[3:]
        return indent + td_utils.color_text(tag, "red") + rest
    if stripped.startswith("→"):
        arrow, rest = "→", stripped[1:]
        return indent + td_utils.color_text(arrow, "cyan") + rest
    if stripped.startswith("file:") or stripped.startswith("file "):
        colon_pos = stripped.index(":") + 1
        label = stripped[:colon_pos]
        rest = stripped[colon_pos:]
        return indent + td_utils.color_text(label, "bright") + rest
    return clean


def _format_watcher_log_line(line: str) -> str:
    stripped = line.rstrip()
    if not stripped:
        return ""
    clean = ANSI_ESCAPE_RE.sub("", stripped)
    # Continuation lines (written by log_event as separate records) start with spaces
    if not clean.startswith("["):
        return _colorize_log_continuation(clean)
    parts = clean.split(" ", 2)
    if len(parts) < 3:
        return clean
    timestamp = parts[0].strip("[]")
    status_raw = parts[1].strip()
    payload = parts[2] if len(parts) > 2 else ""
    status_clean = status_raw.strip("[]")
    colour = WATCHER_LOG_STATUS_COLOURS.get(status_clean, "")
    status_block = f"[{status_clean}]"
    if colour:
        status_block = td_utils.color_text(status_block, colour)
    timestamp_block = td_utils.color_text(f"[{timestamp}]", "gray")
    if payload:
        return f"{timestamp_block} {status_block} {payload}"
    return f"{timestamp_block} {status_block}"


def _read_watcher_log_lines(log_path: Optional[Path], max_lines: int) -> List[str]:
    if not log_path:
        return []
    try:
        path = Path(log_path)
    except Exception:
        return []
    if not path.exists():
        return []
    entries: deque[str] = deque(maxlen=max_lines)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                formatted = _format_watcher_log_line(raw.rstrip("\n"))
                if formatted:
                    entries.append(formatted)
    except Exception:
        return []
    return list(entries)


def _color_operation(op: Optional[str]) -> str:
    if not op:
        return "-"
    op_lower = op.lower()
    color = "yellow" if op_lower == "move" else "cyan"
    return td_utils.color_text(op_lower, color)


def _wrap_hotkey_lines(text: str, cols: int) -> List[str]:
    return td_utils.wrap_text(text, max(20, cols))


def _prepare_log_window(logs: List[str], available_rows: int, scroll: int) -> tuple[List[str], int]:
    if available_rows <= 0:
        return [], 0
    total = len(logs)
    max_scroll = max(0, total - available_rows)
    scroll = max(0, min(scroll, max_scroll))
    start = max(0, total - available_rows - scroll)
    end = start + available_rows
    return logs[start:end], max_scroll


def _apply_pinned_viewport(
    lines: List[str], *, rows: int, header_rows: int, footer_rows: int, scroll: int
) -> tuple[List[str], int]:
    if rows <= 0:
        return [], 0
    if len(lines) <= rows:
        return lines[:rows], 0
    header_rows = max(0, min(header_rows, len(lines)))
    footer_rows = max(0, min(footer_rows, max(0, len(lines) - header_rows)))
    header = lines[:header_rows]
    footer = lines[-footer_rows:] if footer_rows else []
    body = lines[header_rows : len(lines) - footer_rows if footer_rows else len(lines)]
    available_body_rows = max(0, rows - len(header) - len(footer))
    if available_body_rows <= 0:
        truncated_header = header[:rows]
        if len(truncated_header) < rows and footer:
            needed = rows - len(truncated_header)
            truncated_header.extend(footer[-needed:])
        return truncated_header[:rows], 0
    max_scroll = max(0, len(body) - available_body_rows)
    scroll = max(0, min(scroll, max_scroll))
    visible_body = body[scroll : scroll + available_body_rows]
    while len(visible_body) < available_body_rows:
        visible_body.append("")
    return header + visible_body + footer, max_scroll


def _ansi_visible_len(text: str) -> int:
    return len(urlscan.strip_ansi(text))


def _ansi_slice(text: str, start: int, width: int) -> str:
    if width <= 0:
        return ""
    result: List[str] = []
    printable = 0
    i = 0
    active = []
    while i < len(text):
        ch = text[i]
        if ch == "\x1b":
            j = text.find("m", i)
            if j == -1:
                break
            seq = text[i : j + 1]
            result.append(seq)
            if seq == "\x1b[0m":
                active.clear()
            else:
                active.append(seq)
            i = j + 1
            continue
        if start <= printable < start + width:
            result.append(ch)
        printable += 1
        if printable >= start + width:
            break
        i += 1
    if active:
        result.append("\x1b[0m")
    return "".join(result)


def _format_buffer_delta(delta_bytes: int) -> str:
    color = "green" if delta_bytes > 5 * GIB else "yellow" if delta_bytes >= 0 else "red"
    sign = "+" if delta_bytes >= 0 else "-"
    human = _format_disk_bytes(abs(delta_bytes))
    return td_utils.color_text(f"{sign}{human}", color)


def _storage_summary_lines(
    staging_stats: Optional[td_utils.DiskStats],
    destination_stats: Optional[td_utils.DiskStats],
    *,
    threshold_bytes: Optional[int],
    download_speed_bps: float,
) -> List[str]:
    lines: List[str] = []
    if not staging_stats and not destination_stats:
        return lines
    lines.append("Storage")
    if staging_stats:
        lines.append(
            _describe_storage("Staging", staging_stats, threshold_bytes, download_speed_bps, show_disabled=True)
        )
    if destination_stats:
        same = staging_stats and td_utils.same_disk(staging_stats, destination_stats)
        lines.append(
            _describe_storage(
                "Destination",
                destination_stats,
                threshold_bytes if same else None,
                download_speed_bps,
                same_volume=bool(same),
                show_disabled=bool(same),
            )
        )
    return lines


def _describe_storage(
    label: str,
    stats: td_utils.DiskStats,
    threshold_bytes: Optional[int],
    download_speed_bps: float,
    *,
    same_volume: bool = False,
    show_disabled: bool = False,
) -> str:
    free_str = _format_disk_bytes(stats.free_bytes)
    total_str = _format_disk_bytes(stats.total_bytes)
    line = f"{label}: {free_str} free / {total_str} total ({stats.label})"
    extras: List[str] = []
    if same_volume:
        extras.append("shares staging volume")
    if threshold_bytes and threshold_bytes > 0:
        delta = stats.free_bytes - threshold_bytes
        extras.append(f"buffer {_format_buffer_delta(delta)} @ {_format_disk_bytes(threshold_bytes)}")
        if delta > 0 and download_speed_bps > 0:
            eta = delta / download_speed_bps
            extras.append(f"ETA {td_utils.format_duration_hms(eta)}")
        elif delta <= 0:
            extras.append(td_utils.color_text("AUTO CLEAN NOW", "red"))
    elif show_disabled:
        extras.append("auto-halt disabled")
    if extras:
        line += " | " + " | ".join(extras)
    return line


def _render_screen(lines: List[str]) -> None:
    sys.stdout.write("\x1b[0m\x1b[2J\x1b[H")
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def _render_watcher_panel(
    *,
    cols: int,
    rows: int,
    watcher_enabled: bool,
    snapshot: Optional[WatcherSnapshot],
    quit_confirm: bool,
    manager_elapsed: float,
    total_downloaded_bytes: int,
    log_scroll: int,
    log_meta: Optional[Dict[str, int]],
    download_speed_bps: float,
    staging_stats: Optional[td_utils.DiskStats],
    destination_stats: Optional[td_utils.DiskStats],
    auto_trigger_bytes: Optional[int],
    auto_block_reason: Optional[str],
    destination_no_space: bool,
) -> List[str]:
    lines: List[str] = []
    header = "MP4 Folder Synchroniser"
    if snapshot:
        header_state = "running" if snapshot.running else "idle"
        if snapshot.dry_run:
            header_state += " · dry-run"
        header = f"{header} ({header_state})"
    lines.append(header[:cols])

    lines.append(f"Manager elapsed: {_hms(manager_elapsed)}"[:cols])
    lines.append(f"Total downloaded: {_watcher_bytes(total_downloaded_bytes)}"[:cols])
    if destination_no_space:
        lines.append(td_utils.color_text("NO DISK SPACE LEFT AT FINAL DESTINATION", "red")[:cols])
    lines.append("")

    cfg = snapshot.config if snapshot else None
    if cfg:
        lines.append("Configuration"[:cols])
        op_line = (
            f"Default op: {_color_operation(cfg.default_operation)} | Keep source: {_watcher_keep_source_label(cfg)}"
        )
        lines.append(op_line[:cols])
        if cfg.stay_at_staging:
            auto_tag = " (auto)" if (snapshot and snapshot.stay_at_staging_auto) else " (manual)"
            stay_label = td_utils.color_text(f"YES – files stay at staging{auto_tag}", "yellow")
        else:
            stay_label = "no"
        lines.append(f"Stay-at-staging: {stay_label}"[:cols])
        max_label = cfg.max_files if cfg.max_files is not None else "unlimited"
        trigger_bytes = cfg.free_space_trigger_bytes or auto_trigger_bytes
        lines.append(f"Max files/run: {max_label} | Free trigger: {_watcher_trigger_label(trigger_bytes)}"[:cols])
        lines.append(f"Staged size trigger: {_watcher_trigger_label(cfg.total_size_trigger_bytes)}"[:cols])
        reserve = (
            _format_disk_bytes(cfg.destination_space_remaining_bytes)
            if cfg.destination_space_remaining_bytes
            else "disabled"
        )
        lines.append(f"Destination reserve: {reserve}"[:cols])
        lines.append("")

    storage_lines = _storage_summary_lines(
        staging_stats,
        destination_stats,
        threshold_bytes=cfg.free_space_trigger_bytes if cfg else auto_trigger_bytes,
        download_speed_bps=download_speed_bps,
    )
    if storage_lines:
        for line in storage_lines:
            lines.append(line[:cols])
        lines.append("")
    if auto_block_reason:
        lines.append(td_utils.color_text(auto_block_reason, "yellow")[:cols])

    if not watcher_enabled:
        lines.append("Watcher disabled. Launch with --watcher to enable the cleaner."[:cols])
        lines.append("")
    elif snapshot:
        progress = snapshot.progress or {}
        if progress:
            lines.append("Cleaner Status"[:cols])
            lines.append(f"Elapsed: {_watcher_duration(progress.get('elapsed'))}"[:cols])
            lines.append(f"Current folder: {progress.get('current_folder') or '-'}"[:cols])
            lines.append(f"Current file: {progress.get('current_file') or '-'}"[:cols])
            lines.append(
                f"Files processed: {progress.get('processed_files', 0)} / {progress.get('total_files', 0)}"[:cols]
            )
            lines.append(
                f"Copied (no collision): {progress.get('copied_without_collision', 0)} | "
                f"Collisions: {progress.get('collisions', 0)} (replaced: {progress.get('replaced_dest', 0)}, kept: {progress.get('kept_dest', 0)})"[
                    :cols
                ]
            )
            total_prog_pct = progress.get("total_percent", 0.0)
            lines.append(
                f"Total progress: {_watcher_bytes(progress.get('processed_bytes', 0))} / "
                f"{_watcher_bytes(progress.get('total_bytes', 0))} ({total_prog_pct:.1f}%)"[:cols]
            )
            lines.append("")
            lines.append("Transfer Progress")
            if progress.get("current_file_size"):
                file_prog_pct = progress.get("file_percent", 0.0)
                rate = _watcher_rate(progress.get("current_speed", 0.0))
                lines.append(
                    f"File progress: {_watcher_bytes(progress.get('current_file_done', 0))} / "
                    f"{_watcher_bytes(progress.get('current_file_size', 0))} ({file_prog_pct:.1f}%) @ {rate}"[:cols]
                )

        pending_actions = snapshot.plan_actions or (
            snapshot.last_result.planned_actions if snapshot.last_result else None
        )
        pending_bytes = snapshot.plan_bytes or (snapshot.last_result.plan_bytes if snapshot.last_result else None)
        if pending_actions is not None or pending_bytes is not None:
            lines.append(
                f"Potential transfers: {pending_actions or 0} files | {_watcher_bytes(pending_bytes or 0)}"[:cols]
            )

        lines.append(f"Bytes since last run: {_watcher_bytes(snapshot.bytes_since_last or 0)}"[:cols])
        lines.append("")
    else:
        lines.append("(no snapshot yet)"[:cols])
        lines.append("")

    # Hotkey block (precompute for spacing)
    if quit_confirm:
        hotkey_lines = ["Press Y to quit, N to cancel"]
    else:
        hotkey_lines = _wrap_hotkey_lines(
            "Keys: d=downloads, u=url stats, c=start cleaner, s=scan (dry-run), o=toggle copy/move, "
            "t=toggle stay-at-staging, "
            "k=set max-files, f=set staging free GiB, m=set destination reserve, "
            "[=scroll log up, ]=scroll log down, q=quit",
            cols,
        )

    # Recent log section
    log_entries: List[str] = []
    log_path = snapshot.config.log_path if snapshot else None
    if log_path:
        log_entries = _read_watcher_log_lines(log_path, rows * 4)
    if not log_entries and snapshot and snapshot.progress:
        log_entries = snapshot.progress.get("recent_logs") or []
    control_lines = 1 + len(hotkey_lines)
    available_rows = max(5, rows - len(lines) - control_lines)
    window, max_scroll = _prepare_log_window(log_entries, available_rows, log_scroll)
    if log_meta is not None:
        log_meta["log_max_scroll"] = max_scroll
        log_meta["log_window"] = available_rows
        log_meta["log_total"] = len(log_entries)

    lines.append("Recent Activity"[:cols])
    if log_entries:
        lines.append(f"(showing {len(window)}/{len(log_entries)} – scroll {log_scroll}/{max_scroll})"[:cols])
        for entry in window:
            lines.append(entry[:cols])
        # pad if needed
        for _ in range(max(0, available_rows - len(window))):
            lines.append("")
    else:
        lines.append("(no events yet)"[:cols])
        for _ in range(max(0, available_rows - 1)):
            lines.append("")

    lines.append("-" * min(cols, 100))
    lines.extend(line[:cols] for line in hotkey_lines)
    return lines


def _prompt_text(prompt: str) -> Optional[str]:
    try:
        return input(f"\n{prompt.strip()} ").strip()
    except EOFError:
        return None


def _pause_process(proc: subprocess.Popen) -> bool:
    """Pause a process. Returns True if successful."""
    if not proc or proc.poll() is not None:
        return False

    try:
        if os.name == "nt":
            # Windows: use psutil if available, otherwise try native API
            try:
                import psutil

                p = psutil.Process(proc.pid)
                p.suspend()
                return True
            except ImportError:
                # Fallback: use Windows API via ctypes
                try:
                    import ctypes
                    from ctypes import wintypes

                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.OpenProcess(0x0200, False, proc.pid)  # PROCESS_SUSPEND_RESUME
                    if handle:
                        # Get thread IDs and suspend them
                        import ctypes.wintypes

                        class THREADENTRY32(ctypes.Structure):
                            _fields_ = [
                                ("dwSize", wintypes.DWORD),
                                ("cntUsage", wintypes.DWORD),
                                ("th32ThreadID", wintypes.DWORD),
                                ("th32OwnerProcessID", wintypes.DWORD),
                                ("tpBasePri", wintypes.LONG),
                                ("tpDeltaPri", wintypes.LONG),
                                ("dwFlags", wintypes.DWORD),
                            ]

                        # This is complex, so let's use a simpler approach
                        kernel32.CloseHandle(handle)
                        return False
                except Exception:
                    return False
        else:
            # Unix: use SIGSTOP
            os.kill(proc.pid, signal.SIGSTOP)
            return True
    except Exception:
        return False
    return False


def _resume_process(proc: subprocess.Popen) -> bool:
    """Resume a paused process. Returns True if successful."""
    if not proc or proc.poll() is not None:
        return False

    try:
        if os.name == "nt":
            # Windows: use psutil if available
            try:
                import psutil

                p = psutil.Process(proc.pid)
                p.resume()
                return True
            except ImportError:
                return False
        else:
            # Unix: use SIGCONT
            os.kill(proc.pid, signal.SIGCONT)
            return True
    except Exception:
        return False
    return False


@dataclass
class WorkerState:
    slot: int
    proc: Optional[subprocess.Popen] = None
    reader: Optional[threading.Thread] = None
    reader_stop: threading.Event = field(default_factory=threading.Event)
    urlfile: Optional[Path] = None
    canonical_dir: Optional[Path] = None
    url_count: int = 0
    url_index: Optional[int] = None
    url_current: Optional[str] = None
    downloader: Optional[str] = None
    percent: Optional[float] = None
    speed_bps: Optional[float] = None
    eta_s: Optional[float] = None
    downloaded_bytes: Optional[int] = None
    total_bytes: Optional[int] = None
    assign_t0: float = 0.0
    url_t0: float = 0.0
    last_event_time: float = 0.0
    destination: Optional[str] = None
    rc: Optional[int] = None
    cap_mibs: Optional[float] = None
    last_throttle_t: float = 0.0
    last_already: bool = False
    is_searching: bool = False  # True between a finish event and the next start event
    overlay_msg: Optional[str] = None
    overlay_since: float = 0.0
    ndjson_buf: list[str] = field(default_factory=list)
    prog_log_path: Optional[Path] = None
    is_paused: bool = False
    paused_speed_bps: Optional[float] = None
    controlled_stopped: bool = False
    is_waiting_domain: bool = False     # True when idle because all domain slots are taken
    waiting_domain_since: float = 0.0   # timestamp when domain-wait began
    domain_search_file: Optional[str] = None   # file currently being scanned for domain
    domain_search_progress: tuple = (0, 0)     # (checked_count, total_urls) during scan
    url_entry: Optional[object] = None          # DomainIndex UrlEntry for this assignment
    original_urlfile: Optional[Path] = None    # original URL file (before temp wrapping)
    worker_log_counter: int = 0                # counter for manager-written log entries
    progress_log_started: bool = False         # True after first manager-side PROGRESS written for current download
    last_progress_log_t: float = 0.0           # time of last manager-side PROGRESS entry
    ytdlp_grid_trial_id: Optional[str] = None
    ytdlp_grid_config: Optional[dict] = None
    ytdlp_grid_config_path: Optional[Path] = None
    ytdlp_grid_source_urlfile: Optional[str] = None
    ytdlp_grid_stats: Optional[yt_grid.GridRuntimeStats] = None
    ytdlp_grid_recorded: bool = False


def _normalize_active_progress(
    downloaded: object,
    total: object,
    percent: object,
    speed_bps: object,
) -> tuple[Optional[float], Optional[int], Optional[int]]:
    """Normalize an in-flight progress event without showing active transfers as done."""
    dl = downloaded if isinstance(downloaded, int) else None
    tot = total if isinstance(total, int) and total > 0 else None
    sp = float(speed_bps) if isinstance(speed_bps, (int, float)) else None
    pct = float(percent) if isinstance(percent, (int, float)) else None

    if dl is not None and tot is not None:
        pct_value = min(100.0, max(0.0, 100.0 * (float(dl) / float(tot))))
        if pct_value >= 100.0 and sp is not None and sp > 0:
            pct_value = 99.9
        return pct_value, dl, tot

    if pct is not None:
        pct_value = min(100.0, max(0.0, pct))
        if pct_value >= 100.0 and sp is not None and sp > 0:
            pct_value = 99.9
    else:
        pct_value = None

    return pct_value, dl, tot


class DomainDiversityAverager:
    def __init__(self) -> None:
        self.samples = 0
        self.total = 0.0

    def update(self, current_count: int) -> float:
        self.samples += 1
        self.total += max(0, int(current_count))
        return self.average

    @property
    def average(self) -> float:
        if self.samples <= 0:
            return 0.0
        return self.total / self.samples


def _gather_from_roots(
    roots: List[Path], finished_log: Path, priority_files: Optional[List[str]] = None
) -> tuple[List[Path], List[Path]]:
    pool: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.txt"):
            if p.is_file():
                pool.append(p)
    finished: set[str] = set()
    if finished_log.exists():
        try:
            finished = set(x.strip() for x in finished_log.read_text(encoding="utf-8").splitlines() if x.strip())
        except Exception:
            finished = set()

    available_pool = [p for p in pool if str(p.resolve()) not in finished]

    if not priority_files:
        return available_pool, []

    priority_paths = []
    for pf in priority_files:
        p = Path(pf).expanduser().resolve()
        if p.exists() and p.is_file() and str(p) not in finished:
            priority_paths.append(p)

    regular_pool = [p for p in available_pool if p.resolve() not in [pp.resolve() for pp in priority_paths]]

    return regular_pool, priority_paths


def _start_worker(
    slot: int,
    urlfile: Path,
    canonical_root: Path,
    max_rate: float,
    quiet: bool,
    archive_dir: Optional[Path],
    log_dir: Path,
    cap_mibs: Optional[float],
    proxy_dl_location: Optional[str] = None,
    max_resolution: Optional[str] = None,
    stop_sentinel: Optional[Path] = None,
    no_extdl_fallback: bool = False,
    extdl_max_candidates: int = 5,
    extdl_browser_wait: float = 12.0,
    extdl_capture_browser: str = "auto",
    skip_simulate_check: bool = False,
    canonical_dir_override: Optional[Path] = None,
    stall_seconds: int = 4,
    ytdlp_grid_config_file: Optional[Path] = None,
) -> subprocess.Popen:
    if canonical_dir_override is not None:
        canonical_dir = canonical_dir_override
    else:
        canonical_dir = (canonical_root / urlfile.stem).expanduser().resolve()
    canonical_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "downloader.py"),
        "-f",
        str(urlfile),
        "-U",
        str(max_rate),
    ]
    cmd += ["-o", str(canonical_dir)]
    # Dedicated program log per worker to avoid cross-process contention
    log_name = Path(log_dir) / f"ytaedler-worker-{slot:02d}.log"
    cmd += ["-g", str(log_name)]
    if isinstance(cap_mibs, (int, float)) and cap_mibs and cap_mibs > 0:
        cmd += ["-X", str(cap_mibs)]
    if archive_dir:
        cmd += ["-a", str(archive_dir)]
    cmd += ["-r", str(Path(log_dir) / "raw")]  # raw tool logs alongside other logs
    if proxy_dl_location:
        cmd += ["--proxy-dl-location", str(proxy_dl_location)]
    if max_resolution:
        cmd += ["--max-resolution", max_resolution]
    if stop_sentinel:
        cmd += ["-B", str(stop_sentinel)]
    if no_extdl_fallback:
        cmd.append("--no-extdl-fallback")
    if extdl_max_candidates != 5:
        cmd += ["--extdl-max-candidates", str(extdl_max_candidates)]
    if extdl_browser_wait != 12.0:
        cmd += ["--extdl-browser-wait", str(extdl_browser_wait)]
    if extdl_capture_browser != "auto":
        cmd += ["--extdl-capture-browser", extdl_capture_browser]
    if skip_simulate_check:
        cmd.append("--skip-simulate-check")
    if stall_seconds and stall_seconds != 4:
        cmd += ["-S", str(stall_seconds)]
    if ytdlp_grid_config_file:
        cmd += ["-G", str(ytdlp_grid_config_file)]
    if quiet:
        cmd.append("-q")
    # line buffered
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=0,
    )


def _write_worker_log(log_path: Path, counter: int, elapsed_s: float, status: str, message: str) -> None:
    """Write a manager-side log entry to a worker's prog log file.

    Uses the same ``[HH:MM:SS][HH:MM:SS.mmm] STATUS  message`` format as ProgLogger so
    entries appear seamlessly in the TUI verbose log panel.
    """
    try:
        h = int(elapsed_s) // 3600
        m = (int(elapsed_s) % 3600) // 60
        s = int(elapsed_s) % 60
        ms = int((elapsed_s - int(elapsed_s)) * 1000)
        elapsed_str = f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
        wall = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{wall}][{elapsed_str}] {status:<14s}  {message}"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def make_parser() -> argparse.ArgumentParser:
    p = EnforcedArgumentParser(
        prog="dlmanager.py",
        description="Master downloader that coordinates multiple dlscript.py workers",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-t", "--threads", type=int, default=2, help="Number of concurrent dlscript workers")
    p.add_argument(
        "-l", "--time-limit", type=int, default=-1, help="Max seconds a worker holds a urlfile (-1 for unlimited)"
    )
    p.add_argument(
        "-u",
        "--max-ndjson-rate",
        type=float,
        default=5.0,
        help="Max progress events/sec printed by workers (-1 unlimited)",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="Pass -q to workers")
    p.add_argument(
        "-p", "--priority-files", action="append", help="URL files to prioritize (can be specified multiple times)"
    )
    p.add_argument(
        "-P",
        "--proxy-dl-location",
        default=None,
        help="Download into this root (per url file subfolder) while checking duplicates in the canonical location",
    )
    p.add_argument("-s", "--stars-dir", default="./files/downloads/stars", help="Folder of yt-dlp url files")
    p.add_argument("-d", "--aebn-dir", default="./files/downloads/ae-stars", help="Folder of AEBN url files")
    p.add_argument(
        "-f", "--finished-log", default="./logs/finished_urls.txt", help="Path to record completed URLs (default: <log-dir>/finished_urls.txt)"
    )
    p.add_argument("-r", "--refresh-hz", type=float, default=5.0, help="UI refresh rate")
    p.add_argument("-e", "--exit-at-time", type=int, default=-1, help="Exit the manager after N seconds (<=0 disables)")
    p.add_argument("-a", "--archive", type=str, default=None, help="Archive folder to store per-urlfile status files")
    p.add_argument(
        "-g", "--log-dir", type=str, default="./logs", help="Directory for all logs (manager, workers, watcher)"
    )
    p.add_argument(
        "-x", "--max-process-dl-speed", type=float, default=None, help="Per-worker max download speed (MiB/s)"
    )
    p.add_argument(
        "-v",
        "--max-resolution",
        choices=MAX_RESOLUTION_CHOICES,
        default=None,
        help="Highest video resolution workers should request",
    )
    p.add_argument(
        "-z",
        "--max-total-dl-speed",
        type=float,
        default=None,
        help="Global max download speed across all workers (MiB/s)",
    )
    p.add_argument("-b", "--show-bars", action="store_true", help="Show an ASCII progress bar per worker")
    p.add_argument("-w", "--enable-mp4-watcher", action="store_true", help="Enable MP4 watcher integration")
    p.add_argument(
        "-o",
        "--mp4-operation",
        choices=sorted(MP4_VALID_OPERATIONS),
        default="move",
        help="Default MP4 watcher operation to apply when syncing staged MP4 files",
    )
    p.add_argument(
        "-k",
        "--mp4-max-files",
        type=int,
        default=None,
        help="Cap how many MP4 files the watcher processes per run (omit for unlimited)",
    )
    p.add_argument(
        "-G",
        "--mp4-trigger-total-gb",
        type=float,
        default=None,
        help="Automatically trigger the watcher when total size of complete MP4 files in proxy location exceeds this GiB threshold (off by default)",
    )
    p.add_argument(
        "-F",
        "--mp4-trigger-free-gb",
        type=float,
        default=75.0,
        help="Automatically trigger the watcher when staging free space drops below this GiB threshold",
    )
    p.add_argument(
        "-m",
        "--space-remaining",
        type=_parse_size_bytes,
        default=None,
        help=(
            "Minimum final destination disk space to preserve for watcher transfers "
            "(examples: 1024MB, 100GB, unlimited)"
        ),
    )
    p.add_argument(
        "-T",
        "--mp4-stay-at-staging",
        action="store_true",
        help=(
            "Keep downloaded files at the staging/proxy location instead of moving them to the final destination. "
            "The watcher will only scan for inferior duplicate files that exist at both locations and delete the worse copy."
        ),
    )
    p.add_argument(
        "-D",
        "--unique-domain-dls",
        type=int,
        default=-1,
        metavar="N",
        help=(
            "Limit concurrent workers per domain. -1 = off (unlimited). "
            "1 = one worker per unique domain. 2 = up to two workers per domain, etc. "
            "Workers that cannot find a qualifying domain slot stay idle until one opens."
        ),
    )
    p.add_argument(
        "-n", "--no-extdl-fallback",
        action="store_true",
        help="Disable the extdl static-HTML / Playwright fallback when yt-dlp fails.",
    )
    p.add_argument(
        "-j", "--extdl-max-candidates",
        type=int,
        default=5,
        help="Max fallback media candidates to try per method (0 = all).",
    )
    p.add_argument(
        "-J", "--extdl-browser-wait",
        type=float,
        default=12.0,
        help="Seconds to collect browser network traffic in the Playwright fallback.",
    )
    p.add_argument(
        "-N", "--extdl-capture-browser",
        default="auto",
        choices=["auto", "chromium", "firefox", "webkit"],
        help="Playwright browser backend for network capture fallback.",
    )
    p.add_argument(
        "-K", "--skip-simulate-check",
        action="store_true",
        help="Skip the yt-dlp --simulate pre-download duplicate check.",
    )
    p.add_argument(
        "-X",
        "--yt-dlp-grid-search",
        action="store_true",
        help="Enable adaptive gsearch trials for yt-dlp worker downloads.",
    )
    p.add_argument(
        "-B",
        "--yt-dlp-grid-db",
        default=None,
        help="SQLite grid-search database path; defaults to <log-dir>/yt-dlp-grid.db when grid search is enabled.",
    )
    p.add_argument(
        "-V",
        "--yt-dlp-grid-experiment",
        default=yt_grid.DEFAULT_GRID_EXPERIMENT,
        help="gsearch experiment name for yt-dlp grid search.",
    )
    p.add_argument(
        "-S", "--stall-seconds",
        type=int,
        default=4,
        help=(
            "Seconds with no yt-dlp output before a worker kills the attempt and tries the "
            "next fallback method. Default 4s is tuned for the extdl fallback chain."
        ),
    )
    p.add_argument(
        "-H", "--domain-index-path",
        default="./logs/domain_index.json",
        help="Path to save/load the domain URL index (used by -D). Rebuilt when URL files change.",
    )
    p.add_argument(
        "-M", "--rebuild-domain-index",
        action="store_true",
        help="Force a full domain index rebuild even if a saved index exists.",
    )
    p.add_argument(
        "-O",
        "--url-order-key",
        choices=urlscan.SORT_CHOICES,
        default="ratio",
        help="Metric used to prioritise URL files (ratio, remaining, name, unique, mp4, ae, stars, gb)",
    )
    p.add_argument(
        "-C",
        "--url-order-ascending",
        action="store_true",
        help="Sort URL priority ascending instead of descending",
    )
    p.add_argument(
        "-R",
        "--url-rescan-seconds",
        type=int,
        default=0,
        help="How often to rescan URL stats and refresh priority (<=0 disables)",
    )
    p.add_argument(
        "-I",
        "--url-preempt",
        action="store_true",
        help="Interrupt workers handling low-priority files after a rescan so top entries start immediately",
    )
    p.add_argument(
        "-L",
        "--download-root",
        default="./stars",
        help="Directory where per-urlfile MP4 folders are stored",
    )
    p.add_argument(
        "-Z",
        "--url-random-order",
        action="store_true",
        help="Ignore metrics and assign URL files randomly",
    )
    p.add_argument(
        "-Q",
        "--url-pick-temperature",
        type=_parse_url_pick_temperature,
        default=0.0,
        help="Weighted-random URL assignment temperature; 0 is deterministic, higher values add randomness",
    )
    # Web viewer (TermDash mirror) options
    p.add_argument(
        "-W", "--web-view",
        action="store_true",
        help="Mirror the TUI to the web viewer (requires orchestrator_web_viewer)",
    )
    p.add_argument(
        "-Y", "--web-id",
        default="ytaedl",
        help="Dashboard ID to register with the web viewer (default: ytaedl)",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    if argv_list and argv_list[0] == "urls":
        return urlscan.cli_main(argv_list[1:])
    if argv_list and argv_list[0] == "archive":
        return archive_builder.cli_main(argv_list[1:])
    args = make_parser().parse_args(argv_list)
    t0 = time.time()
    deadline = (t0 + args.exit_at_time) if (args.exit_at_time and args.exit_at_time > 0) else None

    # Optional TermDash web mirror
    td_dash = None
    td_lines_built = False
    td_available = False
    if args.web_view:
        try:
            from termdash import TermDash, Stat, Line  # type: ignore
            td_available = True
            # Attempt to register with web viewer if available
            try:
                from orchestrator_web_viewer.api.termdash import register_dashboard  # type: ignore
                td_dash = TermDash(align_columns=True, enable_separators=True)
                register_dashboard(args.web_id, td_dash)
            except Exception:
                # Fallback: still create dashboard locally for export polling
                td_dash = TermDash(align_columns=True, enable_separators=True)
        except Exception:
            td_available = False
            td_dash = None
    stars_dir = Path(args.stars_dir).expanduser().resolve()
    aebn_dir = Path(args.aebn_dir).expanduser().resolve()
    download_root = Path(args.download_root).expanduser().resolve()
    download_root.mkdir(parents=True, exist_ok=True)
    # Logs - all logs go in log_dir with timestamps
    log_dir = Path(args.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    manager_log_path = log_dir / f"dlmanager-{ts}-{os.getpid()}.log"
    controlled_quit_sentinel = log_dir / f"controlled-quit-{ts}-{os.getpid()}.stop"
    mlog = ManagerLogger(manager_log_path)

    ytdlp_grid_db: Optional[Path] = None
    if args.yt_dlp_grid_search:
        ytdlp_grid_db = (
            Path(args.yt_dlp_grid_db).expanduser().resolve()
            if args.yt_dlp_grid_db
            else (log_dir / "yt-dlp-grid.db").resolve()
        )
        try:
            yt_grid.ensure_grid_experiment(ytdlp_grid_db, args.yt_dlp_grid_experiment)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
        mlog.info(
            f"yt-dlp grid search enabled db={ytdlp_grid_db} "
            f"experiment={args.yt_dlp_grid_experiment}"
        )

    archive_dir: Optional[Path] = Path(args.archive).expanduser().resolve() if args.archive else None
    if archive_dir:
        archive_dir.mkdir(parents=True, exist_ok=True)
    # Mirror finished_log into log_dir when using the default path
    _fl_arg = args.finished_log
    if _fl_arg == "./logs/finished_urls.txt":
        finished_log = log_dir / "finished_urls.txt"
    else:
        finished_log = Path(_fl_arg).expanduser().resolve()
    finished_log.parent.mkdir(parents=True, exist_ok=True)

    mp4_trigger_total_bytes = (
        int(args.mp4_trigger_total_gb * (1024**3))
        if isinstance(args.mp4_trigger_total_gb, (int, float)) and args.mp4_trigger_total_gb > 0
        else None
    )
    mp4_trigger_free_bytes = (
        int(args.mp4_trigger_free_gb * (1024**3))
        if isinstance(args.mp4_trigger_free_gb, (int, float)) and args.mp4_trigger_free_gb > 0
        else None
    )
    proxy_root: Optional[Path] = Path(args.proxy_dl_location).expanduser().resolve() if args.proxy_dl_location else None

    watcher: Optional[MP4Watcher] = None
    watcher_auto_delay_until: Optional[float] = None
    watcher_auto_delay_finish_logged = False
    if args.enable_mp4_watcher:
        staging_root = proxy_root
        destination_root = download_root
        watcher_log_path = log_dir / f"mp4_watcher-{ts}.log"
        max_files = args.mp4_max_files if isinstance(args.mp4_max_files, int) and args.mp4_max_files > 0 else None

        # Determine keep_source based on operation mode
        # move = delete source (keep_source=False), copy = keep source (keep_source=True)
        keep_source = args.mp4_operation == "copy"

        if staging_root is None:
            mlog.error("MP4 watcher requested but --proxy-dl-location was not provided; watcher disabled")
        else:
            config = WatcherConfig(
                staging_root=staging_root,
                destination_root=destination_root,
                log_path=watcher_log_path,
                default_operation=args.mp4_operation,
                max_files=max_files,
                keep_source=keep_source,
                total_size_trigger_bytes=mp4_trigger_total_bytes,
                free_space_trigger_bytes=mp4_trigger_free_bytes,
                destination_space_remaining_bytes=args.space_remaining,
                stay_at_staging=args.mp4_stay_at_staging,
            )
            watcher = MP4Watcher(config=config, enabled=True)
            if args.mp4_stay_at_staging and watcher.is_enabled():
                # CLI arg sets stay-at-staging as a manual choice so auto-disable won't fire.
                watcher.set_stay_at_staging(True, manual=True)
            if watcher.is_enabled():
                mlog.info(
                    f"MP4 watcher enabled: staging={staging_root} destination={destination_root} operation={args.mp4_operation}"
                )
                watcher_auto_delay_until = time.time() + 60.0
                watcher_auto_delay_finish_logged = False
                max_label = max_files if max_files is not None else "unlimited"
                free_label = _watcher_trigger_label(config.free_space_trigger_bytes)
                size_label = _watcher_trigger_label(config.total_size_trigger_bytes)
                reserve_label = (
                    _format_disk_bytes(config.destination_space_remaining_bytes)
                    if config.destination_space_remaining_bytes
                    else "disabled"
                )
                keep_desc = "keep source" if keep_source else "delete source"
                staging_label = str(staging_root)
                destination_label = str(destination_root)
                stay_desc = "stay-at-staging=yes (files will not be moved; collision dedup only)" if args.mp4_stay_at_staging else "stay-at-staging=no"
                watcher.log_event(
                    "CONFIG",
                    f"Watcher configured: staging={staging_label} -> {destination_label}, "
                    f"default={args.mp4_operation}, "
                    f"{keep_desc}, max_files={max_label}, free_trigger={free_label}, size_trigger={size_label}, "
                    f"destination_reserve={reserve_label}, {stay_desc}.",
                )
                watcher.log_event(
                    "STATE",
                    "Auto-clean startup delay active for 60s so workers can stabilise. Press 'c' to clean immediately.",
                )
            else:
                mlog.error(
                    f"MP4 watcher initialisation failed; staging={staging_root} destination={destination_root} "
                    f"exists={staging_root.exists()}/{destination_root.exists()}"
                )
                watcher = MP4Watcher(config=config, enabled=False)
    elif (
        args.mp4_operation
        or args.mp4_max_files
        or args.mp4_trigger_total_gb
        or args.mp4_trigger_free_gb
        or args.space_remaining
    ):
        mlog.info("MP4 watcher configuration ignored because --enable-mp4-watcher was not set")

    roots: List[Path] = [stars_dir, aebn_dir]
    pool, priority_pool = _gather_from_roots(roots, finished_log, args.priority_files)
    if not pool and not priority_pool:
        # Fallback to test dirs if primary roots are empty
        repo_root = Path(__file__).resolve().parent.parent
        test_stars = (repo_root / "test" / "files" / "downloads" / "stars").resolve()
        test_aebn = (repo_root / "test" / "files" / "downloads" / "ae-stars").resolve()
        roots = [test_stars, test_aebn]
        pool, priority_pool = _gather_from_roots(roots, finished_log, args.priority_files)
    # ------------------------------------------------------------------
    # Domain index (used when -D is active for URL-level domain locking)
    domain_index: Optional[DomainIndex] = None
    domain_index_path: Optional[Path] = None

    _udl_active = (
        (isinstance(getattr(args, "unique_domain_dls", -1), int) and args.unique_domain_dls >= 1)
        or bool(args.yt_dlp_grid_search)
    )
    if _udl_active:
        # Gather ALL URL files from roots (including finished ones) for a complete index
        _all_url_files: List[Path] = []
        for root in roots:
            if root.exists():
                _all_url_files.extend(sorted(root.rglob("*.txt")))

        # Resolve index path: default to same directory as other logs
        _idx_arg = getattr(args, "domain_index_path", "./logs/domain_index.json")
        if _idx_arg == "./logs/domain_index.json":
            domain_index_path = log_dir / "domain_index.json"
        else:
            domain_index_path = Path(_idx_arg).expanduser().resolve()
        _idx_log: List[str] = []
        _should_rebuild = getattr(args, "rebuild_domain_index", False)

        if not _should_rebuild and domain_index_path.exists():
            try:
                mlog.info(f"Loading domain index from {domain_index_path} …")
                _loaded = DomainIndex.load(domain_index_path)
                if _loaded.is_stale():
                    mlog.info("Domain index is stale (URL files changed) – rebuilding.")
                    _should_rebuild = True
                else:
                    domain_index = _loaded
                    mlog.info(f"Domain index loaded: {domain_index.summary_line()}")
            except Exception as exc:
                mlog.error(f"Failed to load domain index: {exc} – rebuilding.")
                _should_rebuild = True

        if domain_index is None or _should_rebuild:
            if _should_rebuild and domain_index_path and domain_index_path.exists():
                try:
                    domain_index_path.unlink()
                    mlog.info(f"-M: deleted existing domain index {domain_index_path} for clean rebuild")
                except Exception as _e:
                    mlog.error(f"-M: failed to delete {domain_index_path}: {_e}")
            mlog.info(f"Building domain index from {len(_all_url_files)} URL file(s) …")
            domain_index = DomainIndex.build(
                _all_url_files,
                progress_cb=lambda msg: mlog.info(f"  {msg}"),
            )
            domain_index.save(domain_index_path)
            mlog.info(f"Domain index saved to {domain_index_path}")

        # Register save path for auto-save on updates
        domain_index.save_debounced(domain_index_path, delay_s=5.0)
        mlog.info(f"Domain index ready: {domain_index.summary_line()}")

    active: set[str] = set()
    watcher_log_scroll = 0
    watcher_log_follow = True
    watcher_log_meta: Dict[str, int] = {"log_max_scroll": 0, "log_window": 0}
    downloads_panel_scroll = 0
    downloads_panel_max_scroll = 0
    auto_block_reason: Optional[str] = None

    workers: List[WorkerState] = [WorkerState(slot=i) for i in range(1, args.threads + 1)]
    stop = threading.Event()
    mlog.info(
        f"Start manager threads={args.threads} time_limit={args.time_limit} refresh_hz={args.refresh_hz} exit_at_time={args.exit_at_time} archive_dir={archive_dir}"
    )
    mlog.info(f"Log dir: {log_dir} | Manager log: {manager_log_path}")
    if args.priority_files:
        mlog.info(f"Priority files: {len(priority_pool)} files specified: {[str(p) for p in priority_pool]}")
    mlog.info(f"Regular pool: {len(pool)} files | Priority pool: {len(priority_pool)} files")

    url_rankings: Dict[str, int] = {}
    url_order_paths: List[Path] = []
    url_scan_state: Optional[urlscan.ScanResult] = None
    url_scan_interval = (
        float(args.url_rescan_seconds) if args.url_rescan_seconds and args.url_rescan_seconds > 0 else None
    )
    next_url_scan: Optional[float] = None
    last_url_scan = 0.0
    url_scan_json_path = log_dir / "urlscan-latest.json"
    url_scan_thread: Optional[threading.Thread] = None
    url_scan_pending_trigger: Optional[str] = None
    url_scan_status = "idle"
    url_panel_auto_refresh = True
    url_panel_sort_key = args.url_order_key
    url_panel_sort_ascending = args.url_order_ascending
    url_panel_name_filter = ""
    url_panel_top = 0
    url_panel_scroll = 0
    url_panel_max_top = 0
    url_panel_max_scroll = 0
    urlfile_domain_cache: Dict[str, set[str]] = {}
    domain_diversity_avg = DomainDiversityAverager()
    controlled_quit = False
    downloads_status_visible = True

    # Totals tracking
    total_completed_bytes = 0
    total_processed_urls = 0
    total_completed_urls = 0
    total_started_urls = 0

    def _refresh_url_scan_sync(trigger: str) -> bool:
        nonlocal url_rankings, url_order_paths, url_scan_state, next_url_scan, last_url_scan, url_panel_top, url_panel_scroll
        try:
            scan = urlscan.scan_url_stats(stars_dir, aebn_dir, download_root)
        except Exception as exc:
            mlog.error(f"URL scan failed ({trigger}): {exc}")
            return False
        url_scan_state = scan
        ordered_paths, ranks = urlscan.compute_rankings(
            [entry for entry in scan.entries if entry.remaining > 0],
            args.url_order_ascending,
            args.url_order_key,
        )
        url_order_paths = ordered_paths
        url_rankings = {str(path.resolve()): rank for rank, path in enumerate(ordered_paths)}
        ordered_entries = urlscan.sort_entries(scan.entries, args.url_order_key, args.url_order_ascending)
        settings = types.SimpleNamespace(
            stars_dir=str(stars_dir),
            ae_dir=str(aebn_dir),
            media_dir=str(download_root),
            sort_key=args.url_order_key,
            ascending=args.url_order_ascending,
        )
        try:
            payload = urlscan.build_json(ordered_entries, scan.totals, settings)
            url_scan_json_path.parent.mkdir(parents=True, exist_ok=True)
            url_scan_json_path.write_text(payload, encoding="utf-8")
        except Exception as exc:
            mlog.error(f"Failed to write URL scan summary: {exc}")
        last_url_scan = time.time()
        url_panel_top = min(url_panel_top, max(0, len(ordered_entries) - 1))
        url_panel_scroll = max(0, url_panel_scroll)
        if url_scan_interval:
            next_url_scan = last_url_scan + url_scan_interval
        else:
            next_url_scan = None
        mlog.info(
            f"URL scan refreshed ({trigger}) entries={len(scan.entries)} "
            f"order_key={args.url_order_key} ascending={args.url_order_ascending}"
        )
        return True

    def _schedule_url_scan(trigger: str) -> None:
        nonlocal url_scan_thread, url_scan_pending_trigger, url_scan_status

        def _launch(trigger_to_run: str) -> None:
            nonlocal url_scan_thread, url_scan_pending_trigger, url_scan_status

            def runner(req_trigger: str) -> None:
                nonlocal url_scan_thread, url_scan_pending_trigger, url_scan_status
                try:
                    ok = _refresh_url_scan_sync(req_trigger)
                    url_scan_status = f"scan {'ok' if ok else 'failed'} ({req_trigger})"
                except Exception as exc:
                    url_scan_status = f"scan error: {exc}"
                finally:
                    url_scan_thread = None
                    if url_scan_pending_trigger:
                        pending = url_scan_pending_trigger
                        url_scan_pending_trigger = None
                        _launch(pending)

            url_scan_status = f"scan running ({trigger_to_run})"
            url_scan_thread = threading.Thread(target=runner, args=(trigger_to_run,), daemon=True)
            url_scan_thread.start()

        if url_scan_thread and url_scan_thread.is_alive():
            url_scan_pending_trigger = trigger
            url_scan_status = f"scan queued ({trigger})"
            return
        _launch(trigger)

    def _refresh_url_scan(trigger: str) -> bool:
        """Refresh URL scan synchronously (used by UI refresh hooks)."""
        return _refresh_url_scan_sync(trigger)

    def _path_remaining(path: Path) -> Optional[int]:
        if not url_scan_state:
            return None
        entry = url_scan_state.path_index.get(str(path.resolve()))
        if not entry:
            return None
        return entry.remaining

    def _remaining_for_path(path: Path) -> Optional[int]:
        """Return remaining URL count using scan data or a quick inline estimate."""
        remaining = _path_remaining(path)
        if remaining is not None:
            return remaining
        try:
            urls = _read_urls(path)
        except Exception:
            return None
        dest_dir = (download_root / path.stem).resolve()
        mp4_count, _, _ = urlscan.mp4_inventory(dest_dir)
        return max(len(urls) - mp4_count, 0)

    def _active_domains() -> set[str]:
        return {
            domain
            for domain in (_top_domain(worker.url_current) for worker in workers if worker.proc and not worker.is_paused)
            if domain != "-"
        }

    def _active_scheduling_domains() -> set[str]:
        domains = set(_active_domains())
        for worker in workers:
            if not worker.proc or worker.is_paused or not worker.urlfile:
                continue
            if _top_domain(worker.url_current) != "-":
                continue
            domains.update(_cached_domains_for_urlfile(worker.urlfile))
        return domains

    def _cached_domains_for_urlfile(path: Path) -> set[str]:
        key = str(path.resolve())
        if key not in urlfile_domain_cache:
            urlfile_domain_cache[key] = _domains_for_urlfile(path)
        return urlfile_domain_cache[key]

    def _candidate_domain_map(candidates: List[Path]) -> Dict[str, set[str]]:
        return {str(path.resolve()): _cached_domains_for_urlfile(path) for path in candidates}

    def _active_domain_worker_counts() -> Dict[str, int]:
        """Return the number of currently-assigned workers per domain.

        Counts every worker that has a urlfile assigned (regardless of whether
        the subprocess has started yet), so the domain slot budget is always
        accurate during the sequential startup assignment loop.
        """
        counts: Dict[str, int] = {}
        for worker in workers:
            if not worker.urlfile:
                continue
            for domain in _cached_domains_for_urlfile(worker.urlfile):
                counts[domain] = counts.get(domain, 0) + 1
        return counts

    def _hard_domain_filter(pool: List[Path]) -> List[Path]:
        """Filter *pool* to files whose domains have room under the per-domain cap.

        Returns an empty list (never falls back to the full pool) when all
        domains in *pool* are at the limit — the caller must leave the worker
        idle so it can retry on the next main-loop tick.
        """
        max_per = getattr(args, "unique_domain_dls", -1)
        if not isinstance(max_per, int) or max_per < 1:
            return pool  # feature disabled
        counts = _active_domain_worker_counts()
        return [
            f for f in pool
            if any(counts.get(d, 0) < max_per for d in _cached_domains_for_urlfile(f))
        ]

    def _select_best(candidates: List[Path]) -> Optional[Path]:
        eligible = [c for c in candidates if _remaining_for_path(c) != 0]
        if not eligible:
            eligible = list(candidates)
        if args.url_random_order:
            filtered = _hard_domain_filter(eligible)
            return random.choice(filtered) if filtered else None
        filtered = _hard_domain_filter(eligible)
        if not filtered:
            return None  # domain slots full — caller leaves worker idle
        if not url_rankings:
            fallback_rankings = {str(path.resolve()): idx for idx, path in enumerate(sorted(filtered))}
            return _choose_domain_diverse_candidate(
                filtered,
                fallback_rankings,
                _candidate_domain_map(filtered),
                _active_scheduling_domains(),
                float(args.url_pick_temperature or 0.0),
            )
        return _choose_domain_diverse_candidate(
            filtered,
            url_rankings,
            _candidate_domain_map(filtered),
            _active_scheduling_domains(),
            float(args.url_pick_temperature or 0.0),
        )

    def _select_priority(candidates: List[Path]) -> Optional[Path]:
        eligible = [c for c in candidates if _remaining_for_path(c) != 0]
        if not eligible:
            return None
        if args.url_random_order:
            filtered = _hard_domain_filter(eligible)
            return random.choice(filtered) if filtered else None
        filtered = _hard_domain_filter(eligible)
        if not filtered:
            return None  # domain slots full
        priority_rankings = {str(path.resolve()): idx for idx, path in enumerate(filtered)}
        return _choose_domain_diverse_candidate(
            filtered,
            priority_rankings,
            _candidate_domain_map(filtered),
            _active_scheduling_domains(),
            float(args.url_pick_temperature or 0.0),
        )

    _schedule_url_scan("startup")

    def _clear_worker_progress(ws: WorkerState) -> None:
        ws.percent = None
        ws.speed_bps = None
        ws.eta_s = None
        ws.downloaded_bytes = None
        ws.total_bytes = None

    def _reader(ws: WorkerState):
        f = ws.proc.stdout  # type: ignore
        # Capture the stop event once at thread-start.  _assign() may replace
        # ws.reader_stop with a fresh threading.Event() for the NEXT reader while
        # this (old) reader is still draining buffered stdout.  Holding a local
        # reference ensures the old reader continues to see *its* stop signal even
        # after ws.reader_stop is reassigned, and prevents ws.reader_stop.clear()
        # from silently re-enabling this thread.
        my_stop = ws.reader_stop
        try:
            for line in f:
                # Check BEFORE processing so stale buffered events from a
                # just-finished download don't overwrite the freshly cleared ws state.
                if my_stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                # Buffer NDJSON for verbose view
                try:
                    ws.ndjson_buf.append(line)
                    if len(ws.ndjson_buf) > 400:
                        ws.ndjson_buf = ws.ndjson_buf[-200:]
                except Exception:
                    pass
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                ws.last_event_time = time.time()
                ev = evt.get("event")
                if ev == "start":
                    ws.url_index = evt.get("url_index")
                    ws.url_current = evt.get("url")
                    ws.downloader = evt.get("downloader")
                    # Reset progress state on new URL
                    _clear_worker_progress(ws)
                    ws.url_t0 = time.time()
                    if ws.ytdlp_grid_trial_id and ws.downloader == "yt-dlp":
                        ws.ytdlp_grid_stats = yt_grid.GridRuntimeStats(
                            base_domain=yt_grid.base_domain(str(ws.url_current or "")),
                            started_at=ws.url_t0,
                            last_update_at=ws.url_t0,
                        )
                    # Clear overlay and searching flag upon new activity
                    ws.overlay_msg = None
                    ws.overlay_since = 0.0
                    ws.is_searching = False
                    ws.progress_log_started = False
                    ws.last_progress_log_t = 0.0
                    nonlocal total_started_urls
                    total_started_urls += 1
                    mlog.info(f"[{ws.slot:02d}] START idx={ws.url_index} url={ws.url_current}")
                elif ev == "destination":
                    ws.destination = evt.get("path")
                    mlog.info(f"[{ws.slot:02d}] DEST path={ws.destination}")
                elif ev == "already":
                    # Mark that this URL was already downloaded
                    ws.last_already = True
                elif ev == "canonical_duplicate":
                    # Downloader found the file already exists at the canonical destination
                    ws.last_already = True
                    canon = evt.get("canonical_path", "?")
                    mlog.info(f"[{ws.slot:02d}] CANONICAL_DUP dest={canon}")
                elif ev == "simulate_start":
                    ws.overlay_msg = "\x1b[36m[Simulating…]\x1b[0m checking for existing file at destination"
                    ws.overlay_since = time.time()
                    mlog.info(f"[{ws.slot:02d}] SIMULATE_START url={ws.url_current}")
                elif ev == "simulate_result":
                    is_dup = evt.get("is_duplicate", False)
                    if is_dup and domain_index and ws.url_current and ws.url_current != "-":
                        try:
                            domain_index.mark_finished(ws.url_current, "preexisting")
                        except Exception:
                            pass
                    if is_dup:
                        existing = evt.get("existing_path", "?")
                        ws.overlay_msg = (
                            "\x1b[33m[Sim: CONFLICT]\x1b[0m"
                            f" file exists – skipping  ({Path(existing).name if existing else '?'})"
                        )
                        mlog.info(f"[{ws.slot:02d}] SIMULATE_SKIP existing={existing}")
                    else:
                        name = evt.get("predicted_name", "")
                        ws.overlay_msg = (
                            "\x1b[32m[Sim: OK]\x1b[0m"
                            f" no conflict – starting download ({name})"
                        )
                        mlog.info(f"[{ws.slot:02d}] SIMULATE_OK predicted={name}")
                    ws.overlay_since = time.time()
                elif ev == "fallback_start":
                    method = evt.get("method", "?")
                    ws.overlay_msg = f"\x1b[33m[Fallback:{method}]\x1b[0m Discovering media URLs…"
                    ws.overlay_since = time.time()
                    # Clear stale download stats so the UI doesn't show the previous
                    # download's progress (e.g. 100%) while the fallback is running.
                    _clear_worker_progress(ws)
                    # The log will show FALLBACK_START (not START/PROGRESS) so reset
                    # progress_log_started so the next progress event writes DOWNLOAD_START.
                    ws.progress_log_started = False
                    ws.last_progress_log_t = 0.0
                    mlog.info(f"[{ws.slot:02d}] FALLBACK_START method={method} url={ws.url_current}")
                elif ev == "fallback_attempt":
                    method = evt.get("method", "?")
                    attempt = evt.get("attempt", "?")
                    total = evt.get("total", "?")
                    kind = evt.get("kind", "")
                    ws.overlay_msg = (
                        f"\x1b[33m[Fallback:{method}]\x1b[0m"
                        f" Trying candidate {attempt}/{total} ({kind})…"
                    )
                    ws.overlay_since = time.time()
                    mlog.info(f"[{ws.slot:02d}] FALLBACK_ATTEMPT method={method} {attempt}/{total} kind={kind}")
                elif ev == "fallback_success":
                    method = evt.get("method", "?")
                    ws.overlay_msg = f"\x1b[32m[Fallback:{method} OK]\x1b[0m Downloading…"
                    ws.overlay_since = time.time()
                    mlog.info(f"[{ws.slot:02d}] FALLBACK_SUCCESS method={method}")
                elif ev == "fallback_failure":
                    method = evt.get("method", "?")
                    attempt = evt.get("attempt", "?")
                    rc_f = evt.get("rc", "?")
                    mlog.info(f"[{ws.slot:02d}] FALLBACK_FAILURE method={method} attempt={attempt} rc={rc_f}")
                elif ev == "fallback_skip":
                    method = evt.get("method", "?")
                    reason = evt.get("reason", "")
                    ws.overlay_msg = f"\x1b[33m[Fallback:{method} skipped]\x1b[0m {reason}"
                    ws.overlay_since = time.time()
                    mlog.info(f"[{ws.slot:02d}] FALLBACK_SKIP method={method} reason={reason}")
                elif ev == "fallback_exhausted":
                    ws.overlay_msg = "\x1b[31m[All fallbacks exhausted]\x1b[0m"
                    ws.overlay_since = time.time()
                    mlog.info(f"[{ws.slot:02d}] FALLBACK_EXHAUSTED url={ws.url_current}")
                elif ev == "progress":
                    # Clamp and normalize to avoid >100% and >total displays
                    try:
                        dl = evt.get("downloaded")
                        tot = evt.get("total")
                        sp = evt.get("speed_bps")
                        eta = evt.get("eta_s")
                        pct = evt.get("percent")
                        norm_pct, norm_dl, norm_tot = _normalize_active_progress(dl, tot, pct, sp)
                        ws.percent = norm_pct
                        ws.downloaded_bytes = norm_dl
                        ws.total_bytes = norm_tot
                        ws.speed_bps = float(sp) if isinstance(sp, (int, float)) else ws.speed_bps
                        # Only overwrite eta_s when the event actually carries one; otherwise
                        # keep the last known value so workers with partial events don't flicker to '?'.
                        if isinstance(eta, (int, float)):
                            ws.eta_s = float(eta)
                        elif (
                            not isinstance(eta, (int, float))
                            and isinstance(ws.speed_bps, float)
                            and ws.speed_bps > 0
                            and isinstance(ws.total_bytes, int)
                            and isinstance(ws.downloaded_bytes, int)
                        ):
                            remaining = ws.total_bytes - ws.downloaded_bytes
                            if remaining > 0:
                                ws.eta_s = remaining / ws.speed_bps
                        # Any progress clears overlay
                        ws.overlay_msg = None
                        ws.overlay_since = 0.0
                        # --- Manager-side progress log entries ---
                        # Write a DOWNLOAD_START line the first time a progress
                        # event arrives (covers fallback downloads that begin
                        # without emitting their own START log line).
                        _now = time.time()
                        if ws.prog_log_path and not ws.progress_log_started:
                            ws.progress_log_started = True
                            ws.last_progress_log_t = _now
                            _url_label = ws.url_current or "-"
                            _idx_label = f"{ws.url_index or 0}/{ws.url_count or 0}"
                            _wlog(ws, "DOWNLOAD_START",
                                  f"[{_idx_label}] {_url_label}")
                        # Write a PROGRESS line every ~15 s while downloading.
                        _PROGRESS_INTERVAL = 15.0
                        if (
                            ws.prog_log_path
                            and ws.progress_log_started
                            and (_now - ws.last_progress_log_t) >= _PROGRESS_INTERVAL
                        ):
                            ws.last_progress_log_t = _now
                            _pct_s = f"{ws.percent:.1f}%" if isinstance(ws.percent, (int, float)) else "?%"
                            _dl_s = _human_short_bytes(ws.downloaded_bytes)
                            _tot_s = _human_short_bytes(ws.total_bytes)
                            _sp_s = (
                                f"{_human_short_bytes(int(ws.speed_bps))}/s"
                                if isinstance(ws.speed_bps, (int, float)) and ws.speed_bps > 0
                                else "?/s"
                            )
                            _eta_s = (
                                _hms(ws.eta_s)
                                if isinstance(ws.eta_s, (int, float))
                                else "?"
                            )
                            _wlog(ws, "PROGRESS",
                                  f"{_pct_s} {_dl_s}/{_tot_s} @ {_sp_s} ETA {_eta_s}")
                    except Exception:
                        pass
                elif ev == "finish":
                    mlog.info(f"[{ws.slot:02d}] FINISH rc={evt.get('rc')} idx={ws.url_index}")
                    try:
                        rc_v = int(evt.get("rc")) if evt.get("rc") is not None else None
                    except Exception:
                        rc_v = None
                    # Update domain index if active
                    if domain_index and ws.url_current and ws.url_current != "-":
                        try:
                            if rc_v == 0 and not ws.last_already:
                                domain_index.mark_finished(ws.url_current, "downloaded")
                            elif rc_v == 0 and ws.last_already:
                                domain_index.mark_finished(ws.url_current, "preexisting")
                            elif rc_v not in (None, 130, 131):
                                # Failed URL (not user abort/deadline) — mark as failed
                                domain_index.mark_finished(ws.url_current, "failed")
                        except Exception:
                            pass
                    # Update per-URL counters here (process continues running)
                    try:
                        rc_v = int(evt.get("rc")) if evt.get("rc") is not None else None
                    except Exception:
                        rc_v = None
                    # Count this URL as processed
                    nonlocal total_processed_urls, total_completed_urls, total_completed_bytes
                    total_processed_urls += 1
                    if rc_v == 0:
                        total_completed_urls += 1
                        if isinstance(ws.downloaded_bytes, int):
                            total_completed_bytes += ws.downloaded_bytes
                    if ws.downloader == "yt-dlp":
                        _record_ytdlp_grid_result(ws, evt)
                    # Build overlay message until next start/progress
                    if rc_v == 0 and not ws.last_already:
                        status_colored = "\x1b[32mDOWNLOADED\x1b[0m"
                    elif rc_v == 0 and ws.last_already:
                        status_colored = "\x1b[33mDUPLICATE\x1b[0m"
                    else:
                        status_colored = "\x1b[31mBAD_URL\x1b[0m"
                    ws.last_already = False
                    elapsed_url = _hms(time.time() - (ws.url_t0 or ws.assign_t0))
                    size_info = f" [{_human_short_bytes(ws.downloaded_bytes)}]" if ws.downloaded_bytes else ""
                    # Write DOWNLOAD_DONE to worker prog log if we ever started logging progress.
                    if ws.prog_log_path and ws.progress_log_started:
                        _status_word = "DOWNLOAD_DONE" if rc_v == 0 else "DOWNLOAD_FAIL"
                        _size_part = f" [{_human_short_bytes(ws.downloaded_bytes)}]" if ws.downloaded_bytes else ""
                        _wlog(ws, _status_word,
                              f"[{ws.url_index or 0}/{ws.url_count or 0}]"
                              f" Elapsed {elapsed_url}{_size_part} rc={rc_v}")
                        ws.progress_log_started = False
                        ws.last_progress_log_t = 0.0
                    ws.overlay_msg = (
                        f"\x1b[90m[{ws.slot:02d}]\x1b[0m URL {ws.url_index or 0}/{ws.url_count or 0}"
                        f" {status_colored}{size_info} {elapsed_url}"
                    )
                    ws.overlay_since = time.time()
                    ws.is_searching = True
                    # On success show 100 %; on failure/duplicate clear percent.
                    # Set speed to 0 so the display doesn't freeze on the last value.
                    # Keep downloaded/total_bytes for the overlay size display; they are
                    # cleared by _clear_worker_progress on the next 'start' event.
                    if rc_v == 0 and not ws.last_already:
                        ws.percent = 100.0
                    else:
                        ws.percent = None
                    ws.speed_bps = 0.0
                    ws.eta_s = None
                elif ev == "aborted":
                    mlog.info(f"[{ws.slot:02d}] ABORT reason={evt.get('reason')}")
                    elapsed_url = _hms(time.time() - (ws.url_t0 or ws.assign_t0))
                    ws.overlay_msg = (
                        f"\x1b[90m[{ws.slot:02d}]\x1b[0m URL {ws.url_index or 0}/{ws.url_count or 0}"
                        f" \x1b[35mABORTED\x1b[0m {elapsed_url}"
                    )
                    ws.overlay_since = time.time()
                    ws.is_searching = True
                    _clear_worker_progress(ws)
                elif ev == "stalled":
                    mlog.info(f"[{ws.slot:02d}] STALLED stall_seconds={evt.get('stall_seconds')}")
                    elapsed_url = _hms(time.time() - (ws.url_t0 or ws.assign_t0))
                    pct_info = f" @ {ws.percent:.1f}%" if isinstance(ws.percent, (int, float)) else ""
                    ws.overlay_msg = (
                        f"\x1b[90m[{ws.slot:02d}]\x1b[0m URL {ws.url_index or 0}/{ws.url_count or 0}"
                        f" \x1b[31mSTALLED\x1b[0m{pct_info} {elapsed_url}"
                    )
                    ws.overlay_since = time.time()
                    _clear_worker_progress(ws)
                elif ev == "deadline":
                    mlog.info(f"[{ws.slot:02d}] DEADLINE idx={ws.url_index}")
                    elapsed_url = _hms(time.time() - (ws.url_t0 or ws.assign_t0))
                    ws.overlay_msg = (
                        f"\x1b[90m[{ws.slot:02d}]\x1b[0m URL {ws.url_index or 0}/{ws.url_count or 0}"
                        f" \x1b[35mDEADLINE\x1b[0m {elapsed_url}"
                    )
                    ws.overlay_since = time.time()
                    _clear_worker_progress(ws)
                elif ev == "controlled_stop":
                    mlog.info(f"[{ws.slot:02d}] CONTROLLED_STOP next_idx={evt.get('url_index')}")
                    ws.controlled_stopped = True
                    ws.overlay_msg = (
                        f"\x1b[90m[{ws.slot:02d}]\x1b[0m "
                        f"\x1b[31mCONTROLLED QUIT\x1b[0m no new URL started"
                    )
                    ws.overlay_since = time.time()
                    _clear_worker_progress(ws)
                if my_stop.is_set():
                    break
        except Exception as e:
            mlog.error(f"reader exception slot={ws.slot}: {e}\n{traceback.format_exc()}")

    def _worker_prog_log_path(ws: WorkerState) -> Path:
        return (Path(log_dir) / f"ytaedler-worker-{ws.slot:02d}.log").resolve()

    def _wlog(ws: WorkerState, status: str, message: str) -> None:
        """Write a manager-side entry to the worker's prog log file."""
        ws.worker_log_counter += 1
        elapsed = time.time() - t0
        _write_worker_log(_worker_prog_log_path(ws), ws.worker_log_counter, elapsed, status, message)

    def _clear_ytdlp_grid_state(ws: WorkerState) -> None:
        ws.ytdlp_grid_trial_id = None
        ws.ytdlp_grid_config = None
        ws.ytdlp_grid_config_path = None
        ws.ytdlp_grid_source_urlfile = None
        ws.ytdlp_grid_stats = None
        ws.ytdlp_grid_recorded = False

    def _active_grid_workers() -> List[WorkerState]:
        return [
            worker
            for worker in workers
            if worker.proc
            and worker.ytdlp_grid_trial_id
            and worker.ytdlp_grid_stats
            and not worker.is_paused
        ]

    def _update_worker_grid_runtime(ws: WorkerState, now: Optional[float] = None) -> None:
        if not ws.ytdlp_grid_stats:
            return
        stamp = time.time() if now is None else now
        active_workers = [worker for worker in workers if worker.proc and not worker.is_paused]
        same_count = sum(
            1
            for worker in active_workers
            if _domain_of_url(worker.url_current or "") == ws.ytdlp_grid_stats.base_domain
        )
        total_speed_bps = sum(
            float(worker.speed_bps)
            for worker in active_workers
            if isinstance(worker.speed_bps, (int, float)) and worker.speed_bps > 0
        )
        worker_speed_bps = float(ws.speed_bps) if isinstance(ws.speed_bps, (int, float)) and ws.speed_bps > 0 else 0.0
        ws.ytdlp_grid_stats.update(
            now=stamp,
            same_domain_other_count=max(0, same_count - 1),
            same_domain_including_self_count=same_count,
            total_speed_bps=total_speed_bps,
            worker_speed_bps=worker_speed_bps,
        )

    def _record_ytdlp_grid_result(ws: WorkerState, event: dict) -> None:
        if not ytdlp_grid_db or not ws.ytdlp_grid_trial_id or ws.ytdlp_grid_recorded:
            return
        now = time.time()
        _update_worker_grid_runtime(ws, now)
        runtime = ws.ytdlp_grid_stats.snapshot(now=now) if ws.ytdlp_grid_stats else {}
        try:
            rc_value = int(event.get("rc")) if event.get("rc") is not None else None
        except Exception:
            rc_value = None
        downloaded = event.get("downloaded")
        if not isinstance(downloaded, (int, float)):
            downloaded = ws.downloaded_bytes
        downloader_elapsed = event.get("elapsed_s")
        manager_elapsed = runtime.get("manager_observed_elapsed_seconds")
        metric_elapsed = downloader_elapsed if isinstance(downloader_elapsed, (int, float)) and downloader_elapsed > 0 else manager_elapsed
        worker_average_mbps = yt_grid.average_mbps(downloaded, metric_elapsed)
        already = bool(event.get("already") or ws.last_already)
        status = "ok" if rc_value == 0 and not already and worker_average_mbps is not None else "failed"
        metric_value = worker_average_mbps if status == "ok" else None
        url = str(event.get("url") or ws.url_current or "")
        base_domain = ws.ytdlp_grid_stats.base_domain if ws.ytdlp_grid_stats else yt_grid.base_domain(url)
        metadata = {
            "trial_id": ws.ytdlp_grid_trial_id,
            "grid_config": ws.ytdlp_grid_config or {},
            "url": url,
            "hostname": yt_grid.hostname(url),
            "base_domain": base_domain,
            "worker_slot": ws.slot,
            "source_urlfile": ws.ytdlp_grid_source_urlfile,
            "downloader_elapsed_seconds": downloader_elapsed,
            "manager_observed_elapsed_seconds": manager_elapsed,
            "downloaded_bytes": downloaded,
            "worker_average_mbps": worker_average_mbps,
            "worker_sampled_average_mbps": runtime.get("worker_sampled_average_mbps"),
            "total_workers_average_mbps": runtime.get("total_workers_average_mbps"),
            "same_base_domain_other_active_average": runtime.get("same_base_domain_other_active_average"),
            "same_base_domain_including_self_active_average": runtime.get(
                "same_base_domain_including_self_active_average"
            ),
            "rc": rc_value,
            "already": already,
            "failure_reason": event.get("reason") or None,
            "raw_log_path": event.get("raw_log_path"),
        }
        try:
            yt_grid.record_trial(
                database=ytdlp_grid_db,
                trial_id=ws.ytdlp_grid_trial_id,
                status=status,
                metric_value=metric_value,
                metadata=metadata,
            )
            yt_grid.append_raw_result(ytdlp_grid_db, {**metadata, "status": status, "metric_value": metric_value})
            ws.ytdlp_grid_recorded = True
            mlog.info(f"[{ws.slot:02d}] YTDLP_GRID_RECORD trial={ws.ytdlp_grid_trial_id} status={status}")
        except Exception as exc:
            mlog.error(f"[{ws.slot:02d}] YTDLP_GRID_RECORD_FAILED trial={ws.ytdlp_grid_trial_id}: {exc}")

    def _assign(ws: WorkerState) -> bool:
        nonlocal pool, priority_pool
        if controlled_quit:
            return False

        _max_per = getattr(args, "unique_domain_dls", -1)
        if bool(args.yt_dlp_grid_search) and (not isinstance(_max_per, int) or _max_per < 1):
            _max_per = max(1, int(args.threads or 1))
        _use_index = (
            domain_index is not None
            and isinstance(_max_per, int)
            and _max_per >= 1
        )

        # ---- Domain-index path (single-URL assignment) --------------------
        if _use_index:
            assert domain_index is not None  # narrowing
            # Active domain counts — only workers with a RUNNING process hold a domain
            # slot. Idle/waiting workers have stale url_current from their previous
            # download; counting those would incorrectly block new assignments.
            active_counts: Dict[str, int] = {}
            for w in workers:
                if not w.proc:
                    continue  # finished or waiting — does not occupy a domain slot
                url = w.url_current
                if url and url != "-":
                    d = _domain_of_url(url)
                    if d != "-":
                        active_counts[d] = active_counts.get(d, 0) + 1

            # File-priority map: file_id -> rank (lower = better)
            fp_map: Dict[int, int] = {}
            for fid, fpath in domain_index._file_map.items():
                fp_map[fid] = url_rankings.get(str(Path(fpath).resolve()), 999_999)

            scan_log: List[ScanLogEntry] = []
            entry = domain_index.pick_url(active_counts, _max_per, fp_map, scan_log)

            # Write scan log to worker's prog log
            for sl in scan_log:
                _wlog(ws, f"DOMAIN_{sl.kind}", sl.message)

            if entry is None:
                if not ws.is_waiting_domain:
                    ws.is_waiting_domain = True
                    ws.waiting_domain_since = time.time()
                    _wlog(ws, "DOMAIN_WAIT",
                          f"all domain slots filled (max={_max_per}); will retry each tick")
                    mlog.info(f"[{ws.slot:02d}] DOMAIN_WAIT no URL available (max={_max_per}/domain)")
                return False

            # Write a single-URL temp file so downloader.py sees a normal URL file
            tmp_dir = Path(log_dir) / "tmp_urls"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = tmp_dir / f"w{ws.slot:02d}_{entry.file_id}_{entry.line_num}.txt"
            tmp_file.write_text(entry.url + "\n", encoding="utf-8")

            original_file = Path(entry.file_path)
            canonical_dir = (download_root / original_file.stem).resolve()

            mlog.info(
                f"[{ws.slot:02d}] ASSIGN_URL {_domain_of_url(entry.url)} "
                f"→ {original_file.name}:{entry.line_num}  {entry.url}"
            )
            _wlog(ws, "DOMAIN_FOUND",
                  f"{_domain_of_url(entry.url)} → {original_file.name} line {entry.line_num}")

            # Reset worker state
            ws.is_waiting_domain = False
            ws.waiting_domain_since = 0.0
            ws.url_entry = entry
            ws.original_urlfile = original_file
            # Pre-set url_current so domain counts are correct immediately
            ws.url_current = entry.url
            _clear_ytdlp_grid_state(ws)
            ytdlp_grid_config_file: Optional[Path] = None
            if args.yt_dlp_grid_search and not _domain_of_url(entry.url).endswith("aebn.com"):
                try:
                    assert ytdlp_grid_db is not None
                    trial_payload = yt_grid.create_trial(
                        database=ytdlp_grid_db,
                        experiment=args.yt_dlp_grid_experiment,
                        url=entry.url,
                        base_domain=_domain_of_url(entry.url),
                        worker_slot=ws.slot,
                        source_urlfile=str(original_file),
                    )
                    ytdlp_grid_config_dir = Path(log_dir) / "grid_trials"
                    ytdlp_grid_config_file = yt_grid.write_trial_config(
                        ytdlp_grid_config_dir / f"{trial_payload['trial_id']}.json",
                        trial_payload,
                    )
                    ws.ytdlp_grid_trial_id = str(trial_payload["trial_id"])
                    ws.ytdlp_grid_config = dict(trial_payload.get("config") or {})
                    ws.ytdlp_grid_config_path = ytdlp_grid_config_file
                    ws.ytdlp_grid_source_urlfile = str(original_file)
                    _wlog(ws, "YTDLP_GRID", f"trial={ws.ytdlp_grid_trial_id} config={ws.ytdlp_grid_config}")
                except Exception as exc:
                    try:
                        domain_index.requeue_url(entry.url)
                    except Exception:
                        pass
                    mlog.error(f"[{ws.slot:02d}] YTDLP_GRID_CREATE_FAILED url={entry.url}: {exc}")
                    return False
            _clear_worker_progress(ws)
            ws.url_index = None
            ws.destination = None
            ws.url_t0 = 0.0
            ws.assign_t0 = time.time()
            ws.rc = None
            ws.last_already = False
            ws.controlled_stopped = False
            ws.overlay_msg = None
            ws.overlay_since = 0.0
            ws.url_count = 1  # single URL assignment
            ws.cap_mibs = (
                float(args.max_process_dl_speed)
                if isinstance(args.max_process_dl_speed, (int, float))
                and args.max_process_dl_speed and args.max_process_dl_speed > 0
                else None
            )
            ws.prog_log_path = _worker_prog_log_path(ws)
            ws.urlfile = tmp_file
            ws.canonical_dir = canonical_dir
            ws.proc = _start_worker(
                ws.slot,
                tmp_file,
                download_root,
                args.max_ndjson_rate,
                args.quiet,
                archive_dir,
                log_dir,
                ws.cap_mibs,
                args.proxy_dl_location,
                args.max_resolution,
                controlled_quit_sentinel,
                no_extdl_fallback=getattr(args, "no_extdl_fallback", False),
                extdl_max_candidates=getattr(args, "extdl_max_candidates", 5),
                extdl_browser_wait=getattr(args, "extdl_browser_wait", 12.0),
                extdl_capture_browser=getattr(args, "extdl_capture_browser", "auto"),
                skip_simulate_check=getattr(args, "skip_simulate_check", False),
                canonical_dir_override=canonical_dir,
                stall_seconds=getattr(args, "stall_seconds", 4),
                ytdlp_grid_config_file=ytdlp_grid_config_file,
            )
            # Create a fresh stop event so the old reader's captured reference
            # (set by _requeue) keeps firing while the new reader starts clean.
            ws.reader_stop = threading.Event()
            ws.reader = threading.Thread(target=_reader, args=(ws,), daemon=True)
            ws.reader.start()
            return True

        # ---- File-level assignment (no domain index / -D off) -------------
        finished: set[str] = set()
        if finished_log.exists():
            try:
                finished = set(x.strip() for x in finished_log.read_text(encoding="utf-8").splitlines() if x.strip())
            except Exception:
                finished = set()

        priority_avail = [
            p
            for p in priority_pool
            if str(p.resolve()) not in active and str(p.resolve()) not in finished and _remaining_for_path(p) != 0
        ]
        if priority_avail:
            selected = _select_priority(priority_avail)
            if selected is None:
                if not ws.is_waiting_domain:
                    ws.is_waiting_domain = True
                    ws.waiting_domain_since = time.time()
                    mlog.info(f"[{ws.slot:02d}] ASSIGN DEFERRED (priority) – domain slots full")
                return False
            urlfile = selected
            priority_pool = [p for p in priority_pool if p != urlfile]
            mlog.info(f"[{ws.slot:02d}] ASSIGN PRIORITY {urlfile}")
        else:
            avail = [
                p
                for p in pool
                if str(p.resolve()) not in active and str(p.resolve()) not in finished and _remaining_for_path(p) != 0
            ]
            if not avail:
                ws.is_waiting_domain = False
                ws.waiting_domain_since = 0.0
                return False
            urlfile = _select_best(avail)
            if urlfile is None:
                if not ws.is_waiting_domain:
                    ws.is_waiting_domain = True
                    ws.waiting_domain_since = time.time()
                    mlog.info(f"[{ws.slot:02d}] ASSIGN DEFERRED – domain slots full (max={_max_per})")
                return False
            mlog.info(f"[{ws.slot:02d}] ASSIGN {urlfile}")

        ws.is_waiting_domain = False
        ws.waiting_domain_since = 0.0
        ws.url_entry = None
        ws.original_urlfile = None
        _clear_ytdlp_grid_state(ws)
        active.add(str(urlfile.resolve()))
        ws.urlfile = urlfile
        ws.url_count = len(_read_urls(urlfile))
        if archive_dir and ws.url_count > 0:
            prefix = "ae" if ("ae-stars" in str(urlfile.parent)) else "yt"
            arch = archive_dir / f"{prefix}-{urlfile.stem}.txt"
            if arch.exists():
                try:
                    statuses = arch.read_text(encoding="utf-8").splitlines()
                except Exception:
                    statuses = []
                done = sum(1 for s in statuses if s.strip())
                if done >= ws.url_count:
                    try:
                        with finished_log.open("a", encoding="utf-8") as f:
                            f.write(str(urlfile.resolve()) + "\n")
                    except Exception:
                        pass
                    active.discard(str(urlfile.resolve()))
                    mlog.info(f"[{ws.slot:02d}] SKIP finished {urlfile}")
                    return _assign(ws)
        _clear_worker_progress(ws)
        ws.url_index = None
        ws.url_current = None
        ws.destination = None
        ws.url_t0 = 0.0
        ws.assign_t0 = time.time()
        ws.rc = None
        ws.last_already = False
        ws.controlled_stopped = False
        ws.overlay_msg = None
        ws.overlay_since = 0.0
        ws.cap_mibs = (
            float(args.max_process_dl_speed)
            if isinstance(args.max_process_dl_speed, (int, float))
            and args.max_process_dl_speed and args.max_process_dl_speed > 0
            else None
        )
        try:
            ws.prog_log_path = _worker_prog_log_path(ws)
        except Exception:
            ws.prog_log_path = None
        canonical_dir = (download_root / urlfile.stem).resolve()
        ws.canonical_dir = canonical_dir
        ws.proc = _start_worker(
            ws.slot,
            urlfile,
            download_root,
            args.max_ndjson_rate,
            args.quiet,
            archive_dir,
            log_dir,
            ws.cap_mibs,
            args.proxy_dl_location,
            args.max_resolution,
            controlled_quit_sentinel,
            no_extdl_fallback=getattr(args, "no_extdl_fallback", False),
            extdl_max_candidates=getattr(args, "extdl_max_candidates", 5),
            extdl_browser_wait=getattr(args, "extdl_browser_wait", 12.0),
            extdl_capture_browser=getattr(args, "extdl_capture_browser", "auto"),
            skip_simulate_check=getattr(args, "skip_simulate_check", False),
            stall_seconds=getattr(args, "stall_seconds", 4),
        )
        # Create a fresh stop event so the old reader's captured reference
        # (set by _requeue) keeps firing while the new reader starts clean.
        ws.reader_stop = threading.Event()
        ws.reader = threading.Thread(target=_reader, args=(ws,), daemon=True)
        ws.reader.start()
        return True

    def _requeue(ws: WorkerState, finished: bool, reason: str):
        # Domain-index cleanup: if URL didn't get a finish event, requeue it
        if domain_index and ws.url_entry:
            url = ws.url_current or ws.url_entry.url
            if domain_index.is_in_progress(url):
                # Determine if we should requeue or mark failed
                rc = ws.proc.poll() if ws.proc else None
                if rc in (130, 131):
                    # User abort or deadline — return to queue for next session
                    domain_index.requeue_url(url)
                elif not finished:
                    # Stall, bad URL, etc. — also requeue (let simulate/retries handle it)
                    domain_index.requeue_url(url)
        # Delete temp single-URL file if present
        if ws.urlfile and ws.urlfile.parent.name == "tmp_urls":
            try:
                ws.urlfile.unlink(missing_ok=True)
            except Exception:
                pass
        # Cleanup process
        if ws.proc and ws.proc.poll() is None:
            # Resume if paused before terminating
            if ws.is_paused:
                _resume_process(ws.proc)
                ws.is_paused = False
            try:
                ws.proc.terminate()
            except Exception:
                pass
            try:
                ws.proc.wait(timeout=2)
            except Exception:
                pass
        ws.reader_stop.set()
        if ws.reader:
            try:
                ws.reader.join(timeout=1)
            except Exception:
                pass
        if ws.urlfile is not None:
            key = str(ws.urlfile.resolve())
            active.discard(key)
            if finished:
                try:
                    # In domain-index mode record the URL; in file-mode record the path
                    if ws.url_entry is not None:
                        _finished_line = (ws.url_current or ws.url_entry.url) + "\n"
                    else:
                        _finished_line = key + "\n"
                    with finished_log.open("a", encoding="utf-8") as f:
                        f.write(_finished_line)
                except Exception:
                    pass
        mlog.info(f"[{ws.slot:02d}] REQUEUE finished={finished} reason={reason}")
        ws.proc = None
        ws.urlfile = None
        ws.canonical_dir = None
        ws.url_entry = None
        ws.original_urlfile = None
        _clear_ytdlp_grid_state(ws)
        ws.domain_search_file = None
        ws.domain_search_progress = (0, 0)
        # Clear download stats immediately so the UI doesn't show stale progress
        # (e.g. 100% bar from the just-finished download) during the next search/assign.
        _clear_worker_progress(ws)
        ws.is_searching = False
        if finished:
            _schedule_url_scan("post-finish")
            if args.url_preempt:
                _maybe_preempt_workers()

    # Helpers for total throttle
    def _current_speed_mib() -> float:
        return sum(float(w.speed_bps) for w in workers if isinstance(w.speed_bps, (int, float)) and not w.is_paused) / (
            1024 * 1024
        )

    def _can_assign_more() -> bool:
        if controlled_quit:
            return False
        if (
            not isinstance(args.max_total_dl_speed, (int, float))
            or not args.max_total_dl_speed
            or args.max_total_dl_speed <= 0
        ):
            return True
        cur = _current_speed_mib()
        est_add = (
            float(args.max_process_dl_speed)
            if isinstance(args.max_process_dl_speed, (int, float))
            and args.max_process_dl_speed
            and args.max_process_dl_speed > 0
            else 0.0
        )
        return (cur + est_add) <= float(args.max_total_dl_speed)

    def _maybe_preempt_workers() -> None:
        if controlled_quit:
            return
        if not args.url_preempt or not url_order_paths or args.url_random_order:
            return
        finished_set: set[str] = set()
        if finished_log.exists():
            try:
                finished_set = set(
                    x.strip() for x in finished_log.read_text(encoding="utf-8").splitlines() if x.strip()
                )
            except Exception:
                finished_set = set()
        desired: List[str] = []
        for path in url_order_paths:
            key = str(path.resolve())
            remaining = _remaining_for_path(path)
            if key in finished_set or remaining == 0:
                continue
            desired.append(key)
            if len(desired) >= args.threads:
                break
        if not desired:
            return
        active_paths = {str(w.urlfile.resolve()) for w in workers if w.urlfile}
        missing = [key for key in desired if key not in active_paths]
        if not missing:
            return
        victims = [
            w for w in workers if w.urlfile and str(w.urlfile.resolve()) not in desired and w.proc and w.proc.poll() is None
        ]
        if not victims:
            return
        for _ in missing:
            if not victims:
                break
            ws = victims.pop(0)
            mlog.info(f"[{ws.slot:02d}] PREEMPT urlfile={ws.urlfile}")
            _requeue(ws, finished=False, reason="url_preempt")
            if _can_assign_more():
                _assign(ws)

    # Initial fill
    start_gap = 0.0
    if args.time_limit and args.time_limit > 0 and args.threads > 1:
        start_gap = min(10.0, max(1.0, args.time_limit / max(2, args.threads)))

    for idx, ws in enumerate(workers):
        if not _can_assign_more():
            mlog.info("Admission control: delaying assignment due to max-total-dl-speed")
            break
        if not _assign(ws):
            break
        if start_gap and idx < len(workers) - 1:
            time.sleep(start_gap)

    # UI loop
    refresh_dt = 1.0 / max(1.0, float(args.refresh_hz))
    # Interactive verbose pane state: 0=off, 1=NDJSON, 2=Program log
    verbose_mode = 0
    verbose_slot = 1
    selected_worker_slot = workers[0].slot if workers else 1
    active_panel = "downloads"
    # Pause/quit state
    paused = False
    quit_confirm = False

    def _pause_worker_slot(ws: WorkerState) -> bool:
        if not ws.proc or ws.proc.poll() is not None or ws.is_paused:
            return False
        ws.paused_speed_bps = ws.speed_bps
        if _pause_process(ws.proc):
            ws.is_paused = True
            ws.speed_bps = 0.0
            ws.overlay_msg = "PAUSED - process suspended, no downloads active"
            ws.overlay_since = time.time()
            mlog.info(f"[{ws.slot:02d}] PAUSED process PID {ws.proc.pid}")
            return True
        ws.overlay_msg = "PAUSE FAILED - could not suspend process"
        ws.overlay_since = time.time()
        mlog.error(f"[{ws.slot:02d}] Failed to pause process PID {ws.proc.pid}")
        return False

    def _resume_worker_slot(ws: WorkerState) -> bool:
        if not ws.proc or ws.proc.poll() is not None or not ws.is_paused:
            return False
        if _resume_process(ws.proc):
            ws.is_paused = False
            ws.speed_bps = ws.paused_speed_bps
            ws.paused_speed_bps = None
            ws.overlay_msg = None
            mlog.info(f"[{ws.slot:02d}] RESUMED process PID {ws.proc.pid}")
            return True
        mlog.error(f"[{ws.slot:02d}] Failed to resume process PID {ws.proc.pid}")
        return False

    def _toggle_all_workers_pause() -> None:
        nonlocal paused
        paused = not paused
        if paused:
            mlog.info("PAUSE requested - pausing all worker processes")
            for ws in workers:
                _pause_worker_slot(ws)
            return
        mlog.info("UNPAUSE requested - resuming all worker processes")
        for ws in workers:
            if _resume_worker_slot(ws):
                continue
            if not ws.proc:
                _assign(ws)

    def _set_controlled_quit(enabled: bool) -> None:
        nonlocal controlled_quit
        if controlled_quit == enabled:
            return
        controlled_quit = enabled
        if enabled:
            try:
                controlled_quit_sentinel.write_text("controlled quit requested\n", encoding="utf-8")
            except Exception as exc:
                mlog.error(f"Failed to create controlled quit sentinel: {exc}")
            for worker in workers:
                if worker.proc and worker.proc.poll() is None:
                    worker.overlay_msg = "CONTROLLED QUIT - finishing current URL"
                    worker.overlay_since = time.time()
            mlog.info(f"CONTROLLED_QUIT enabled sentinel={controlled_quit_sentinel}")
            return
        try:
            controlled_quit_sentinel.unlink(missing_ok=True)
        except Exception as exc:
            mlog.error(f"Failed to remove controlled quit sentinel: {exc}")
        for worker in workers:
            if worker.overlay_msg == "CONTROLLED QUIT - finishing current URL":
                worker.overlay_msg = None
        mlog.info("CONTROLLED_QUIT disabled")
        if not paused:
            for worker in workers:
                if worker.proc is None and _can_assign_more():
                    _assign(worker)

    def _toggle_selected_worker_pause() -> None:
        nonlocal paused
        ws = next((w for w in workers if w.slot == selected_worker_slot), None)
        if ws is None:
            mlog.error(f"Selected worker {selected_worker_slot} not found")
            return
        if not ws.proc:
            ws.overlay_msg = "No active process for selected worker"
            ws.overlay_since = time.time()
            mlog.info(f"[{ws.slot:02d}] Selected worker has no active process to pause")
            return
        if ws.is_paused:
            _resume_worker_slot(ws)
        else:
            _pause_worker_slot(ws)
        active_workers = [w for w in workers if w.proc and w.proc.poll() is None]
        paused = bool(active_workers) and all(w.is_paused for w in active_workers)

    def _select_worker_delta(delta: int) -> None:
        nonlocal selected_worker_slot, verbose_slot
        if not workers:
            return
        slots = [w.slot for w in workers]
        try:
            idx = slots.index(selected_worker_slot)
        except ValueError:
            idx = 0
        idx = max(0, min(len(slots) - 1, idx + delta))
        selected_worker_slot = slots[idx]
        verbose_slot = selected_worker_slot

    def _build_verbose_lines(slot: int, mode: int, cols: int, rows: int) -> List[str]:
        if not mode:
            return []
        out = ["-" * min(cols, 100)]
        sel = next((w for w in workers if w.slot == slot), None)
        max_lines = max(4, min(60, max(1, rows) // 3))
        if mode == 1:
            out.append(f"Verbose NDJSON [{slot:02d}]"[:cols])
            if sel and sel.ndjson_buf:
                for ln in sel.ndjson_buf[-max_lines:]:
                    out.append(ln[:cols])
            return out
        if mode == 2:
            out.append(f"Program Log [{slot:02d}]"[:cols])

            def _tail_lines(p: Optional[Path], n: int) -> list[str]:
                if not p:
                    return ["<no log path>"]
                try:
                    txt = Path(p).read_text(encoding="utf-8", errors="ignore")
                    arr = txt.splitlines()
                    return arr[-n:]
                except Exception as exc:
                    return [f"<error reading {p}: {exc}>"]

            def _colorize_log(s: str) -> str:
                pairs = [
                    ("FINISH_BAD", "\x1b[31m"),
                    ("BAD", "\x1b[31m"),
                    ("STALLED", "\x1b[31m"),
                    ("DEADLINE", "\x1b[35m"),
                    ("FORCE_EXIT", "\x1b[35m"),
                    ("DUPLICATE", "\x1b[33m"),
                    ("FINISH_SUCCESS", "\x1b[32m"),
                    ("SUCCESS", "\x1b[32m"),
                ]
                result = s
                for token, color in pairs:
                    if token in result:
                        result = result.replace(token, f"{color}{token}\x1b[0m")
                if "\x1b[" in result and not result.endswith("\x1b[0m"):
                    result = result + "\x1b[0m"
                return result

            for ln in _tail_lines(sel.prog_log_path if sel else None, max_lines):
                out.append(_colorize_log(ln)[:cols])
        return out

    try:
        while not stop.is_set():
            if deadline and time.time() >= deadline:
                stop.set()
                break
            watcher_enabled = bool(watcher and watcher.is_enabled())
            now = time.time()
            if url_scan_interval and next_url_scan and now >= next_url_scan:
                if _refresh_url_scan("interval") and args.url_preempt:
                    _maybe_preempt_workers()
            if watcher:
                allow_auto = True
                auto_block_reason = None
                if watcher_auto_delay_until is not None:
                    if now >= watcher_auto_delay_until:
                        watcher_auto_delay_until = None
                        if watcher and not watcher_auto_delay_finish_logged:
                            watcher.log_event("STATE", "Auto-clean delay expired; automatic runs enabled.")
                            watcher_auto_delay_finish_logged = True
                    else:
                        allow_auto = False
                        auto_block_reason = "Watcher auto-clean pending (startup delay)"
                auto_reason = None
                if allow_auto:
                    auto_reason = watcher.update_download_progress(total_completed_bytes)
                if auto_reason:
                    mlog.info(f"MP4 watcher auto-triggered: {auto_reason}")
                watcher_status = watcher.snapshot()
                trigger_bytes_candidate = (
                    watcher_status.config.free_space_trigger_bytes
                    if watcher_status and watcher_status.config.free_space_trigger_bytes
                    else mp4_trigger_free_bytes
                )
                if (not allow_auto) and trigger_bytes_candidate:
                    trig_gib = trigger_bytes_candidate / GIB
                    auto_block_reason = (
                        auto_block_reason or f"Auto-clean queued (free-space trigger {trig_gib:.1f} GiB)."
                    )
            else:
                watcher_status = None
                auto_block_reason = None
            try:
                staging_stats = td_utils.get_disk_stats(proxy_root) if proxy_root else None
            except Exception:
                staging_stats = None
            try:
                destination_stats = td_utils.get_disk_stats(download_root)
            except Exception:
                destination_stats = None
            current_auto_trigger_bytes = (
                watcher_status.config.free_space_trigger_bytes
                if watcher_status and watcher_status.config.free_space_trigger_bytes
                else mp4_trigger_free_bytes
            )
            destination_reserve_bytes = (
                watcher_status.config.destination_space_remaining_bytes
                if watcher_status and watcher_status.config.destination_space_remaining_bytes
                else None
            )
            destination_no_space = bool(
                (watcher_status and watcher_status.destination_no_space)
                or (
                    destination_stats
                    and isinstance(destination_reserve_bytes, int)
                    and destination_reserve_bytes > 0
                    and destination_stats.free_bytes <= destination_reserve_bytes
                )
            )
            # Dynamic total throttle: proportional caps across yt-dlp workers
            now_check = time.time()
            if (
                isinstance(args.max_total_dl_speed, (int, float))
                and args.max_total_dl_speed
                and args.max_total_dl_speed > 0
                and not controlled_quit
            ):
                cap = float(args.max_total_dl_speed)
                total_mib = sum(
                    float(w.speed_bps) for w in workers if isinstance(w.speed_bps, (int, float)) and not w.is_paused
                ) / (1024 * 1024)
                elig = [
                    w
                    for w in workers
                    if w.proc
                    and w.downloader == "yt-dlp"
                    and isinstance(w.speed_bps, (int, float))
                    and w.speed_bps
                    and w.speed_bps > 0
                    and not w.is_paused
                ]
                elig_sum = sum((float(w.speed_bps) / (1024 * 1024)) for w in elig)
                non_elig_mib = max(0.0, total_mib - elig_sum)
                budget = max(0.0, cap - non_elig_mib)
                if total_mib > cap * 1.05 and elig:
                    # Proportional scaling to stay under budget
                    if elig_sum <= 0.0:
                        target_each = budget / len(elig) if budget > 0 else 0.5
                        targets = {w: target_each for w in elig}
                    else:
                        scale = budget / elig_sum if elig_sum > 0 else 0.0
                        targets = {w: max(0.25, (float(w.speed_bps) / (1024 * 1024)) * scale) for w in elig}
                    for w, tgt in targets.items():
                        # Respect per-process cap if set
                        if (
                            isinstance(args.max_process_dl_speed, (int, float))
                            and args.max_process_dl_speed
                            and args.max_process_dl_speed > 0
                        ):
                            tgt = min(tgt, float(args.max_process_dl_speed))
                        # Change only if significant and cooldown passed
                        if (w.cap_mibs is None or abs(tgt - w.cap_mibs) > 0.25) and (
                            now_check - w.last_throttle_t
                        ) > 3.0:
                            w.last_throttle_t = now_check
                            mlog.info(
                                f"[{w.slot:02d}] THROTTLE total={total_mib:.2f}MiB/s -> cap {tgt:.2f}MiB/s (budget {budget:.2f})"
                            )
                            try:
                                if w.proc and w.proc.poll() is None:
                                    w.proc.terminate()
                                    w.proc.wait(timeout=2)
                            except Exception:
                                pass
                            if w.urlfile:
                                w.cap_mibs = max(0.25, tgt)
                                w.reader_stop.set()
                                if w.reader:
                                    try:
                                        w.reader.join(timeout=1)
                                    except Exception:
                                        pass
                                w.reader_stop = threading.Event()
                                try:
                                    w.prog_log_path = (Path(log_dir) / f"ytaedler-worker-{w.slot:02d}.log").resolve()
                                except Exception:
                                    w.prog_log_path = None
                                    w.proc = _start_worker(
                                        w.slot,
                                        w.urlfile,
                                        download_root,
                                        args.max_ndjson_rate,
                                        args.quiet,
                                        archive_dir,
                                        log_dir,
                                        w.cap_mibs,
                                        args.proxy_dl_location,
                                        args.max_resolution,
                                        controlled_quit_sentinel,
                                    )
                                w.reader = threading.Thread(target=_reader, args=(w,), daemon=True)
                                w.reader.start()
                elif total_mib < cap * 0.60:
                    # Gently increase caps back toward per-process cap (if any)
                    for w in elig:
                        if w.cap_mibs and (now_check - w.last_throttle_t) > 5.0:
                            target = (
                                float(args.max_process_dl_speed)
                                if isinstance(args.max_process_dl_speed, (int, float))
                                and args.max_process_dl_speed
                                and args.max_process_dl_speed > 0
                                else None
                            )
                            new_cap = w.cap_mibs * 1.2
                            if target:
                                new_cap = min(new_cap, target)
                            if new_cap > w.cap_mibs + 0.25:
                                w.last_throttle_t = now_check
                                mlog.info(
                                    f"[{w.slot:02d}] UNTHROTTLE total={total_mib:.2f}MiB/s -> cap {new_cap:.2f}MiB/s"
                                )
                                try:
                                    if w.proc and w.proc.poll() is None:
                                        w.proc.terminate()
                                        w.proc.wait(timeout=2)
                                except Exception:
                                    pass
                                if w.urlfile:
                                    w.cap_mibs = new_cap
                                    w.reader_stop.set()
                                    if w.reader:
                                        try:
                                            w.reader.join(timeout=1)
                                        except Exception:
                                            pass
                                    w.reader_stop = threading.Event()
                                    try:
                                        w.prog_log_path = (
                                            Path(log_dir) / f"ytaedler-worker-{w.slot:02d}.log"
                                        ).resolve()
                                    except Exception:
                                        w.prog_log_path = None
                                    w.proc = _start_worker(
                                        w.slot,
                                        w.urlfile,
                                        download_root,
                                        args.max_ndjson_rate,
                                        args.quiet,
                                        archive_dir,
                                        log_dir,
                                        w.cap_mibs,
                                        args.proxy_dl_location,
                                        args.max_resolution,
                                        controlled_quit_sentinel,
                                    )
                                    w.reader = threading.Thread(target=_reader, args=(w,), daemon=True)
                                    w.reader.start()
            # Check time limit and exits
            for ws in workers:
                if not ws.proc:
                    continue
                # time limit
                if args.time_limit is not None and args.time_limit > 0:
                    if (time.time() - ws.assign_t0) > args.time_limit:
                        _requeue(ws, finished=False, reason="time_limit")
                        _refresh_url_scan("time_limit")
                        if not paused and not controlled_quit:
                            _assign(ws)
                        continue
                # exit
                rc = ws.proc.poll()
                if rc is not None:
                    ws.rc = rc
                    finished = rc == 0 and not ws.controlled_stopped
                    _requeue(ws, finished=finished, reason=f"exit rc={rc}")
                    # Assign a new one if available (only if not paused)
                    if not paused and not controlled_quit:
                        _assign(ws)

            # Build frame lines and redraw whole screen
            try:
                term_size = os.get_terminal_size()
                cols = term_size.columns
                rows = term_size.lines
            except OSError:
                cols, rows = 80, 40

            lines: List[str] = []

            manager_elapsed = time.time() - t0
            total_completed_bytes = sum(ws.downloaded_bytes or 0 for ws in workers if ws.rc == 0)
            total_speed_bps = sum(
                float(w.speed_bps) for w in workers if isinstance(w.speed_bps, (int, float)) and not w.is_paused
            )
            _grid_sample_now = time.time()
            for _grid_worker in _active_grid_workers():
                _update_worker_grid_runtime(_grid_worker, _grid_sample_now)
            total_speed_mib = total_speed_bps / (1024 * 1024) if total_speed_bps else 0.0
            inprog_bytes = sum(int(w.downloaded_bytes) for w in workers if isinstance(w.downloaded_bytes, int))
            agg_bytes = total_completed_bytes + inprog_bytes
            avg_mib_s = (agg_bytes / max(1.0, (time.time() - t0))) / (1024 * 1024)
            avg_speed_bps = avg_mib_s * (1024 * 1024)
            active_domain_values = sorted(_active_domains())
            active_domain_count = len(active_domain_values)
            avg_domain_count = domain_diversity_avg.update(active_domain_count)
            domain_summary = ",".join(active_domain_values[:3])
            if len(active_domain_values) > 3:
                domain_summary += ",+"

            # Update web mirror
            if td_available and td_dash:
                try:
                    if not td_lines_built:
                        # Build header and totals lines
                        from termdash import Stat, Line  # type: ignore
                        header = Line("header", stats=[Stat("title", "DL Manager", prefix="")], style="header")
                        td_dash.add_line("header", header, at_top=True)
                        td_dash.add_separator()
                        totals = Line("totals", stats=[
                            Stat("speed", _format_download_rate(total_speed_bps), prefix="Speed: ", unit=""),
                            Stat("avg", _format_download_rate(avg_speed_bps), prefix="Avg: ", unit=""),
                            Stat("downloaded", _format_download_bytes(agg_bytes), prefix="Downloaded: ", unit=""),
                            Stat("started", total_started_urls, prefix="Started: "),
                            Stat("processed", total_processed_urls, prefix="Processed: "),
                            Stat("completed", total_completed_urls, prefix="Completed: "),
                        ])
                        td_dash.add_line("totals", totals)
                        td_dash.add_separator()
                        # Build per-worker lines
                        for ws in workers:
                            line = Line(f"worker_{ws.slot}", stats=[
                                Stat("slot", f"[{ws.slot:02d}]", prefix=""),
                                Stat("name", ws.urlfile.name if ws.urlfile else "idle", prefix=""),
                                Stat("url", f"URL {ws.url_index or 0}/{ws.url_count or 0}", prefix=""),
                                Stat("elapsed", "00:00:00", prefix="Elapsed: "),
                                Stat("pct", "?%", prefix="Pct: "),
                                Stat("speed", "?/s", prefix="Speed: "),
                                Stat("eta", "?", prefix="ETA: "),
                                Stat("sizes", "", prefix=""),
                            ])
                            td_dash.add_line(f"worker_{ws.slot}", line)
                        td_lines_built = True
                    else:
                        # Update totals
                        td_dash.update_stat("totals", "speed", _format_download_rate(total_speed_bps))
                        td_dash.update_stat("totals", "avg", _format_download_rate(avg_speed_bps))
                        td_dash.update_stat("totals", "downloaded", _format_download_bytes(agg_bytes))
                        td_dash.update_stat("totals", "started", total_started_urls)
                        td_dash.update_stat("totals", "processed", total_processed_urls)
                        td_dash.update_stat("totals", "completed", total_completed_urls)
                        # Update workers
                        now = time.time()
                        for ws in workers:
                            name = ws.urlfile.name if (ws.urlfile) else "idle"
                            url_idx = f"URL {ws.url_index or 0}/{ws.url_count or 0}"
                            elapsed = _hms(now - ws.assign_t0) if ws.urlfile else "00:00:00"
                            pct = f"{ws.percent:.2f}%" if isinstance(ws.percent, (int, float)) else "?%"
                            if ws.is_paused:
                                sp = "PAUSED"
                            else:
                                sp = (
                                    _format_download_rate(ws.speed_bps).replace(" ", "")
                                    if isinstance(ws.speed_bps, (int, float)) and ws.speed_bps is not None
                                    else "?/s"
                                )
                            if isinstance(ws.eta_s, (int, float)):
                                eta_val = float(ws.eta_s)
                                is_near_done = isinstance(ws.percent, (int, float)) and ws.percent >= 99.5
                                eta_txt = _hms(eta_val) if (eta_val > 0 or is_near_done) else "?"
                            else:
                                eta_txt = "?"
                            sizes = (
                                f"{_human_short_bytes(ws.downloaded_bytes)}/{_human_short_bytes(ws.total_bytes)}"
                                if (isinstance(ws.downloaded_bytes, int) and isinstance(ws.total_bytes, int) and ws.total_bytes)
                                else ""
                            )
                            td_dash.update_stat(f"worker_{ws.slot}", "name", name)
                            td_dash.update_stat(f"worker_{ws.slot}", "url", url_idx)
                            td_dash.update_stat(f"worker_{ws.slot}", "elapsed", elapsed)
                            td_dash.update_stat(f"worker_{ws.slot}", "pct", pct)
                            td_dash.update_stat(f"worker_{ws.slot}", "speed", sp)
                            td_dash.update_stat(f"worker_{ws.slot}", "eta", eta_txt)
                            td_dash.update_stat(f"worker_{ws.slot}", "sizes", sizes)
                except Exception:
                    pass

            if active_panel == "watcher":
                layout_meta: Dict[str, int] = {}
                lines = _render_watcher_panel(
                    cols=cols,
                    rows=rows,
                    watcher_enabled=watcher_enabled,
                    snapshot=watcher_status,
                    quit_confirm=quit_confirm,
                    manager_elapsed=manager_elapsed,
                    total_downloaded_bytes=total_completed_bytes,
                    log_scroll=watcher_log_scroll,
                    log_meta=layout_meta,
                    download_speed_bps=avg_speed_bps,
                    staging_stats=staging_stats,
                    destination_stats=destination_stats,
                    auto_trigger_bytes=current_auto_trigger_bytes,
                    auto_block_reason=auto_block_reason,
                    destination_no_space=destination_no_space,
                )
                watcher_log_meta = {
                    "log_max_scroll": layout_meta.get("log_max_scroll", 0),
                    "log_window": layout_meta.get("log_window", 0),
                }
                if watcher_log_follow:
                    watcher_log_scroll = 0
                else:
                    watcher_log_scroll = min(watcher_log_scroll, watcher_log_meta["log_max_scroll"])
            elif active_panel == "urls":
                total_entries = len(url_scan_state.entries) if url_scan_state else 0
                last_scan_label = (
                    time.strftime("%H:%M:%S", time.localtime(last_url_scan)) if last_url_scan else "never"
                )
                order_desc = f"{url_panel_sort_key} ({'asc' if url_panel_sort_ascending else 'desc'})"
                random_desc = "random" if args.url_random_order else "ranked"
                search_desc = f" | search: {url_panel_name_filter}" if url_panel_name_filter else ""
                lines.append(
                    f"URL Stats Panel | last refresh: {last_scan_label} | entries: {total_entries} "
                    f"| order: {order_desc} {random_desc}{search_desc}"
                )
                lines.append("-" * min(cols, 100))
                if url_scan_state and url_scan_state.entries:
                    filtered_entries = urlscan.filter_entries_by_name(
                        url_scan_state.entries,
                        url_panel_name_filter,
                    )
                    ordered_entries = urlscan.sort_entries(
                        filtered_entries,
                        url_panel_sort_key,
                        url_panel_sort_ascending,
                    )
                    max_rows = max(5, min(25, rows - 8))
                    url_panel_max_top = max(0, len(ordered_entries) - max_rows)
                    url_panel_top = max(0, min(url_panel_top, url_panel_max_top))
                    header_values = [name for name, _, _ in urlscan.INTERACTIVE_COLUMN_LAYOUT]
                    header_line = urlscan._format_interactive_columns(header_values)
                    visible_entries = ordered_entries[url_panel_top : url_panel_top + max_rows]
                    table_lines: List[str] = [header_line]
                    for entry in visible_entries:
                        row_values = [
                            entry.name,
                            urlscan.format_int(entry.total_unique_urls),
                            urlscan.format_int(entry.ae_line_count),
                            urlscan.format_int(entry.stars_unique_urls),
                            urlscan.format_int(entry.mp4_count),
                            urlscan.format_int(entry.remaining),
                            urlscan.format_ratio(entry.ratio),
                            f"{entry.mp4_bytes / urlscan.GBYTES:.2f}",
                        ]
                        table_lines.append(urlscan._format_interactive_columns(row_values))
                    if url_panel_name_filter:
                        table_lines.append(f"Matches: {len(ordered_entries)} / {total_entries}")
                    max_line_len = max((len(line) for line in table_lines), default=0)
                    url_panel_max_scroll = max(0, max_line_len - cols + 2)
                    url_panel_scroll = max(0, min(url_panel_scroll, url_panel_max_scroll))
                    for line in table_lines:
                        lines.append(line[url_panel_scroll : url_panel_scroll + cols])
                    lines.append(urlscan.build_summary_line(url_scan_state.totals)[:cols])
                else:
                    lines.append("No scan data available. Press 'r' to run a scan.")
                lines.append("-" * min(cols, 100))
                auto_label = td_utils.color_text("ON", "green") if url_panel_auto_refresh else td_utils.color_text("OFF", "red")
                lines.append(
                    f"Auto refresh: {auto_label} | Keys: d=downloads, w=watcher, r=rescan, "
                    f"a=toggle auto, s=sort, /=search, Esc=clear, j/k=vert, h/l=horz, q=quit"
                )
                if (
                    url_panel_auto_refresh
                    and last_url_scan
                    and (time.time() - last_url_scan) >= URL_PANEL_AUTO_INTERVAL
                ):
                    _refresh_url_scan("url-panel-auto")
            else:
                # Downloads panel
                active_workers = sum(1 for w in workers if w.proc)
                current_regular, current_priority = _gather_from_roots(roots, finished_log, args.priority_files)
                total_available = len([p for p in current_regular if str(p.resolve()) not in active]) + len(
                    [p for p in current_priority if str(p.resolve()) not in active]
                )
                if controlled_quit:
                    controlled_label = td_utils.color_text("CONTROLLED QUIT", "red")
                    lines.append(f"{controlled_label} eta {_controlled_quit_eta_label(workers)}"[:cols])
                if downloads_status_visible:
                    # Header
                    pause_tag = td_utils.color_text(" [PAUSED]", "yellow") if paused else ""
                    quit_tag = td_utils.color_text(" [Press Y to confirm quit]", "red") if quit_confirm else ""
                    active_label = td_utils.color_text(str(active_workers), "green" if active_workers > 0 else "gray")
                    pool_label = td_utils.color_text(str(total_available), "cyan" if total_available > 0 else "gray")
                    _udl = getattr(args, "unique_domain_dls", -1)
                    domain_lock_tag = td_utils.color_text(f" [D:{_udl}]", "cyan") if isinstance(_udl, int) and _udl >= 1 else ""
                    header = (
                        f"DL Manager{pause_tag}{quit_tag}{domain_lock_tag}"
                        f"  |  threads={args.threads}"
                        f"  active={active_label}"
                        f"  pool={pool_label}"
                        f"  elapsed={_hms(manager_elapsed)}"
                    )
                    lines.append(header[:cols])
                    # Totals bar
                    speed_color = "cyan" if total_speed_mib >= 1.0 else ("yellow" if total_speed_mib > 0 else "gray")
                    speed_str = td_utils.color_text(_format_download_rate(total_speed_bps), speed_color)
                    avg_str = f"avg {_format_download_rate(avg_speed_bps)}"
                    dl_str = td_utils.color_text(_format_download_bytes(agg_bytes), "bright")
                    started_str = td_utils.color_text(str(total_started_urls), "bright")
                    done_str = td_utils.color_text(str(total_completed_urls), "green")
                    dup_count = total_processed_urls - total_completed_urls
                    dup_str = td_utils.color_text(str(dup_count), "yellow") if dup_count else str(dup_count)
                    lines.append(
                        f"Speed: {speed_str}  {avg_str}  DL: {dl_str}"
                        f"  URLs: {started_str} started / {done_str} done / {dup_str} dup"
                        f"  Domains: {active_domain_count} now / {avg_domain_count:.1f} avg"[:cols]
                    )
                    if domain_summary:
                        unique_total = domain_index.total_unique_domains if domain_index else 0
                        unique_suffix = f" / {unique_total} unique" if unique_total else ""
                        lines.append(f"Active domains: {domain_summary}{unique_suffix}"[:cols])
                    for storage_line in _storage_summary_lines(
                        staging_stats,
                        destination_stats,
                        threshold_bytes=current_auto_trigger_bytes,
                        download_speed_bps=avg_speed_bps,
                    ):
                        lines.append(storage_line[:cols])
                if destination_no_space:
                    lines.append(td_utils.color_text("NO DISK SPACE LEFT AT FINAL DESTINATION", "red")[:cols])
                if auto_block_reason:
                    lines.append(td_utils.color_text(auto_block_reason, "yellow")[:cols])
                if downloads_status_visible or controlled_quit or destination_no_space or auto_block_reason:
                    lines.append("-" * min(cols, 100))
                downloads_header_rows = len(lines)
                now = time.time()

                def col(text: str, width: int) -> str:
                    return (text[:width]).ljust(width)

                # Build quartiles for color-coding speeds
                speeds = [
                    float(w.speed_bps)
                    for w in workers
                    if isinstance(w.speed_bps, (int, float)) and w.speed_bps and w.speed_bps > 0
                ]
                speeds.sort()

                def _quantile(xs, q):
                    if not xs:
                        return None
                    idx = int(round((len(xs) - 1) * q))
                    return xs[max(0, min(len(xs) - 1, idx))]

                q1 = _quantile(speeds, 0.25)
                q2 = _quantile(speeds, 0.50)
                q3 = _quantile(speeds, 0.75)

                def speed_color_prefix(sp_bps: Optional[float]) -> str:
                    try:
                        v = float(sp_bps)
                    except Exception:
                        return "\x1b[37m"
                    if not speeds or q1 is None or q2 is None or q3 is None:
                        return "\x1b[37m"
                    if v <= q1:
                        return "\x1b[31m"  # red
                    if v <= q2:
                        return "\x1b[33m"  # yellow
                    if v <= q3:
                        return "\x1b[32m"  # green
                    return "\x1b[36m"  # cyan

                def make_bar(pct: Optional[float], width: int, color_prefix: str = "") -> str:
                    try:
                        p = float(pct)
                    except Exception:
                        p = -1
                    inner = max(0, width - 2)
                    if p < 0:
                        return "[" + ("." * inner) + "]"
                    p = max(0.0, min(100.0, p))
                    filled = int(inner * (p / 100.0))
                    # Always show at least one filled segment while downloading (p > 0)
                    if p > 0 and filled == 0:
                        filled = 1
                    reset = "\x1b[0m"
                    if color_prefix:
                        return "[" + (f"{color_prefix}" + ("=" * filled) + f"{reset}") + ("." * (inner - filled)) + "]"
                    else:
                        return "[" + ("=" * filled) + ("." * (inner - filled)) + "]"

                for ws in workers:
                    # Workers blocked on the domain cap show a distinct waiting row
                    if ws.is_waiting_domain and not ws.proc:
                        wait_elapsed = _hms(now - ws.waiting_domain_since) if ws.waiting_domain_since else "?"
                        sel_marker = ">" if ws.slot == selected_worker_slot else " "
                        idx_stat = ""
                        if domain_index:
                            queued = domain_index.total_queued
                            domains = domain_index.total_unique_domains
                            idx_stat = f"  ({queued} queued / {domains} domains)"
                        wait_line = (
                            f"{sel_marker}[{ws.slot:02d}] "
                            + td_utils.color_text(
                                f"[Waiting: all domain slots taken – max {args.unique_domain_dls}/domain]",
                                "yellow",
                            )
                            + f"  {wait_elapsed}{idx_stat}"
                        )
                        lines.append(wait_line[:cols])
                        continue
                    # For single-URL assignments, show the original file name (not temp file)
                    if ws.original_urlfile:
                        name = ws.original_urlfile.name
                    elif ws.urlfile:
                        name = ws.urlfile.name
                    else:
                        name = "searching..."
                    # Show a → marker in the URL index when between individual URLs
                    if ws.is_searching and ws.urlfile:
                        url_idx = f"\x1b[33m→\x1b[0m URL {ws.url_index or 0}/{ws.url_count or 0}"
                    else:
                        url_idx = f"URL {ws.url_index or 0}/{ws.url_count or 0}"
                    domain_txt = _top_domain(ws.url_current)
                    elapsed = _hms(now - ws.assign_t0) if ws.urlfile else "00:00:00"
                    pct = f"{ws.percent:.2f}%" if isinstance(ws.percent, (int, float)) else "?%"
                    if ws.is_paused:
                        sp = "PAUSED"
                    else:
                        sp = (
                            _format_download_rate(ws.speed_bps).replace(" ", "")
                            if isinstance(ws.speed_bps, (int, float)) and ws.speed_bps is not None
                            else "?/s"
                        )
                    # Render ETA; if near completion and eta ≤ 0, show '?' to avoid stuck 00:00:00
                    if isinstance(ws.eta_s, (int, float)):
                        eta_val = float(ws.eta_s)
                        is_near_done = isinstance(ws.percent, (int, float)) and ws.percent >= 99.5
                        eta_txt = _hms(eta_val) if (eta_val > 0 or is_near_done) else "?"
                    else:
                        eta_txt = "?"
                    has_dl = isinstance(ws.downloaded_bytes, int)
                    has_tot = isinstance(ws.total_bytes, int) and ws.total_bytes
                    dl_txt = _human_short_bytes(ws.downloaded_bytes) if has_dl else ""
                    tot_txt = _human_short_bytes(ws.total_bytes) if has_tot else ""
                    sel_marker = ">" if ws.slot == selected_worker_slot else " "

                    if cols >= 110:
                        # Single row packed
                        tag = "[Y]" if ws.downloader == "yt-dlp" else ("[A]" if ws.downloader == "aebndl" else "   ")
                        c0 = col(f"{sel_marker}[{ws.slot:02d}]", 5)
                        c1 = col(name, 40)
                        c2 = col(url_idx, 12)
                        c3 = col(f"Elapsed {elapsed}", 16)
                        c4 = col(pct, 8)
                        c5 = col(sp, 12)
                        c6 = col(f"ETA {eta_txt}", 12)
                        c7 = col(f"Dom {domain_txt}", 20)
                        c8 = col(dl_txt, 10)
                        c9 = col(tot_txt, 10)
                        mainline = " | ".join([c0, c1, c2, c3, c4, c5, c6, c7, c8, c9])[:cols]
                        lines.append(ws.overlay_msg[:cols] if ws.overlay_msg else mainline)
                        barw = max(20, cols - 8)
                        lines.append(
                            f"  {sel_marker}{tag}  "
                            + make_bar(ws.percent, barw, speed_color_prefix(ws.speed_bps))[: max(0, cols - 7)]
                        )
                    elif cols >= 90:
                        # Two rows
                        tag = "[Y]" if ws.downloader == "yt-dlp" else ("[A]" if ws.downloader == "aebndl" else "   ")
                        c0 = col(f"{sel_marker}[{ws.slot:02d}]", 5)
                        c1 = col(name, 36)
                        c2 = col(url_idx, 12)
                        c3 = col(dl_txt, 10)
                        c4 = col(tot_txt, 10)
                        main1 = " | ".join([c0, c1, c2, c3, c4])[:cols]
                        lines.append(ws.overlay_msg[:cols] if ws.overlay_msg else main1)
                        c0b = col(f"{sel_marker}{tag}", 4)
                        c1b = col(f"Elapsed {elapsed}", 20)
                        c2b = col(pct, 10)
                        c3b = col(sp, 12)
                        c4b = col(f"ETA {eta_txt}", 14)
                        c5b = col(f"Dom {domain_txt}", 20)
                        lines.append(" | ".join([c0b, c1b, c2b, c3b, c4b, c5b])[:cols])
                        barw = max(20, cols - 8)
                        lines.append("     " + make_bar(ws.percent, barw, speed_color_prefix(ws.speed_bps))[:cols])
                    else:
                        # Three rows compact
                        tag = "[Y]" if ws.downloader == "yt-dlp" else ("[A]" if ws.downloader == "aebndl" else "   ")
                        c0 = col(f"{sel_marker}[{ws.slot:02d}]", 5)
                        c1 = col(name, max(20, cols - 7))
                        lines.append(ws.overlay_msg[:cols] if ws.overlay_msg else " | ".join([c0, c1])[:cols])
                        c0b = col(f"{sel_marker}{tag}", 4)
                        c1b = col(f"{url_idx}  Elapsed {elapsed}", max(20, cols - 7))
                        lines.append(" | ".join([c0b, c1b])[:cols])
                        sizes_compact = f"{dl_txt}/{tot_txt}" if (dl_txt or tot_txt) else ""
                        c1c = col(f"{pct}  {sp}  ETA {eta_txt}  Dom {domain_txt}  {sizes_compact}", max(20, cols - 7))
                        lines.append(" | ".join([c0, c1c])[:cols])
                        barw = max(20, cols - 8)
                        lines.append("     " + make_bar(ws.percent, barw, speed_color_prefix(ws.speed_bps))[:cols])

                # Controls and optional verbose pane
                if quit_confirm:
                    downloads_footer_lines = ["Press Y to quit, N to cancel"[:cols]]
                else:
                    downloads_footer_lines = [
                        line[:cols]
                        for line in _wrap_hotkey_lines(_downloads_footer_text(), cols)
                    ]
                verbose_lines = _build_verbose_lines(verbose_slot, verbose_mode, cols, rows)
                # Reserve rows for the footer (always pinned last) and the verbose panel.
                # This ensures the hotkey guide is always visible at the bottom of the screen
                # regardless of how many workers or how large the verbose panel is.
                footer_row_count = len(downloads_footer_lines)
                verbose_row_count = len(verbose_lines)
                downloads_rows = max(1, rows - verbose_row_count - footer_row_count)
                lines, downloads_panel_max_scroll = _apply_pinned_viewport(
                    lines,
                    rows=downloads_rows,
                    header_rows=downloads_header_rows,
                    footer_rows=0,  # footer is rendered outside the viewport
                    scroll=downloads_panel_scroll,
                )
                downloads_panel_scroll = min(downloads_panel_scroll, downloads_panel_max_scroll)
                # Append verbose panel then footer so keys are always visible at the bottom
                lines.extend(verbose_lines)
                lines.extend(downloads_footer_lines)
                lines = lines[:rows]

            # Keyboard handling (for both panels)
            if os.name == "nt":
                try:
                    import msvcrt  # type: ignore

                    while msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch in ("\x00", "\xe0"):
                            special = msvcrt.getwch()
                            if active_panel == "downloads":
                                if special == "H":
                                    _select_worker_delta(-1)
                                elif special == "P":
                                    _select_worker_delta(1)
                            continue
                        key = ch.lower() if ch else ""
                        if quit_confirm:
                            # Handle quit confirmation
                            if key == "y":
                                stop.set()
                                break
                            elif key == "n":
                                quit_confirm = False
                        else:
                            # Normal key handling
                            if not key:
                                continue
                            if key == "d":
                                active_panel = "downloads"
                                continue
                            if key == "w":
                                active_panel = "watcher"
                                continue
                            if key == "u":
                                active_panel = "urls"
                                continue
                            if active_panel == "urls":
                                if key == "a":
                                    url_panel_auto_refresh = not url_panel_auto_refresh
                                elif key == "r":
                                    _refresh_url_scan("url-panel-manual")
                                elif key == "s":
                                    url_panel_sort_key, url_panel_sort_ascending = _cycle_url_sort(
                                        url_panel_sort_key,
                                        url_panel_sort_ascending,
                                    )
                                    url_panel_top = 0
                                    url_panel_scroll = 0
                                elif ch == "/":
                                    response = _prompt_text("URL name search (glob allowed, blank=clear)")
                                    url_panel_name_filter = response or ""
                                    url_panel_top = 0
                                    url_panel_scroll = 0
                                elif ch == "\x1b":
                                    url_panel_name_filter = ""
                                    url_panel_top = 0
                                    url_panel_scroll = 0
                                elif key in ("j",):
                                    url_panel_top = min(url_panel_top + 1, url_panel_max_top)
                                elif key in ("k",):
                                    url_panel_top = max(0, url_panel_top - 1)
                                elif key in ("h",):
                                    url_panel_scroll = max(0, url_panel_scroll - 4)
                                elif key in ("l",):
                                    url_panel_scroll = min(url_panel_scroll + 4, url_panel_max_scroll)
                                elif key == "q":
                                    quit_confirm = True
                                continue
                            if active_panel == "watcher":
                                if key == "c" and watcher and watcher_enabled:
                                    if watcher.manual_run(dry_run=False, trigger="manual-ui"):
                                        mlog.info("MP4 watcher run started (manual).")
                                        watcher_log_follow = True
                                    else:
                                        mlog.info("MP4 watcher run request ignored (already running or disabled).")
                                elif key in ("d", "s") and watcher and watcher_enabled:
                                    if watcher.manual_run(dry_run=True, trigger="manual-ui-dry-run"):
                                        mlog.info("MP4 watcher scan (dry-run) started.")
                                        watcher_log_follow = True
                                    else:
                                        mlog.info("MP4 watcher scan request ignored (already running or disabled).")
                                elif key == "o" and watcher and watcher_enabled:
                                    new_op = watcher.toggle_operation()
                                    cfg_snapshot = watcher.config_snapshot()
                                    keep_desc = "keep source" if cfg_snapshot.keep_source else "delete source"
                                    mlog.info(f"MP4 watcher default operation set to {new_op} ({keep_desc}).")
                                elif key == "k" and watcher and watcher_enabled:
                                    response = _prompt_text("Max MP4 files per watcher run (blank=unlimited)")
                                    if response is None:
                                        continue
                                    if not response:
                                        watcher.set_max_files(None)
                                        mlog.info("MP4 watcher max-files set to unlimited.")
                                        continue
                                    try:
                                        new_limit = int(response)
                                    except ValueError:
                                        mlog.error("Invalid max-files value; expected a positive integer.")
                                        continue
                                    limit = watcher.set_max_files(new_limit)
                                    if limit is None:
                                        mlog.info("MP4 watcher max-files set to unlimited.")
                                    else:
                                        mlog.info(f"MP4 watcher max-files set to {limit}.")
                                elif key == "f" and watcher and watcher_enabled:
                                    response = _prompt_text(
                                        "Trigger watcher when staging free space (GiB) drops below (blank=disable)"
                                    )
                                    if response is None:
                                        continue
                                    if not response:
                                        watcher.set_free_space_trigger_gib(None)
                                        mlog.info("MP4 watcher free-space trigger disabled.")
                                        continue
                                    try:
                                        new_threshold = float(response)
                                    except ValueError:
                                        mlog.error("Invalid free-space threshold; expected a number.")
                                        continue
                                    threshold_bytes = watcher.set_free_space_trigger_gib(new_threshold)
                                    if threshold_bytes:
                                        mlog.info(f"MP4 watcher free-space trigger set to {new_threshold:.1f} GiB.")
                                    else:
                                        mlog.info("MP4 watcher free-space trigger disabled.")
                                elif key == "m" and watcher and watcher_enabled:
                                    response = _prompt_text(
                                        "Destination disk space to keep free (examples: 1024MB, 100GB; blank=unlimited)"
                                    )
                                    if response is None:
                                        continue
                                    try:
                                        reserve_bytes = _parse_size_bytes(response)
                                    except argparse.ArgumentTypeError as exc:
                                        mlog.error(f"Invalid destination reserve: {exc}")
                                        continue
                                    current = watcher.set_destination_space_remaining_bytes(reserve_bytes)
                                    if current:
                                        mlog.info(
                                            f"MP4 watcher destination reserve set to {_format_disk_bytes(current)}."
                                        )
                                    else:
                                        mlog.info("MP4 watcher destination reserve disabled.")
                                elif key == "t" and watcher and watcher_enabled:
                                    new_val = watcher.toggle_stay_at_staging()
                                    if new_val:
                                        mlog.info(
                                            "MP4 watcher stay-at-staging enabled: files will not be moved; "
                                            "watcher will only remove inferior duplicates."
                                        )
                                    else:
                                        mlog.info("MP4 watcher stay-at-staging disabled: normal move/copy mode.")
                                elif key == "[" and watcher and watcher_enabled:
                                    step = max(1, watcher_log_meta.get("log_window", 10) // 2 or 1)
                                    watcher_log_scroll = min(
                                        watcher_log_scroll + step,
                                        watcher_log_meta.get("log_max_scroll", 0),
                                    )
                                    watcher_log_follow = watcher_log_scroll == 0
                                elif key == "]" and watcher and watcher_enabled:
                                    step = max(1, watcher_log_meta.get("log_window", 10) // 2 or 1)
                                    watcher_log_scroll = max(0, watcher_log_scroll - step)
                                    watcher_log_follow = watcher_log_scroll == 0
                                elif key == "q":
                                    quit_confirm = True
                                continue
                            if key == "v":
                                try:
                                    verbose_mode = int(verbose_mode)
                                except Exception:
                                    verbose_mode = 0
                                verbose_mode = (verbose_mode + 1) % 3
                            elif ch.isdigit():
                                # Prompt for full worker number so slots 10+ are reachable.
                                response = _prompt_text(f"Select worker (1-{len(workers)}) [{ch}]")
                                try:
                                    n = int(response) if response else int(ch)
                                    if 1 <= n <= len(workers):
                                        verbose_slot = n
                                        selected_worker_slot = n
                                except (ValueError, TypeError):
                                    pass
                            elif ch == "P":
                                _toggle_selected_worker_pause()
                            elif key == "p":
                                _toggle_all_workers_pause()
                            elif key == "x":
                                _set_controlled_quit(not controlled_quit)
                            elif key == "h":
                                downloads_status_visible = not downloads_status_visible
                            elif key == "q":
                                # Request quit confirmation
                                quit_confirm = True
                except Exception:
                    pass
            # Redraw whole frame (reset attributes first to avoid color bleed)
            _render_screen(lines)

            if _controlled_quit_complete(controlled_quit, workers):
                break

            # If all workers idle and both pools empty, stop
            if all(w.proc is None for w in workers):
                current_regular, current_priority = _gather_from_roots(roots, finished_log, args.priority_files)
                if not current_regular and not current_priority:
                    break

            time.sleep(refresh_dt)
    except KeyboardInterrupt:
        stop.set()
    finally:
        try:
            controlled_quit_sentinel.unlink(missing_ok=True)
        except Exception:
            pass
        # Cleanup
        for ws in workers:
            if ws.proc and ws.proc.poll() is None:
                # Resume if paused before terminating
                if ws.is_paused:
                    _resume_process(ws.proc)
                    ws.is_paused = False
                try:
                    ws.proc.terminate()
                except Exception:
                    pass
                try:
                    ws.proc.wait(timeout=2)
                except Exception:
                    pass
            if ws.reader:
                ws.reader_stop.set()
                try:
                    ws.reader.join(timeout=1)
                except Exception:
                    pass
        if url_scan_thread and url_scan_thread.is_alive():
            try:
                url_scan_thread.join(timeout=2)
            except Exception:
                pass
        # Flush domain index on exit
        if domain_index and domain_index_path:
            try:
                domain_index.flush_save()
            except Exception:
                pass
        # Leave cursor below
    return 0


if __name__ == "__main__":
    # Make Ctrl-C stop child process trees on POSIX; on Windows terminate() handles direct child
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
