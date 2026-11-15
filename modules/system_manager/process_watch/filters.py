"""Filtering, sorting, grouping, and column presets for process_watch."""

from __future__ import annotations

import fnmatch
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .models import ProcessGroup, ProcessIdentity, ProcessSample

SORT_FIELDS: Tuple[str, ...] = (
    "cpu",
    "cpu_norm",
    "rss",
    "io_read",
    "io_write",
    "io_total",
    "gpu_mem",
    "name",
    "pid",
    "uptime",
    "threads",
    "peak_cpu",
    "peak_rss",
    "subtree_cpu",
    "subtree_rss",
    "random",
)

COLUMN_PRESETS: Dict[str, List[str]] = {
    "default": ["pid", "name", "cpu", "rss", "io_read", "io_write", "gpu_mem", "uptime"],
    "compact": ["pid", "name", "cpu", "rss", "io_total"],
    "cpu": ["pid", "name", "cpu", "cpu_norm", "peak_cpu", "subtree_cpu", "threads", "uptime"],
    "memory": ["pid", "name", "rss", "private_mem", "vms", "peak_rss", "subtree_rss", "uptime"],
    "io": ["pid", "name", "io_read", "io_write", "io_total", "handles", "uptime"],
    "gpu": ["pid", "name", "gpu_mem", "gpu_id", "gpu_util", "cpu", "rss", "uptime"],
    "comprehensive": [
        "pid",
        "ppid",
        "name",
        "status",
        "user",
        "cpu",
        "cpu_norm",
        "rss",
        "private_mem",
        "vms",
        "io_read",
        "io_write",
        "gpu_mem",
        "threads",
        "handles",
        "peak_cpu",
        "peak_rss",
        "uptime",
    ],
}

COLUMN_DEFS: Dict[str, Tuple[str, bool]] = {
    # key -> (header, right_aligned)
    "pid": ("PID", True),
    "ppid": ("PPID", True),
    "name": ("Process", False),
    "status": ("Status", False),
    "user": ("User", False),
    "exe": ("Executable", False),
    "cpu": ("CPU %", True),
    "cpu_norm": ("Host CPU%", True),
    "rss": ("RSS", True),
    "private_mem": ("Private", True),
    "vms": ("Virtual", True),
    "io_read": ("Proc Read/s", True),
    "io_write": ("Proc Write/s", True),
    "io_total": ("Proc I/O/s", True),
    "gpu_mem": ("GPU Mem", True),
    "gpu_id": ("GPU", True),
    "gpu_util": ("GPU %", True),
    "threads": ("Threads", True),
    "handles": ("Handles", True),
    "peak_cpu": ("Peak CPU%", True),
    "peak_rss": ("Peak RSS", True),
    "subtree_cpu": ("Tree CPU%", True),
    "subtree_rss": ("Tree RSS", True),
    "uptime": ("Uptime", True),
}

GROUP_MODES: Tuple[str, ...] = ("none", "name", "exe", "parent", "root")


@dataclass
class ProcessFilter:
    """Selection and filtering rules for monitored processes."""

    include_globs: List[str] = field(default_factory=list)
    exclude_globs: List[str] = field(default_factory=list)
    pids: List[int] = field(default_factory=list)
    recursive: bool = False
    match_cmdline: bool = False
    search_text: str = ""

    def has_selectors(self) -> bool:
        return bool(self.include_globs or self.exclude_globs or self.pids or self.search_text.strip())


def expand_pid_scope(
    seed_pids: Sequence[int],
    children_map: Dict[int, List[int]],
    *,
    recursive: bool,
) -> Set[int]:
    """Expand seed PIDs to include descendants when recursive=True."""
    allowed: Set[int] = {int(p) for p in seed_pids}
    if not recursive or not allowed:
        return allowed
    stack = list(allowed)
    while stack:
        current = stack.pop()
        for child in children_map.get(current, ()):
            if child not in allowed:
                allowed.add(child)
                stack.append(child)
    return allowed


def _matches_any_glob(sample: ProcessSample, globs: Sequence[str], *, match_cmdline: bool) -> bool:
    name_l = (sample.name or "").lower()
    exe_l = (sample.exe or "").lower()
    cmd_l = (sample.cmdline_raw or "").lower() if match_cmdline else ""
    for pattern in globs:
        pat_l = pattern.lower()
        if fnmatch.fnmatch(name_l, pat_l):
            return True
        if exe_l and fnmatch.fnmatch(exe_l, pat_l):
            return True
        if match_cmdline and cmd_l and fnmatch.fnmatch(cmd_l, pat_l):
            return True
    return False


def filter_processes(
    samples: Sequence[ProcessSample],
    flt: ProcessFilter,
    children_map: Dict[int, List[int]],
    *,
    always_include_identities: Optional[Set[ProcessIdentity]] = None,
) -> List[ProcessSample]:
    """Filter processes using PIDs, include globs (OR), exclude globs, and live search text.

    Exclusions apply after PID/descendant expansion so noisy children can still be excluded.
    Pinned/selected identities passed in ``always_include_identities`` are never dropped by
    transient filtering if callers want them retained separately, though normally Pinned tab
    tracks pinned processes independently.
    """
    allowed_pids: Optional[Set[int]] = None
    if flt.pids:
        allowed_pids = expand_pid_scope(flt.pids, children_map, recursive=flt.recursive)

    search = flt.search_text.strip().lower()
    result: List[ProcessSample] = []

    for sample in samples:
        if always_include_identities and sample.identity in always_include_identities:
            # Caller explicitly asked to retain (not used for main filter unless requested).
            pass

        if allowed_pids is not None and sample.pid not in allowed_pids:
            continue

        if flt.include_globs and not _matches_any_glob(
            sample, flt.include_globs, match_cmdline=flt.match_cmdline
        ):
            continue

        if flt.exclude_globs and _matches_any_glob(
            sample, flt.exclude_globs, match_cmdline=flt.match_cmdline
        ):
            continue

        if search:
            haystack = f"{sample.pid} {sample.name} {sample.exe} {sample.username}".lower()
            if flt.match_cmdline:
                haystack = f"{haystack} {sample.cmdline_raw.lower()}"
            if search not in haystack:
                continue

        result.append(sample)

    return result


def _metric_value(sample: ProcessSample, sort_key: str, *, aggregated: bool = False) -> Optional[object]:
    if sort_key == "cpu":
        return sample.subtree_cpu_percent if aggregated else sample.cpu_percent
    if sort_key == "cpu_norm":
        return sample.cpu_percent_normalized
    if sort_key == "rss":
        return sample.subtree_rss_bytes if aggregated else sample.rss_bytes
    if sort_key == "io_read":
        return sample.subtree_io_read_rate if aggregated else sample.io_read_rate
    if sort_key == "io_write":
        return sample.subtree_io_write_rate if aggregated else sample.io_write_rate
    if sort_key == "io_total":
        if aggregated:
            r = sample.subtree_io_read_rate
            w = sample.subtree_io_write_rate
            if r is None and w is None:
                return None
            return (r or 0.0) + (w or 0.0)
        return sample.io_total_rate
    if sort_key == "gpu_mem":
        return sample.gpu_memory_bytes
    if sort_key == "name":
        return (sample.name or "").lower()
    if sort_key == "pid":
        return sample.pid
    if sort_key == "uptime":
        return sample.uptime_seconds
    if sort_key == "threads":
        return sample.num_threads
    if sort_key == "peak_cpu":
        return sample.peak_cpu_percent
    if sort_key == "peak_rss":
        return sample.peak_rss_bytes
    if sort_key == "subtree_cpu":
        return sample.subtree_cpu_percent
    if sort_key == "subtree_rss":
        return sample.subtree_rss_bytes
    return sample.cpu_percent


def sort_processes(
    samples: Sequence[ProcessSample],
    sort_key: str = "cpu",
    *,
    descending: bool = True,
    aggregated: bool = False,
) -> List[ProcessSample]:
    """Sort process samples by raw numeric/text value with missing values always last.

    Deterministic tie-breaking uses (pid, create_time).
    """
    items = list(samples)
    if sort_key == "random":
        random.shuffle(items)
        return items

    present: List[Tuple[object, int, float, ProcessSample]] = []
    missing: List[Tuple[int, float, ProcessSample]] = []

    for sample in items:
        val = _metric_value(sample, sort_key, aggregated=aggregated)
        if val is None:
            missing.append((sample.pid, sample.create_time, sample))
        else:
            present.append((val, sample.pid, sample.create_time, sample))

    if sort_key == "name":
        present.sort(key=lambda item: (str(item[0]), item[1], item[2]), reverse=descending)
    elif descending:
        # Sort value descending, tie-break pid/create_time ascending for stability
        present.sort(key=lambda item: (item[0], -item[1], -item[2]), reverse=True)
    else:
        present.sort(key=lambda item: (item[0], item[1], item[2]))

    missing.sort(key=lambda item: (item[0], item[1]))
    return [item[3] for item in present] + [item[2] for item in missing]


def group_processes(
    samples: Sequence[ProcessSample],
    mode: str,
    by_pid: Optional[Dict[int, ProcessSample]] = None,
) -> List[ProcessGroup]:
    """Group processes by name, executable path, parent process, or root ancestor."""
    if mode == "none":
        return []

    pid_lookup = by_pid or {s.pid: s for s in samples}

    def find_root(sample: ProcessSample) -> ProcessSample:
        seen = {sample.pid}
        cur = sample
        while cur.ppid and cur.ppid in pid_lookup and cur.ppid not in seen:
            seen.add(cur.ppid)
            cur = pid_lookup[cur.ppid]
        return cur

    buckets: Dict[str, Tuple[str, List[ProcessSample]]] = {}
    for sample in samples:
        if mode == "name":
            key = (sample.name or "unknown").lower()
            label = sample.name or "unknown"
        elif mode == "exe":
            key = (sample.exe or sample.name or "unknown").lower()
            label = sample.exe or sample.name or "unknown"
        elif mode == "parent":
            parent = pid_lookup.get(sample.ppid)
            key = f"ppid:{sample.ppid}"
            label = f"{parent.name} ({sample.ppid})" if parent else f"PID {sample.ppid}"
        elif mode == "root":
            root = find_root(sample)
            key = f"root:{root.identity.key}"
            label = f"{root.name} ({root.pid})"
        else:
            key = (sample.name or "unknown").lower()
            label = sample.name or "unknown"

        if key not in buckets:
            buckets[key] = (label, [])
        buckets[key][1].append(sample)

    groups: List[ProcessGroup] = []
    for key, (label, members) in buckets.items():
        cpu_vals = [m.cpu_percent for m in members if m.cpu_percent is not None]
        rss_vals = [m.rss_bytes for m in members if m.rss_bytes is not None]
        r_vals = [m.io_read_rate for m in members if m.io_read_rate is not None]
        w_vals = [m.io_write_rate for m in members if m.io_write_rate is not None]
        gpu_vals = [m.gpu_memory_bytes for m in members if m.gpu_memory_bytes is not None]
        groups.append(
            ProcessGroup(
                group_key=key,
                label=label,
                members=members,
                cpu_percent=sum(cpu_vals) if cpu_vals else None,
                rss_bytes=sum(rss_vals) if rss_vals else None,
                io_read_rate=sum(r_vals) if r_vals else None,
                io_write_rate=sum(w_vals) if w_vals else None,
                gpu_memory_bytes=sum(gpu_vals) if gpu_vals else None,
            )
        )

    groups.sort(key=lambda g: (g.cpu_percent is None, -(g.cpu_percent or 0.0), g.label.lower()))
    return groups
