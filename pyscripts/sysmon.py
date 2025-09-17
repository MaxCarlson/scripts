# File: pyscripts/sysmon.py
#!/usr/bin/env python3
"""
sysmon.py — unified CPU / Memory / Disk / Network / Overall / GPU TUI for tiny terminals.
(Updated: Termux-safe CPU, fixed NET per-proc deltas, expanded OVERALL graphs)
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import random
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import psutil
from rich import box
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# --------------------------- Key reader (non-blocking) ------------------------
if os.name == "nt":
    import msvcrt

    class KeyReader:
        def __enter__(self): return self
        def __exit__(self, et, ex, tb): return False
        def read(self) -> Optional[str]:
            if msvcrt.kbhit():
                return msvcrt.getwch()
            return None
else:
    import tty, termios

    class KeyReader:
        def __enter__(self):
            self.fd = sys.stdin.fileno()
            self.ok = sys.stdin.isatty()
            if self.ok:
                self.old = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
            return self
        def __exit__(self, et, ex, tb):
            if getattr(self, "ok", False):
                try: termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
                except Exception: pass
            return False
        def read(self) -> Optional[str]:
            if not getattr(self, "ok", False): return None
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                return sys.stdin.read(1)
            return None

# ------------------------------ Constants ------------------------------------
CPU_SORTS  = ["cpu", "memory", "disk", "name", "random"]
NET_SORTS  = ["mbps", "name"]
DISK_SORTS = ["read", "write", "total", "name"]
UNITS      = ["mb", "mib"]
VIEWS      = ["cpu", "net", "disk", "overall", "gpu"]
GRAPH_MODES = ["off", "total"]   # tiny-terminal friendly

# ------------------------------ Helpers --------------------------------------
def term_width() -> int:
    return shutil.get_terminal_size((100, 24)).columns

def clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)

def truncate(s: str, width: int) -> str:
    if width <= 1: return ""
    return s if len(s) <= width else (s[: max(0, width - 1)] + "…")

def human_mbps(bits_per_sec: float, base: str) -> float:
    denom = 1_000_000 if base == "mb" else (1 << 20)
    return bits_per_sec / denom

def sparkline(values: Sequence[float], width: int = 30) -> str:
    if width <= 0 or not values: return ""
    if len(values) > width:
        step = len(values) / width
        points = [values[int(i * step)] for i in range(width)]
    else:
        points = list(values)
    lo, hi = 0.0, max(points) or 1.0
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for v in points[-width:]:
        level = int(round((v - lo) / (hi - lo) * (len(blocks) - 1))) if hi > lo else 0
        out.append(blocks[level])
    return "".join(out)

# Safe wrappers (Termux/locked filesystems can deny /proc or /sys reads)
def safe_cpu_percent() -> float:
    try:
        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return 0.0

def safe_virtual_memory():
    try:
        return psutil.virtual_memory()
    except Exception:
        class Dummy:  # minimal shape
            total = used = available = 0
            percent = 0.0
        return Dummy()

# ---------------------- Process snapshotting for CPU/DISK --------------------
@dataclass
class ProcSnap:
    pid: int
    name: str
    rss: int
    read_bytes: int
    write_bytes: int
    cpu_user: float
    cpu_system: float
    ts: float

def iter_snaps(glob_pattern: str) -> Dict[int, ProcSnap]:
    snaps: Dict[int, ProcSnap] = {}
    now = time.time()
    gp = glob_pattern.lower()
    patt = gp if any(c in gp for c in "*?[]") else f"*{gp}*"
    for info in psutil.process_iter(attrs=["pid", "name", "memory_info", "io_counters", "cpu_times"]):
        try:
            name = (info.info.get("name") or "").lower()
            if not fnmatch.fnmatch(name, patt):
                continue
            mi = info.info.get("memory_info")
            io = info.info.get("io_counters")
            ct = info.info.get("cpu_times")
            snaps[info.info["pid"]] = ProcSnap(
                pid=info.info["pid"],
                name=info.info.get("name") or str(info.info["pid"]),
                rss=int(getattr(mi, "rss", 0) or 0),
                read_bytes=int(getattr(io, "read_bytes", 0) or 0),
                write_bytes=int(getattr(io, "write_bytes", 0) or 0),
                cpu_user=float(getattr(ct, "user", 0.0) or 0.0),
                cpu_system=float(getattr(ct, "system", 0.0) or 0.0),
                ts=now,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return snaps

def deltas(prev: Dict[int, ProcSnap], curr: Dict[int, ProcSnap], ncpu: int) -> List[dict]:
    rows: List[dict] = []
    for pid, c in curr.items():
        p = prev.get(pid)
        if not p:
            cpu_pct = 0.0
            rps = wps = 0.0
        else:
            elapsed = max(1e-6, c.ts - p.ts)
            cpu_time_delta = (c.cpu_user + c.cpu_system) - (p.cpu_user + p.cpu_system)
            cpu_pct = 100.0 * cpu_time_delta / elapsed / max(1, ncpu)
            rps = max(0.0, (c.read_bytes - p.read_bytes) / elapsed) / (1024 ** 2)
            wps = max(0.0, (c.write_bytes - p.write_bytes) / elapsed) / (1024 ** 2)
        rows.append(
            {
                "pid": pid,
                "name": c.name,
                "cpu_pct": cpu_pct,
                "mem_mb": c.rss / (1024 ** 2),
                "r_mb_s": rps,
                "w_mb_s": wps,
                "d_mb_s": rps + wps,
                "disk_mb": rps + wps,  # legacy key
            }
        )
    return rows

# ------------------------------ CPU view -------------------------------------
def cpu_columns_for_width(width: int, label_mode: str) -> List[str]:
    cols = ["PID"]
    if label_mode == "name":
        cols.append("Name")
    # metrics
    base = ["CPU %", "Mem(MB)", "DΔ(MB)", "RΔ(MB)", "WΔ(MB)"]
    if width < 65:  return cols + ["CPU %"]
    if width < 80:  return cols + ["CPU %", "Mem(MB)"]
    if width < 95:  return cols + ["CPU %", "Mem(MB)", "DΔ(MB)"]
    if width < 110: return cols + ["CPU %", "Mem(MB)", "RΔ(MB)", "WΔ(MB)"]
    return cols + base

def sort_cpu_rows(rows: List[dict], mode: str) -> None:
    if     mode == "cpu":    rows.sort(key=lambda r: r.get("cpu_pct", 0.0), reverse=True)
    elif   mode == "memory": rows.sort(key=lambda r: r.get("mem_mb", 0.0), reverse=True)
    elif   mode == "disk":   rows.sort(key=lambda r: r.get("d_mb_s", r.get("disk_mb", 0.0)), reverse=True)
    elif   mode == "name":   rows.sort(key=lambda r: r.get("name", "").lower())
    else:                    random.shuffle(rows)

@dataclass
class CpuState:
    hist_total: List[float]
    graph_mode: str = "total"       # graphs ON by default
    label_mode: str = "name"        # 'name' or 'pid'
    def __init__(self):
        self.hist_total = []
        self.graph_mode = "total"
        self.label_mode = "name"

def render_cpu_table(rows: List[dict], total: int, limit: int, sort_mode: str,
                     cpu_state: CpuState) -> Panel:
    width = term_width()
    cols = cpu_columns_for_width(width, cpu_state.label_mode)
    name_cap = max(8, min(24, width - 46))  # trim earlier to keep numbers visible

    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True)
    for col in cols:
        if col == "PID":
            table.add_column("PID", justify="right", no_wrap=True)
        elif col == "Name":
            table.add_column("Name", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
        else:
            table.add_column(col, justify="right", no_wrap=True)

    for r in rows[:limit]:
        vals = []
        if "PID" in cols:     vals.append(str(r["pid"]))
        if "Name" in cols:    vals.append(truncate(r["name"], name_cap))
        if "CPU %" in cols:   vals.append(f"{r['cpu_pct']:.1f}")
        if "Mem(MB)" in cols: vals.append(f"{r['mem_mb']:.1f}")
        if "DΔ(MB)" in cols:  vals.append(f"{r['d_mb_s']:.2f}")
        if "RΔ(MB)" in cols:  vals.append(f"{r['r_mb_s']:.2f}")
        if "WΔ(MB)" in cols:  vals.append(f"{r['w_mb_s']:.2f}")
        table.add_row(*vals)

    cap = f"Showing {min(limit, len(rows))} of {total} procs   |   sort: {sort_mode}"
    footer = Text("[v] view  [s] sort  [+/-] topN  ]/[ interval  g graphs  x label  [q] quit", style="dim")
    items: List = [table, Text(cap, style="dim"), footer]

    if cpu_state.graph_mode != "off":
        total_cpu = safe_cpu_percent()
        cpu_state.hist_total.append(total_cpu)
        if len(cpu_state.hist_total) > 120:
            cpu_state.hist_total = cpu_state.hist_total[-120:]
        s = sparkline(cpu_state.hist_total, width=max(20, min(80, width - 10)))
        items.insert(0, Text(f"CPU total: {total_cpu:.1f}%  {s}"))

    return Panel(Group(*items), title="CPU / Memory / Disk", border_style="cyan")

# -------------------------- Disk live (per-disk) ------------------------------
@dataclass
class DiskLiveState:
    prev: Dict[str, psutil._common.sdiskio]
    last_ts: float
    hist_total_mb_s: List[float]
    graph_mode: str = "total"   # graphs on by default
    per_disk_available: bool = True
    label_mode: str = "name"    # 'name'|'pid' for per-proc table
    win_drive_model_map: Dict[str, str] = None
    def __init__(self):
        self.prev = {}
        self.last_ts = time.time()
        self.hist_total_mb_s = []
        self.graph_mode = "total"
        self.per_disk_available = True
        self.label_mode = "name"
        self.win_drive_model_map = {}

def safe_disk_io_counters_perdisk() -> Dict[str, psutil._common.sdiskio]:
    try:
        return psutil.disk_io_counters(perdisk=True) or {}
    except Exception:
        return {}

def _win_populate_drive_models() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if os.name != "nt":
        return mapping
    try:
        out = subprocess.check_output(
            ["wmic", "diskdrive", "get", "index,model", "/format:csv"],
            text=True, stderr=subprocess.DEVNULL, timeout=1.0
        )
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 3 and parts[-1].isdigit():
                model = parts[-2]
                idx = parts[-1]
                mapping[f"PhysicalDrive{idx}"] = model
    except Exception:
        pass
    return mapping

def disk_perdisk_snapshot(state: DiskLiveState) -> Dict[str, Tuple[float, float, float, str]]:
    curr = safe_disk_io_counters_perdisk()
    if not curr:
        state.per_disk_available = False
        return {}
    state.per_disk_available = True

    now = time.time()
    dt = max(1e-6, now - state.last_ts)
    out: Dict[str, Tuple[float, float, float, str]] = {}
    total_bw = 0.0

    if os.name == "nt" and not state.win_drive_model_map:
        state.win_drive_model_map = _win_populate_drive_models()

    for dev, io in curr.items():
        prv = state.prev.get(dev)
        read_bps = write_bps = util = 0.0
        if prv:
            d_read = max(0, io.read_bytes - prv.read_bytes) / dt
            d_write = max(0, io.write_bytes - prv.write_bytes) / dt
            d_time = max(0, (io.read_time + io.write_time) - (prv.read_time + prv.read_time))
            # ^ bug in old build; correct util uses (prev.read_time + prev.write_time):
            d_time = max(0, (io.read_time + io.write_time) - (prv.read_time + prv.write_time))
            util = min(100.0, (d_time / (dt * 1000.0)) * 100.0)
            read_bps, write_bps = d_read, d_write
            total_bw += (d_read + d_write) / (1024 ** 2)

        disp = state.win_drive_model_map.get(dev, dev)
        out[dev] = (read_bps, write_bps, util, disp)

    state.hist_total_mb_s.append(total_bw)
    if len(state.hist_total_mb_s) > 120:
        state.hist_total_mb_s = state.hist_total_mb_s[-120:]
    state.prev = curr
    state.last_ts = now
    return out

def disk_usage_table() -> Optional[Table]:
    try:
        parts = psutil.disk_partitions()
    except Exception:
        return None
    table = Table(title="Disk Usage", box=box.SIMPLE_HEAVY)
    table.add_column("Mount/Drv", style="cyan")
    table.add_column("FS")
    table.add_column("Total(GB)", justify="right")
    table.add_column("Free(GB)", justify="right")
    table.add_column("Used(%)", justify="right")
    for part in parts:
        try:
            u = psutil.disk_usage(part.mountpoint)
        except Exception:
            continue
        table.add_row(
            part.mountpoint, part.fstype,
            f"{u.total/1e9:.2f}", f"{u.free/1e9:.2f}", f"{u.percent:.2f}",
        )
    return table

def per_disk_perf_table(inst: Dict[str, Tuple[float, float, float, str]]) -> Table:
    table = Table(title="Live Disk Performance", box=box.SIMPLE_HEAVY)
    table.add_column("Drive", style="magenta")
    table.add_column("Read MB/s", justify="right")
    table.add_column("Write MB/s", justify="right")
    table.add_column("Util(%)", justify="right")
    for dev, (rb, wb, util, disp) in inst.items():
        label = disp if disp else dev
        table.add_row(label, f"{rb/(1024**2):.2f}", f"{wb/(1024**2):.2f}", f"{util:.2f}")
    return table

def render_disk_view(proc_rows: List[dict], total_procs: int, top_n: int, sort_mode: str,
                     dstate: DiskLiveState) -> Panel:
    width = term_width()
    name_cap = max(6, min(20, width - 30))
    ptable = Table(box=box.SIMPLE_HEAVY, expand=True, title="DISK — per-process I/O")
    ptable.add_column("PID", justify="right", no_wrap=True)
    if dstate.label_mode == "name":
        ptable.add_column("Name", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    ptable.add_column("R MB/s", justify="right", no_wrap=True)
    ptable.add_column("W MB/s", justify="right", no_wrap=True)
    ptable.add_column("D MB/s", justify="right", no_wrap=True)

    for r in proc_rows[:top_n]:
        row = [str(r["pid"])]
        if dstate.label_mode == "name":
            row.append(truncate(r["name"], name_cap))
        row.extend([f"{r['r_mb_s']:.2f}", f"{r['w_mb_s']:.2f}", f"{r['d_mb_s']:.2f}"])
        ptable.add_row(*row)

    cap = f"Showing {min(top_n, len(proc_rows))} of {total_procs} procs   |   sort: {sort_mode}"

    inst = disk_perdisk_snapshot(dstate)
    items: List = []

    if dstate.graph_mode != "off":
        sl = sparkline(dstate.hist_total_mb_s, width=max(20, min(80, width - 10)))
        latest = dstate.hist_total_mb_s[-1] if dstate.hist_total_mb_s else 0.0
        items.append(Text(f"Disk total MB/s: {latest:.2f}  {sl}"))

    items.extend([ptable, Text(cap, style="dim")])

    if dstate.per_disk_available and inst:
        items.append(per_disk_perf_table(inst))
        du = disk_usage_table()
        if du and width >= 100:
            items.append(du)
    else:
        items.append(Text("Per-disk stats unavailable (permissions / platform)", style="dim"))

    items.append(Text("[v] view  [s] sort  [+/-] topN  ]/[ interval  g graphs  x label  [q] quit", style="dim"))
    return Panel(Group(*items), title="DISK", border_style="green")

# ------------------------------ NET view -------------------------------------
def _sysfs_sum_net_bytes() -> Optional[Tuple[int, int]]:
    base = "/sys/class/net"
    try:
        if not os.path.isdir(base): return None
        total_rx = total_tx = 0
        for iface in os.listdir(base):
            if iface == "lo": continue
            stats_dir = os.path.join(base, iface, "statistics")
            try:
                with open(os.path.join(stats_dir, "rx_bytes"), "r") as fr:
                    total_rx += int(fr.read().strip())
                with open(os.path.join(stats_dir, "tx_bytes"), "r") as ft:
                    total_tx += int(ft.read().strip())
            except (FileNotFoundError, PermissionError, ValueError):
                continue
        return (total_tx, total_rx)
    except Exception:
        return None

def get_total_counters() -> Tuple[int, int]:
    try:
        c = psutil.net_io_counters(pernic=False)
        return c.bytes_sent, c.bytes_recv
    except Exception:
        return _sysfs_sum_net_bytes() or (0, 0)

def sum_active_link_capacity_mbps() -> float:
    total = 0.0
    try:
        for _, st in psutil.net_if_stats().items():
            if st.isup and st.speed and st.speed > 0:
                total += float(st.speed)
    except Exception:
        return 0.0
    return total

@dataclass
class NetState:
    units: str = "mb"
    prev_total: Tuple[int, int] = (0, 0)
    prev_time: float = 0.0
    link_cap_mbps: float = 0.0
    hist_total_mbps: List[float] = None  # type: ignore
    per_proc_on: bool = True
    graph_mode: str = "total"
    label_mode: str = "name"
    def __post_init__(self):
        if self.hist_total_mbps is None: self.hist_total_mbps = []

def render_net_panel(state: NetState, top_n: int, interval_hint: float,
                     proc_rows: List[dict]) -> Panel:
    now = time.time()
    elapsed = now - state.prev_time if state.prev_time else interval_hint
    if elapsed <= 0: elapsed = interval_hint

    curr_total = get_total_counters()
    sent_bps = (curr_total[0] - state.prev_total[0]) * 8.0 / elapsed
    recv_bps = (curr_total[1] - state.prev_total[1]) * 8.0 / elapsed
    total_bps = max(0.0, sent_bps + recv_bps)

    sent_mbps = human_mbps(sent_bps, state.units)
    recv_mbps = human_mbps(recv_bps, state.units)
    total_mbps = human_mbps(total_bps, state.units)
    util = (total_mbps / state.link_cap_mbps * 100.0) if state.link_cap_mbps > 0 else 0.0

    state.hist_total_mbps.append(total_mbps)
    if len(state.hist_total_mbps) > 120:
        state.hist_total_mbps = state.hist_total_mbps[-120:]

    width = term_width()
    name_cap = max(8, min(24, width - 26))
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("PID", justify="right", no_wrap=True)
    if state.label_mode == "name":
        table.add_column("Process", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    table.add_column("Σ ({}b/s)".format("Mi" if state.units == "mib" else "M"), justify="right", no_wrap=True)

    if state.per_proc_on and proc_rows:
        for r in proc_rows[:top_n]:
            row = [str(r["pid"])]
            if state.label_mode == "name":
                row.append(truncate(r["name"], name_cap))
            row.append(f"{r['d_mb_s']:8.2f}")
            table.add_row(*row)
    else:
        table.add_row("-", "(per-proc off)" if state.label_mode=="name" else "-", "-")

    hdr = Text.assemble(
        ("Network Usage  ", "cyan bold"),
        (f"(interval≈{elapsed:.2f}s, units={'MiB/s' if state.units=='mib' else 'Mb/s'})", "dim"),
    )
    totals = f"Total:  ↓ {recv_mbps:7.2f}  ↑ {sent_mbps:7.2f}  Σ {total_mbps:7.2f}    Util: {util:5.1f}%"
    cap = (f"{int(state.link_cap_mbps):d} Mb/s link cap (sum of up NICs)"
           if state.link_cap_mbps > 0 else "unknown link cap (permissions / mobile)")

    items: List = [hdr]
    if state.graph_mode != "off":
        items.append(Text(sparkline(state.hist_total_mbps, width=max(20, min(80, width - 24)))))
    items.extend([Text(totals), Text(cap, style="dim"), table,
                  Text("[v] view  [s] sort  [+/-] topN  ]/[ interval  m units  p per-proc  g graphs  x label  [q] quit", style="dim")])

    state.prev_total = curr_total
    state.prev_time = now
    return Panel(Group(*items), title="NET — totals", border_style="magenta")

# ------------------------------ OVERALL view ---------------------------------
@dataclass
class OverallState:
    cpu_hist: List[float]
    mem_free_hist: List[float]
    net_hist: List[float]
    disk_hist: List[float]
    graph_mode: str = "total"
    def __init__(self):
        self.cpu_hist = []
        self.mem_free_hist = []
        self.net_hist = []
        self.disk_hist = []
        self.graph_mode = "total"

def render_overall(ost: OverallState, nst: NetState, dst: DiskLiveState) -> Panel:
    width = term_width()
    cpu = safe_cpu_percent()
    mem = safe_virtual_memory()
    mem_free = (getattr(mem, "available", 0) or 0) / (1024**3)

    ost.cpu_hist.append(cpu);            ost.cpu_hist = ost.cpu_hist[-120:]
    if nst.hist_total_mbps: ost.net_hist.append(nst.hist_total_mbps[-1]); ost.net_hist = ost.net_hist[-120:]
    if dst.hist_total_mb_s: ost.disk_hist.append(dst.hist_total_mb_s[-1]); ost.disk_hist = ost.disk_hist[-120:]
    ost.mem_free_hist.append(mem_free);  ost.mem_free_hist = ost.mem_free_hist[-120:]

    t = Table(box=box.SIMPLE_HEAVY, expand=True, title="Overall")
    t.add_column("Metric"); t.add_column("Value", justify="right")
    total_gb = (getattr(mem, "total", 0) or 0)/(1024**3)
    used_gb  = (getattr(mem, "used", 0) or 0)/(1024**3)
    percent  = getattr(mem, "percent", 0.0)
    t.add_row("CPU", f"{cpu:.1f}%")
    t.add_row("Mem Used", f"{used_gb:.2f} / {total_gb:.2f} GB ({percent:.1f}%)")
    if nst.hist_total_mbps: t.add_row("Net Σ",  f"{nst.hist_total_mbps[-1]:.2f} {'MiB/s' if nst.units=='mib' else 'Mb/s'}")
    if dst.hist_total_mb_s: t.add_row("Disk Σ", f"{dst.hist_total_mb_s[-1]:.2f} MB/s")

    graph_width = max(30, min(90, width - 10))
    items: List = [t]
    if ost.graph_mode != "off":
        items.extend([
            Text(f"CPU   {sparkline(ost.cpu_hist,       width=graph_width)}"),
            Text(f"MEM↑  {sparkline(ost.mem_free_hist,  width=graph_width)} (free GB)"),
            Text(f"NET   {sparkline(ost.net_hist,       width=graph_width)}"),
            Text(f"DISK  {sparkline(ost.disk_hist,      width=graph_width)}"),
        ])
    items.append(Text("[v] view  g graphs  [q] quit", style="dim"))
    return Panel(Group(*items), title="OVERALL", border_style="white")

# ------------------------------ GPU view -------------------------------------
@dataclass
class GpuState:
    hist_util: List[float]
    graph_mode: str = "total"
    def __init__(self):
        self.hist_util = []
        self.graph_mode = "total"

def gpu_info() -> Tuple[List[dict], Optional[str]]:
    try:
        import GPUtil  # type: ignore
        gpus = GPUtil.getGPUs()
        rows = []
        for g in gpus:
            rows.append({
                "name": g.name, "id": g.id, "load": g.load * 100.0,
                "mem_used": g.memoryUsed, "mem_total": g.memoryTotal, "temp": g.temperature,
            })
        return rows, None
    except Exception:
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,index,utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL, text=True, timeout=1.0
            )
            rows = []
            for line in out.strip().splitlines():
                name, idx, util, mu, mt, temp = [s.strip() for s in line.split(",")]
                rows.append({"name": name, "id": int(idx), "load": float(util),
                             "mem_used": float(mu), "mem_total": float(mt), "temp": float(temp)})
            return rows, None
        except Exception:
            return [], "GPU info unavailable (install GPUtil or nvidia-smi)"

def render_gpu(gst: GpuState) -> Panel:
    width = term_width()
    rows, err = gpu_info()
    table = Table(title="GPU", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("ID", justify="right"); table.add_column("Name")
    table.add_column("Util %", justify="right"); table.add_column("Mem(used/total MB)", justify="right")
    table.add_column("Temp °C", justify="right")
    if rows:
        for r in rows:
            table.add_row(str(r["id"]), truncate(r["name"], max(8, min(32, width-36))),
                          f"{r['load']:.1f}", f"{r['mem_used']:.0f}/{r['mem_total']:.0f}", f"{r['temp']:.0f}")
        gst.hist_util.append(rows[0]["load"]); gst.hist_util = gst.hist_util[-120:]
    else:
        table.add_row("-", err or "No GPU detected", "-", "-", "-")

    items: List = [table]
    if gst.graph_mode != "off" and gst.hist_util:
        items.insert(0, Text(f"GPU util: {gst.hist_util[-1]:.1f}%  {sparkline(gst.hist_util, width=max(20, min(80, width-10)))}"))
    items.append(Text("[v] view  g graphs  [q] quit", style="dim"))
    return Panel(Group(*items), title="GPU", border_style="blue")

# ------------------------------- CLI / Main ----------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unified CPU/NET/DISK/OVERALL/GPU monitor (lightweight)")
    p.add_argument("-t", "--top", type=int, default=15, help="Top N rows (1-99)")
    p.add_argument("-i", "--interval", type=float, default=1.0, help="Refresh interval seconds (0.2–5)")
    p.add_argument("-g", "--glob", type=str, default="*", help="Process name glob filter for CPU/DISK views")
    p.add_argument("-w", "--view", choices=VIEWS, default="cpu", help="Initial view")
    p.add_argument("-S", "--sort", choices=CPU_SORTS + NET_SORTS + DISK_SORTS, default="cpu", help="Initial sort mode")
    p.add_argument("-u", "--units", choices=UNITS, default="mb", help="Network units (mb or mib)")
    p.add_argument("--low-prio", action="store_true", help="Lower this process priority (nice / BELOW_NORMAL)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logs to stderr")
    return p.parse_args(argv)

def set_low_priority() -> None:
    try:
        if os.name == "nt":
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(5)
    except Exception:
        pass

def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if args.low_prio:
        set_low_priority()

    top_n = int(clamp(args.top, 1, 99))
    interval = float(clamp(args.interval, 0.2, 5.0))

    cpu_sort  = args.sort if args.sort in CPU_SORTS  else "cpu"
    net_sort  = args.sort if args.sort in NET_SORTS  else "mbps"
    disk_sort = args.sort if args.sort in DISK_SORTS else "total"
    view_idx  = VIEWS.index(args.view)

    ncpu = psutil.cpu_count(logical=True) or 1

    # States
    cpu_state  = CpuState()
    net_state  = NetState(units=args.units); net_state.prev_total = get_total_counters(); net_state.prev_time = time.time(); net_state.link_cap_mbps = sum_active_link_capacity_mbps(); net_state.per_proc_on = True
    disk_state = DiskLiveState(); disk_state.prev = safe_disk_io_counters_perdisk()
    over_state = OverallState()
    gpu_state  = GpuState()

    prev_snaps: Dict[int, ProcSnap] = {}      # CPU/DISK per-proc
    prev_net_snaps: Dict[int, ProcSnap] = {}  # NET per-proc (persist while NET tab visible)

    help_on = False

    with KeyReader() as keys, Live(refresh_per_second=8, redirect_stdout=False) as live:
        while True:
            ch = keys.read()
            if ch:
                low = ch.lower()
                if low == "q": break
                elif low == "v": view_idx = (view_idx + 1) % len(VIEWS)
                elif low == "s":
                    v = VIEWS[view_idx]
                    if v == "cpu":
                        cpu_sort = CPU_SORTS[(CPU_SORTS.index(cpu_sort) + 1) % len(CPU_SORTS)]
                    elif v == "net":
                        net_sort = NET_SORTS[(NET_SORTS.index(net_sort) + 1) % len(NET_SORTS)]
                    elif v == "disk":
                        disk_sort = DISK_SORTS[(DISK_SORTS.index(disk_sort) + 1) % len(DISK_SORTS)]
                elif ch == "+": top_n = int(clamp(top_n + 1, 1, 99))
                elif ch == "-": top_n = int(clamp(top_n - 1, 1, 99))
                elif ch == "]": interval = float(clamp(interval + 0.1, 0.2, 5.0))
                elif ch == "[": interval = float(clamp(interval - 0.1, 0.2, 5.0))
                elif low == "m": net_state.units = "mib" if net_state.units == "mb" else "mb"
                elif low == "p": net_state.per_proc_on = not net_state.per_proc_on
                elif low == "g":
                    v = VIEWS[view_idx]
                    if v == "cpu":
                        cpu_state.graph_mode = GRAPH_MODES[(GRAPH_MODES.index(cpu_state.graph_mode) + 1) % len(GRAPH_MODES)]
                    elif v == "net":
                        net_state.graph_mode = GRAPH_MODES[(GRAPH_MODES.index(net_state.graph_mode) + 1) % len(GRAPH_MODES)]
                    elif v == "disk":
                        disk_state.graph_mode = GRAPH_MODES[(GRAPH_MODES.index(disk_state.graph_mode) + 1) % len(GRAPH_MODES)]
                    elif v == "overall":
                        over_state.graph_mode = GRAPH_MODES[(GRAPH_MODES.index(over_state.graph_mode) + 1) % len(GRAPH_MODES)]
                    elif v == "gpu":
                        gpu_state.graph_mode = GRAPH_MODES[(GRAPH_MODES.index(gpu_state.graph_mode) + 1) % len(GRAPH_MODES)]
                elif low == "x":
                    v = VIEWS[view_idx]
                    if v == "cpu":    cpu_state.label_mode  = "pid" if cpu_state.label_mode  == "name" else "name"
                    elif v == "net":  net_state.label_mode  = "pid" if net_state.label_mode  == "name" else "name"
                    elif v == "disk": disk_state.label_mode = "pid" if disk_state.label_mode == "name" else "name"
                elif low == "h":
                    help_on = not help_on

            # ------------ Update only the active view ------------
            current_view = VIEWS[view_idx]

            if current_view in ("cpu", "disk"):
                curr_snaps = iter_snaps(args.glob)
                rows = deltas(prev_snaps, curr_snaps, ncpu)
                total_procs = len(curr_snaps)
                prev_snaps = curr_snaps

                if current_view == "cpu":
                    rows_cpu = list(rows)
                    sort_cpu_rows(rows_cpu, cpu_sort)
                    panel = render_cpu_table(rows_cpu, total=total_procs, limit=top_n, sort_mode=cpu_sort, cpu_state=cpu_state)
                else:
                    rows_disk = list(rows)
                    if   disk_sort == "read":  rows_disk.sort(key=lambda r: r["r_mb_s"], reverse=True)
                    elif disk_sort == "write": rows_disk.sort(key=lambda r: r["w_mb_s"], reverse=True)
                    elif disk_sort == "total": rows_disk.sort(key=lambda r: r["d_mb_s"], reverse=True)
                    else:                      rows_disk.sort(key=lambda r: r["name"].lower())
                    panel = render_disk_view(rows_disk, total_procs, top_n, disk_sort, disk_state)

            elif current_view == "net":
                proc_rows = []
                if net_state.per_proc_on:
                    curr_snaps = iter_snaps("*")
                    proc_rows = deltas(prev_net_snaps, curr_snaps, ncpu)
                    prev_net_snaps = curr_snaps
                    if net_sort == "name":
                        proc_rows.sort(key=lambda r: r["name"].lower())
                    else:
                        proc_rows.sort(key=lambda r: r["d_mb_s"], reverse=True)
                panel = render_net_panel(net_state, top_n=top_n, interval_hint=interval, proc_rows=proc_rows)

            elif current_view == "overall":
                _ = disk_perdisk_snapshot(disk_state)
                # keep NET history moving cheaply
                now = time.time()
                if net_state.prev_time == 0.0:
                    net_state.prev_time = now; net_state.prev_total = get_total_counters()
                else:
                    curr_total = get_total_counters()
                    elapsed = max(1e-6, now - net_state.prev_time)
                    total_bps = max(0.0, ((curr_total[0]-net_state.prev_total[0]) + (curr_total[1]-net_state.prev_total[1])) * 8.0 / elapsed)
                    net_state.hist_total_mbps.append(human_mbps(total_bps, net_state.units))
                    net_state.hist_total_mbps = net_state.hist_total_mbps[-120:]
                    net_state.prev_total, net_state.prev_time = curr_total, now
                panel = render_overall(over_state, net_state, disk_state)

            else:  # GPU
                panel = render_gpu(gpu_state)

            if help_on:
                help_text = Text(
                    "q quit • v view • s sort • +/- top rows • ]/[ interval • m units(NET) • p per-proc(NET)\n"
                    "g graphs • x label (Name↔PID)\n"
                    "Views: cpu, net, disk, overall, gpu | CPU sort: cpu,memory,disk,name,random | "
                    "NET sort: mbps,name | DISK sort: read,write,total,name",
                    style="yellow",
                )
                live.update(Panel(Group(panel, Panel(help_text, title="Help", border_style="yellow"))))
            else:
                live.update(panel)

            time.sleep(interval)

if __name__ == "__main__":
    main()
