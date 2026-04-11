"""Process discovery, control, and metrics helpers for system_manager."""

from __future__ import annotations

import difflib
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import psutil

from cross_platform import SystemUtils, run_powershell_text


sysu = SystemUtils()


@dataclass(frozen=True)
class ProcessQuery:
    """Criteria for process search."""

    pid: Optional[int] = None
    query: Optional[str] = None
    name: Optional[str] = None
    cmdline: bool = False
    exe: bool = False
    path: Optional[str] = None
    regex: bool = False
    fuzzy: bool = False


def _safe_join_cmdline(cmdline: Optional[List[str]]) -> str:
    return " ".join(cmdline or [])


def _safe_process_record(proc: psutil.Process, *, depth: Optional[int] = None) -> Dict[str, Any]:
    try:
        info = proc.as_dict(attrs=["pid", "ppid", "name", "exe", "cmdline", "username", "status", "create_time", "cwd"])
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {}

    created = ""
    if info.get("create_time"):
        created = datetime.fromtimestamp(info["create_time"]).strftime("%Y-%m-%d %H:%M:%S")

    record = {
        "pid": info.get("pid"),
        "ppid": info.get("ppid"),
        "name": info.get("name") or "",
        "status": info.get("status") or "",
        "username": info.get("username") or "",
        "created": created,
        "path": info.get("exe") or "",
        "cwd": info.get("cwd") or "",
        "cmdline": _safe_join_cmdline(info.get("cmdline")),
    }
    if depth is not None:
        record["depth"] = depth
        record["display"] = "  " * depth + f"|- {record['name']} ({record['pid']})"
    return record


def _haystack(record: Dict[str, Any], query: ProcessQuery) -> str:
    parts = [record.get("name", "")]
    if query.cmdline:
        parts.append(record.get("cmdline", ""))
    if query.exe:
        parts.append(record.get("path", ""))
    if query.path:
        parts.append(record.get("path", ""))
        parts.append(record.get("cwd", ""))
    return " ".join(str(part) for part in parts if part)


def _matches_text(text: str, needle: str, *, regex: bool = False, fuzzy: bool = False) -> bool:
    if regex:
        return re.search(needle, text, flags=re.IGNORECASE) is not None
    text_l = text.lower()
    needle_l = needle.lower()
    if needle_l in text_l:
        return True
    if fuzzy:
        return difflib.SequenceMatcher(None, needle_l, text_l).ratio() >= 0.58
    return False


def find_processes(query: ProcessQuery) -> List[Dict[str, Any]]:
    """Find processes using PID, name, command line, exe path, or fuzzy criteria."""
    if query.pid is not None:
        try:
            record = _safe_process_record(psutil.Process(query.pid))
            return [record] if record else []
        except psutil.NoSuchProcess:
            return []

    records: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "username", "status", "create_time", "cwd"]):
        record = _safe_process_record(proc)
        if not record:
            continue
        if query.name and not _matches_text(record["name"], query.name, regex=query.regex, fuzzy=query.fuzzy):
            continue
        if query.path:
            path_text = f"{record.get('path', '')} {record.get('cwd', '')}"
            if query.path.lower() not in path_text.lower():
                continue
        if query.query and not _matches_text(
            _haystack(record, query),
            query.query,
            regex=query.regex,
            fuzzy=query.fuzzy,
        ):
            continue
        records.append(record)
    return sorted(records, key=lambda row: (str(row.get("name", "")).lower(), int(row.get("pid") or 0)))


def process_tree(pid: int, *, include_root: bool = True) -> List[Dict[str, Any]]:
    """Return a process subtree rooted at pid."""
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []

    rows: List[Dict[str, Any]] = []

    def walk(proc: psutil.Process, depth: int) -> None:
        record = _safe_process_record(proc, depth=depth)
        if record:
            rows.append(record)
        for child in proc.children(recursive=False):
            walk(child, depth + 1)

    if include_root:
        walk(root, 0)
    else:
        for child_proc in root.children(recursive=False):
            walk(child_proc, 0)
    return rows


def process_parents(pid: int) -> List[Dict[str, Any]]:
    """Return parent chain from nearest parent outward."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    rows = []
    current = proc.parent()
    depth = 0
    while current is not None:
        record = _safe_process_record(current, depth=depth)
        if record:
            rows.append(record)
        current = current.parent()
        depth += 1
    return rows


def _resolve_targets(
    *,
    pid: Optional[int],
    query: Optional[str],
    name: Optional[str],
    cmdline: bool,
    exe: bool,
    path: Optional[str],
    regex: bool,
    fuzzy: bool,
    recursive: bool = False,
) -> List[psutil.Process]:
    records = find_processes(
        ProcessQuery(
            pid=pid,
            query=query,
            name=name,
            cmdline=cmdline,
            exe=exe,
            path=path,
            regex=regex,
            fuzzy=fuzzy,
        )
    )
    targets: Dict[int, psutil.Process] = {}
    for record in records:
        try:
            proc = psutil.Process(int(record["pid"]))
            targets[proc.pid] = proc
            if recursive:
                for child in proc.children(recursive=True):
                    targets[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return list(targets.values())


def _ordered_for_action(processes: Iterable[psutil.Process], *, parent_last: bool) -> List[psutil.Process]:
    proc_list = list(processes)
    if not parent_last:
        return sorted(proc_list, key=lambda p: p.pid)
    depths: Dict[int, int] = {}
    proc_ids = {p.pid for p in proc_list}
    for proc in proc_list:
        depth = 0
        parent = proc.parent()
        while parent is not None and parent.pid in proc_ids:
            depth += 1
            parent = parent.parent()
        depths[proc.pid] = depth
    return sorted(proc_list, key=lambda p: depths.get(p.pid, 0), reverse=True)


def act_on_processes(
    action: str,
    *,
    pid: Optional[int] = None,
    query: Optional[str] = None,
    name: Optional[str] = None,
    cmdline: bool = False,
    exe: bool = False,
    path: Optional[str] = None,
    regex: bool = False,
    fuzzy: bool = False,
    recursive: bool = False,
    force: bool = False,
    dry_run: bool = True,
    confirm: bool = False,
) -> List[Dict[str, Any]]:
    """Preview or apply a process action."""
    if pid is None and not query and not name and not path:
        return [
            {
                "status": "error",
                "error": "refusing to target processes without -p/--pid, -q/--query, -N/--name, or -P/--path",
            }
        ]
    targets = _resolve_targets(
        pid=pid,
        query=query,
        name=name,
        cmdline=cmdline,
        exe=exe,
        path=path,
        regex=regex,
        fuzzy=fuzzy,
        recursive=recursive,
    )
    if not targets:
        return [{"status": "no-match"}]

    destructive = action in {"stop", "kill", "restart"}
    should_apply = not dry_run and (confirm or not destructive)
    ordered = _ordered_for_action(targets, parent_last=action in {"stop", "kill"} or recursive)
    results: List[Dict[str, Any]] = []

    for proc in ordered:
        record = _safe_process_record(proc)
        if not record:
            continue
        result = {"pid": record["pid"], "name": record["name"], "action": action, "status": "preview"}
        if destructive and not confirm:
            result["reason"] = "requires -y/--confirm"
        elif should_apply:
            try:
                if action == "pause":
                    proc.suspend()
                    result["status"] = "paused"
                elif action == "resume":
                    proc.resume()
                    result["status"] = "resumed"
                elif action == "stop":
                    proc.kill() if force else proc.terminate()
                    result["status"] = "killed" if force else "terminated"
                elif action == "kill":
                    proc.kill()
                    result["status"] = "killed"
                elif action == "restart":
                    result.update(_restart_process(proc, dry_run=False))
                else:
                    result["status"] = "unknown-action"
            except Exception as exc:
                result["status"] = "error"
                result["error"] = str(exc)
        elif action == "restart":
            try:
                result.update(_restart_process(proc, dry_run=True))
            except Exception as exc:
                result["status"] = "error"
                result["error"] = str(exc)
        results.append(result)
    return results


def _restart_process(proc: psutil.Process, *, dry_run: bool) -> Dict[str, Any]:
    cmdline = proc.cmdline()
    if not cmdline:
        return {"status": "error", "error": "cannot restart without command line"}
    cwd = proc.cwd() if proc.cwd() else None
    if dry_run:
        return {"status": "preview", "cmdline": " ".join(cmdline), "cwd": cwd or ""}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    subprocess.Popen(cmdline, cwd=cwd)
    return {"status": "restarted", "cmdline": " ".join(cmdline), "cwd": cwd or ""}


def sample_process_stats(
    pid: int,
    *,
    interval: float = 1.0,
    samples: int = 1,
    include_tree: bool = False,
) -> Dict[str, Any]:
    """Sample process resource usage and return aggregate metrics."""
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return {"error": "process not found", "pid": pid}

    samples = max(1, samples)
    interval = max(0.1, interval)
    per_sample: List[Dict[str, Any]] = []
    first_io: Dict[int, Any] = {}
    first_cpu: Dict[int, Any] = {}
    last_io: Dict[int, Any] = {}
    last_cpu: Dict[int, Any] = {}
    observed_paths = set()
    started = time.monotonic()

    for index in range(samples):
        procs = [root]
        if include_tree:
            procs.extend(root.children(recursive=True))
        live = []
        for proc in procs:
            try:
                proc.cpu_percent(interval=None)
                live.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if index > 0 or samples == 1:
            time.sleep(interval)

        proc_rows = []
        for proc in live:
            try:
                cpu_percent = proc.cpu_percent(interval=None)
                mem = proc.memory_info()
                cpu_times = proc.cpu_times()
                io = proc.io_counters() if hasattr(proc, "io_counters") else None
                if proc.pid not in first_cpu:
                    first_cpu[proc.pid] = cpu_times
                if io and proc.pid not in first_io:
                    first_io[proc.pid] = io
                last_cpu[proc.pid] = cpu_times
                if io:
                    last_io[proc.pid] = io
                for opened in proc.open_files():
                    observed_paths.add(str(Path(opened.path).anchor or Path(opened.path).parent))
                proc_rows.append(
                    {
                        "pid": proc.pid,
                        "name": proc.name(),
                        "cpu_percent": cpu_percent,
                        "rss": mem.rss,
                        "vms": mem.vms,
                        "threads": proc.num_threads(),
                        "read_bytes": getattr(io, "read_bytes", 0) if io else 0,
                        "write_bytes": getattr(io, "write_bytes", 0) if io else 0,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        per_sample.append(
            {
                "sample": index + 1,
                "system_cpu_per_core": psutil.cpu_percent(interval=None, percpu=True),
                "processes": proc_rows,
            }
        )

    elapsed = max(time.monotonic() - started, 0.001)
    cpu_time_delta = 0.0
    read_delta = 0
    write_delta = 0
    for proc_pid, end_times in last_cpu.items():
        start_times = first_cpu.get(proc_pid)
        if start_times:
            cpu_time_delta += (end_times.user + end_times.system) - (start_times.user + start_times.system)
    for proc_pid, end_io in last_io.items():
        start_io = first_io.get(proc_pid)
        if start_io:
            read_delta += max(0, end_io.read_bytes - start_io.read_bytes)
            write_delta += max(0, end_io.write_bytes - start_io.write_bytes)

    return {
        "pid": pid,
        "include_tree": include_tree,
        "samples": samples,
        "interval_seconds": interval,
        "elapsed_seconds": round(elapsed, 3),
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "cpu_time_delta_seconds": round(cpu_time_delta, 6),
        "estimated_core_seconds": round(cpu_time_delta, 6),
        "read_bytes_delta": read_delta,
        "write_bytes_delta": write_delta,
        "read_bytes_per_second": round(read_delta / elapsed, 2),
        "write_bytes_per_second": round(write_delta / elapsed, 2),
        "observed_file_roots": sorted(observed_paths),
        "note": "Per-drive and exact per-core per-process attribution may require ETW/performance counters on Windows.",
        "sample_data": per_sample,
    }


def windows_cim_process_search(pattern: str) -> List[Dict[str, Any]]:
    """Search Win32_Process command lines with CIM through PowerShell."""
    if not sysu.is_windows():
        return []
    safe = pattern.replace("'", "''")
    script = f"""
    Get-CimInstance Win32_Process |
        Where-Object {{ $_.CommandLine -like '*{safe}*' }} |
        Select-Object ProcessId, ParentProcessId, Name, CommandLine |
        ConvertTo-Json
    """
    out = run_powershell_text(script, timeout=20)
    if not out:
        return []
    import json

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        {
            "pid": item.get("ProcessId"),
            "ppid": item.get("ParentProcessId"),
            "name": item.get("Name"),
            "cmdline": item.get("CommandLine"),
        }
        for item in data
    ]
