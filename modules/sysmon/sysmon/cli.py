#!/usr/bin/env python3
"""
sysmon — Beautiful unified system monitor: CPU / Memory / Disk / Network / GPU TUI
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
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import psutil
from rich import box
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ─────────────────────────── Key reader (non-blocking) ───────────────────────
if os.name == "nt":
    import msvcrt

    class KeyReader:
        def __enter__(self): return self
        def __exit__(self, et, ex, tb): return False
        def read(self) -> Optional[str]:
            if not msvcrt.kbhit():
                return None
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):
                if msvcrt.kbhit():
                    ch2 = msvcrt.getwch()
                    if ch2 == 'K': return 'LEFT'
                    if ch2 == 'M': return 'RIGHT'
                    if ch2 == 'H': return 'UP'
                    if ch2 == 'P': return 'DOWN'
                return None
            return ch
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
            if not r: return None
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                r2, _, _ = select.select([sys.stdin], [], [], 0.05)
                if r2 and sys.stdin.read(1) == '[':
                    r3, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if r3:
                        ch3 = sys.stdin.read(1)
                        if ch3 == 'A': return 'UP'
                        if ch3 == 'B': return 'DOWN'
                        if ch3 == 'C': return 'RIGHT'
                        if ch3 == 'D': return 'LEFT'
                return None
            return ch

# ─────────────────────────── Constants ───────────────────────────────────────
CPU_SORTS   = ["cpu", "memory", "disk", "name", "random"]
NET_SORTS   = ["mbps", "name"]
DISK_SORTS  = ["read", "write", "total", "name"]
UNITS       = ["mb", "mib"]
VIEWS       = ["overall", "cpu", "net", "disk", "gpu"]
GRAPH_MODES = ["off", "total"]

# ─────────────────────────── Color / Style Helpers ───────────────────────────
_GRAD = [
    (50.0,  "bright_green"),
    (75.0,  "green"),
    (88.0,  "yellow"),
    (100.0, "bold red"),
]

def _pct_style(pct: float) -> str:
    for threshold, style in _GRAD:
        if pct <= threshold:
            return style
    return "bold red"

def _make_bar(pct: float, width: int = 24) -> Text:
    """Colored progress bar: ████████░░░░ 67.3%"""
    filled = max(0, min(width, int(round(pct / 100.0 * width))))
    empty  = width - filled
    style  = _pct_style(pct)
    t = Text()
    t.append("█" * filled, style=style)
    t.append("░" * empty,  style="grey30")
    t.append(f" {pct:5.1f}%", style=style)
    return t

def _spark(values: Sequence[float], width: int = 40) -> str:
    if not values or width <= 0:
        return ""
    pts = list(values)
    if len(pts) > width:
        step = len(pts) / width
        pts = [pts[int(i * step)] for i in range(width)]
    lo, hi = 0.0, max(pts) or 1.0
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(
        blocks[int(round((v - lo) / (hi - lo) * (len(blocks) - 1))) if hi > lo else 0]
        for v in pts[-width:]
    )

def _spark_text(values: Sequence[float], width: int = 40, label: str = "", color: str = "cyan") -> Text:
    t = Text()
    if label:
        t.append(f"{label}  ", style="dim")
    t.append(_spark(values, width), style=color)
    return t

def _nav_bar(current: str) -> Text:
    t = Text()
    icons = {"overall": "◈", "cpu": "⚙", "net": "⬡", "disk": "◫", "gpu": "▣"}
    for v in VIEWS:
        icon = icons.get(v, "•")
        if v == current:
            t.append(f"  {icon} {v.upper()}  ", style="bold white on #005f87")
        else:
            t.append(f"  {icon} {v}  ", style="dim")
    return t

def _footer(*hints: str) -> Text:
    t = Text()
    for i, h in enumerate(hints):
        if i:
            t.append("  │  ", style="grey42")
        t.append(h, style="grey62")
    return t

# ─────────────────────────── Terminal geometry ───────────────────────────────
def term_width()  -> int: return shutil.get_terminal_size((120, 30)).columns
def term_height() -> int: return shutil.get_terminal_size((120, 30)).lines

def _visual_lines(text: str, inner_width: int) -> int:
    if inner_width <= 0: return 1
    total = 0
    for para in text.split('\n'):
        total += max(1, -(-len(para) // inner_width))
    return total

def clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)

def truncate(s: str, width: int) -> str:
    if width <= 1: return ""
    return s if len(s) <= width else s[: max(0, width - 1)] + "…"

def human_mbps(bits_per_sec: float, base: str) -> float:
    denom = 1_000_000 if base == "mb" else (1 << 20)
    return bits_per_sec / denom

# ─────────────────────────── Safe psutil wrappers ────────────────────────────
def safe_cpu_percent() -> float:
    try:    return float(psutil.cpu_percent(interval=None))
    except: return 0.0

def safe_virtual_memory():
    try: return psutil.virtual_memory()
    except:
        class _Dummy:
            total = used = available = 0
            percent = 0.0
        return _Dummy()

# ─────────────────────────── Process snapshotting ────────────────────────────
@dataclass
class ProcSnap:
    pid: int; name: str; rss: int
    read_bytes: int; write_bytes: int
    cpu_user: float; cpu_system: float; ts: float

def iter_snaps(glob_pattern: str) -> Dict[int, ProcSnap]:
    snaps: Dict[int, ProcSnap] = {}
    now  = time.time()
    gp   = glob_pattern.lower()
    patt = gp if any(c in gp for c in "*?[]") else f"*{gp}*"
    for info in psutil.process_iter(attrs=["pid", "name", "memory_info", "io_counters", "cpu_times"]):
        try:
            name = (info.info.get("name") or "").lower()
            if not fnmatch.fnmatch(name, patt): continue
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
            cpu_pct = rps = wps = 0.0
        else:
            elapsed = max(1e-6, c.ts - p.ts)
            cpu_time_delta = (c.cpu_user + c.cpu_system) - (p.cpu_user + p.cpu_system)
            cpu_pct = 100.0 * cpu_time_delta / elapsed / max(1, ncpu)
            rps = max(0.0, (c.read_bytes  - p.read_bytes)  / elapsed) / (1024 ** 2)
            wps = max(0.0, (c.write_bytes - p.write_bytes) / elapsed) / (1024 ** 2)
        rows.append({
            "pid": pid, "name": c.name,
            "cpu_pct": cpu_pct, "mem_mb": c.rss / (1024 ** 2),
            "r_mb_s": rps, "w_mb_s": wps, "d_mb_s": rps + wps,
        })
    return rows

# ═══════════════════════════ OVERALL VIEW ════════════════════════════════════
@dataclass
class OverallState:
    cpu_hist:   List[float]
    mem_hist:   List[float]
    disk_hist:  List[float]
    net_hist:   List[float]
    gpu_hist:   List[float]
    graph_mode: str = "total"

    def __init__(self):
        self.cpu_hist   = []
        self.mem_hist   = []
        self.disk_hist  = []
        self.net_hist   = []
        self.gpu_hist   = []
        self.graph_mode = "total"

def _section(label: str, color: str, pct: float, bar_w: int, detail: str = "") -> Text:
    t = Text()
    t.append(f"  {label:<5}", style=f"bold {color}")
    t.append("  ")
    t.append_text(_make_bar(pct, bar_w))
    if detail:
        t.append(f"   {detail}", style="dim")
    return t

def render_overall(ost: OverallState, nst, dst, gst) -> Panel:
    width   = term_width()
    bar_w   = max(18, min(36, width - 42))
    spark_w = max(24, min(70, width - 18))

    cpu    = safe_cpu_percent()
    mem    = safe_virtual_memory()
    m_pct  = getattr(mem, "percent", 0.0)
    m_used = getattr(mem, "used",    0) / (1024 ** 3)
    m_tot  = getattr(mem, "total",   0) / (1024 ** 3)

    c_pct = c_used = c_tot = 0.0
    try:
        cu    = psutil.disk_usage("C:\\" if os.name == "nt" else "/")
        c_pct = cu.percent
        c_used = cu.used  / (1024 ** 3)
        c_tot  = cu.total / (1024 ** 3)
    except Exception:
        pass

    gpu_rows, _ = _gpu_info_safe()
    gpu_load    = gpu_rows[0]["load"]      if gpu_rows else 0.0
    gpu_mu      = gpu_rows[0]["mem_used"]  if gpu_rows else 0.0
    gpu_mt      = gpu_rows[0]["mem_total"] if gpu_rows else 0.0
    gpu_temp    = gpu_rows[0]["temp"]      if gpu_rows else 0.0

    def _push(lst: List[float], v: float) -> None:
        lst.append(v); del lst[:-120]

    _push(ost.cpu_hist,  cpu)
    _push(ost.mem_hist,  m_pct)
    _push(ost.disk_hist, c_pct)
    if nst.hist_total_mbps: _push(ost.net_hist, nst.hist_total_mbps[-1])
    if gpu_rows:
        _push(ost.gpu_hist,  gpu_load)
        _push(gst.hist_util, gpu_load)

    indent    = "      "
    do_sparks = ost.graph_mode != "off"
    items: List = [_nav_bar("overall"), Text()]

    items.append(_section("CPU", "cyan", cpu, bar_w,
                           f"({psutil.cpu_count(logical=True)} logical cores)"))
    if do_sparks:
        items.append(_spark_text(ost.cpu_hist, spark_w, indent, "cyan"))
    items.append(Text())

    items.append(_section("RAM", "green", m_pct, bar_w,
                           f"{m_used:.1f} / {m_tot:.1f} GB"))
    if do_sparks:
        items.append(_spark_text(ost.mem_hist, spark_w, indent, "green"))
    items.append(Text())

    drive_label = "C:\\" if os.name == "nt" else "ROOT"
    items.append(_section(drive_label, "yellow", c_pct, bar_w,
                           f"{c_used:.1f} / {c_tot:.1f} GB"))
    if do_sparks:
        items.append(_spark_text(ost.disk_hist, spark_w, indent, "yellow"))
    items.append(Text())

    if gpu_rows:
        items.append(_section("GPU", "magenta", gpu_load, bar_w,
                               f"{gpu_mu:.0f} / {gpu_mt:.0f} MB  {gpu_temp:.0f}°C  "
                               f"{truncate(gpu_rows[0]['name'], 28)}"))
        if do_sparks and ost.gpu_hist:
            items.append(_spark_text(ost.gpu_hist, spark_w, indent, "magenta"))
    else:
        items.append(Text("  GPU   No GPU detected (install GPUtil or nvidia-smi)", style="dim"))
    items.append(Text())

    if nst.hist_total_mbps:
        unit = "MiB/s" if nst.units == "mib" else "Mb/s"
        items.append(Text(f"  NET    ↓↑ {nst.hist_total_mbps[-1]:.2f} {unit}", style="blue"))
        if do_sparks and ost.net_hist:
            items.append(_spark_text(ost.net_hist, spark_w, indent, "blue"))
        items.append(Text())

    items.append(_footer("[v] cycle views", "[g] toggle graphs", "[q] quit"))
    return Panel(
        Group(*items),
        title=f"[bold bright_white]SYSTEM MONITOR[/bold bright_white]  "
              f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
        border_style="bright_blue",
        box=box.DOUBLE_EDGE,
    )

# ═══════════════════════════ CPU VIEW ════════════════════════════════════════
@dataclass
class CpuState:
    hist_total: List[float]
    graph_mode: str = "total"
    label_mode: str = "name"
    col_offset: int = 0

    def __init__(self):
        self.hist_total = []
        self.graph_mode = "total"
        self.label_mode = "name"
        self.col_offset = 0

_CPU_ALL_COLS = ["PID", "Name", "CPU %", "Mem(MB)", "DΔ(MB)", "RΔ(MB)", "WΔ(MB)"]

def cpu_columns_for_width(width: int, label_mode: str) -> List[str]:
    cols = ["PID"]
    if label_mode == "name": cols.append("Name")
    base = ["CPU %", "Mem(MB)", "DΔ(MB)", "RΔ(MB)", "WΔ(MB)"]
    if width < 65:  return cols + ["CPU %"]
    if width < 80:  return cols + ["CPU %", "Mem(MB)"]
    if width < 95:  return cols + ["CPU %", "Mem(MB)", "DΔ(MB)"]
    if width < 110: return cols + ["CPU %", "Mem(MB)", "RΔ(MB)", "WΔ(MB)"]
    return cols + base

def sort_cpu_rows(rows: List[dict], mode: str) -> None:
    if   mode == "cpu":    rows.sort(key=lambda r: r.get("cpu_pct", 0.0), reverse=True)
    elif mode == "memory": rows.sort(key=lambda r: r.get("mem_mb",  0.0), reverse=True)
    elif mode == "disk":   rows.sort(key=lambda r: r.get("d_mb_s",  0.0), reverse=True)
    elif mode == "name":   rows.sort(key=lambda r: r.get("name",     "").lower())
    else:                  random.shuffle(rows)

def render_cpu_table(rows: List[dict], total: int, limit: int, sort_mode: str,
                     cpu_state: CpuState) -> Panel:
    width = term_width()
    inner = max(1, width - 4)

    graph_lines   = 2 if cpu_state.graph_mode != "off" else 0
    footer_text   = "[v] view  [s] sort  [+/-] topN  ]/[ interval  [g] graphs  [x] label  [q] quit  ←/→ cols"
    cap_text      = f"  {min(limit, 99)} of {total} procs  │  sort: {sort_mode}"
    overhead      = 2 + graph_lines + 1 + 2 + _visual_lines(cap_text, inner) + _visual_lines(footer_text, inner)
    display_limit = max(1, min(limit, term_height() - overhead))

    base_cols = cpu_columns_for_width(width, cpu_state.label_mode)
    offset    = min(cpu_state.col_offset, max(0, len(base_cols) - 1))
    cols      = base_cols[offset:] or base_cols[-1:]
    name_cap  = max(8, min(24, width - 46))

    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True,
                  header_style="bold cyan", border_style="grey35")
    for col in cols:
        if   col == "PID":  table.add_column("PID",  justify="right", no_wrap=True, min_width=5)
        elif col == "Name": table.add_column("Name", justify="left",  no_wrap=True, overflow="ellipsis", width=name_cap)
        else:               table.add_column(col,    justify="right", no_wrap=True, min_width=7)

    for r in rows[:display_limit]:
        vals = []
        if "PID"     in cols: vals.append(str(r["pid"]))
        if "Name"    in cols: vals.append(truncate(r["name"], name_cap))
        if "CPU %"   in cols: vals.append(f"[{_pct_style(r['cpu_pct'])}]{r['cpu_pct']:.1f}[/]")
        if "Mem(MB)" in cols: vals.append(f"{r['mem_mb']:.1f}")
        if "DΔ(MB)"  in cols: vals.append(f"{r['d_mb_s']:.2f}")
        if "RΔ(MB)"  in cols: vals.append(f"{r['r_mb_s']:.2f}")
        if "WΔ(MB)"  in cols: vals.append(f"{r['w_mb_s']:.2f}")
        row_style = _pct_style(r["cpu_pct"]) if r["cpu_pct"] >= 50 else ""
        table.add_row(*vals, style=row_style)

    total_cpu = safe_cpu_percent()
    cpu_state.hist_total.append(total_cpu); del cpu_state.hist_total[:-120]

    scroll_hint = f"  ◀ {offset} cols hidden" if offset > 0 else ""
    items: List = [_nav_bar("cpu")]
    if cpu_state.graph_mode != "off":
        sw = max(20, min(80, width - 18))
        items.append(Text.assemble(("  CPU  ", "bold cyan"), _make_bar(total_cpu, sw)))
        items.append(_spark_text(cpu_state.hist_total, sw, "      ", "cyan"))
    items.extend([Text(), table, Text(f"{cap_text}{scroll_hint}", style="dim"), _footer(footer_text)])
    return Panel(Group(*items), title="[bold]CPU / Processes[/bold]", border_style="cyan", box=box.HEAVY_EDGE)

# ═══════════════════════════ DISK VIEW ═══════════════════════════════════════
@dataclass
class DiskLiveState:
    prev: Dict
    last_ts: float
    hist_total_mb_s: List[float]
    graph_mode: str = "total"
    per_disk_available: bool = True
    label_mode: str = "name"
    win_drive_model_map:  Dict[str, str] = None
    win_drive_letter_map: Dict[str, str] = None
    col_offset: int = 0

    def __init__(self):
        self.prev                 = {}
        self.last_ts              = time.time()
        self.hist_total_mb_s      = []
        self.graph_mode           = "total"
        self.per_disk_available   = True
        self.label_mode           = "name"
        self.win_drive_model_map  = {}
        self.win_drive_letter_map = {}
        self.col_offset           = 0

def safe_disk_io_counters_perdisk() -> Dict:
    try:    return psutil.disk_io_counters(perdisk=True) or {}
    except: return {}

def _win_populate_drive_models() -> Dict[str, str]:
    if os.name != "nt": return {}
    try:
        out = subprocess.check_output(
            ["wmic", "diskdrive", "get", "index,model", "/format:csv"],
            text=True, stderr=subprocess.DEVNULL, timeout=1.5
        )
        mapping: Dict[str, str] = {}
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 3 and parts[-1].isdigit():
                mapping[f"PhysicalDrive{parts[-1]}"] = parts[-2]
        return mapping
    except Exception:
        return {}

def _win_populate_drive_letters() -> Dict[str, str]:
    """Return {'PhysicalDrive0': 'C:, D:', 'PhysicalDrive1': 'E:'} etc."""
    if os.name != "nt": return {}
    try:
        script = (
            "Get-Partition | Where-Object {$_.DriveLetter} | "
            "ForEach-Object { 'PhysicalDrive' + $_.DiskNumber + '=' + $_.DriveLetter + ':' }"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            text=True, stderr=subprocess.DEVNULL, timeout=4.0
        )
        raw: Dict[str, List[str]] = {}
        for line in out.strip().splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                raw.setdefault(k.strip(), []).append(v.strip())
        return {k: ", ".join(sorted(v)) for k, v in raw.items()}
    except Exception:
        return {}

def _disk_display_name(dev: str, state: DiskLiveState) -> str:
    letters = state.win_drive_letter_map.get(dev)
    if letters: return letters
    model = state.win_drive_model_map.get(dev)
    if model: return model
    return dev

def disk_perdisk_snapshot(state: DiskLiveState) -> Dict[str, Tuple[float, float, float, str]]:
    curr = safe_disk_io_counters_perdisk()
    if not curr:
        state.per_disk_available = False
        return {}
    state.per_disk_available = True
    now = time.time()
    dt  = max(1e-6, now - state.last_ts)
    out: Dict[str, Tuple[float, float, float, str]] = {}
    total_bw = 0.0

    if os.name == "nt":
        if not state.win_drive_model_map:  state.win_drive_model_map  = _win_populate_drive_models()
        if not state.win_drive_letter_map: state.win_drive_letter_map = _win_populate_drive_letters()

    for dev, io in curr.items():
        prv = state.prev.get(dev)
        read_bps = write_bps = util = 0.0
        if prv:
            d_read  = max(0, io.read_bytes  - prv.read_bytes)  / dt
            d_write = max(0, io.write_bytes - prv.write_bytes) / dt
            d_time  = max(0, (io.read_time + io.write_time) - (prv.read_time + prv.write_time))
            util    = min(100.0, (d_time / (dt * 1000.0)) * 100.0)
            read_bps, write_bps = d_read, d_write
            total_bw += (d_read + d_write) / (1024 ** 2)
        out[dev] = (read_bps, write_bps, util, _disk_display_name(dev, state))

    state.hist_total_mb_s.append(total_bw); del state.hist_total_mb_s[:-120]
    state.prev    = curr
    state.last_ts = now
    return out

def disk_usage_table() -> Optional[Table]:
    try: parts = psutil.disk_partitions()
    except: return None

    table = Table(title="[bold]Disk Usage[/bold]", box=box.SIMPLE_HEAVY,
                  header_style="bold yellow", border_style="grey35", expand=True)
    table.add_column("Drive",  style="yellow",  no_wrap=True)
    table.add_column("FS",     style="dim")
    table.add_column("Total",  justify="right")
    table.add_column("Free",   justify="right")
    table.add_column("Used",   justify="right", no_wrap=True)
    table.add_column("",       no_wrap=True, min_width=20)

    for part in parts:
        try: u = psutil.disk_usage(part.mountpoint)
        except: continue
        table.add_row(
            part.mountpoint, part.fstype,
            f"{u.total/1e9:.1f} GB", f"{u.free/1e9:.1f} GB",
            Text(f"{u.percent:.1f}%", style=_pct_style(u.percent)),
            _make_bar(u.percent, 18),
        )
    return table

def per_disk_perf_table(inst: Dict[str, Tuple[float, float, float, str]]) -> Table:
    table = Table(title="[bold]Drive I/O[/bold]", box=box.SIMPLE_HEAVY,
                  header_style="bold green", border_style="grey35", expand=True)
    table.add_column("Drive",      style="green")
    table.add_column("Read MB/s",  justify="right")
    table.add_column("Write MB/s", justify="right")
    table.add_column("Util",       justify="right", no_wrap=True)
    table.add_column("",           no_wrap=True, min_width=16)

    for dev, (rb, wb, util, disp) in inst.items():
        table.add_row(
            disp or dev,
            f"{rb/(1024**2):.2f}", f"{wb/(1024**2):.2f}",
            Text(f"{util:.1f}%", style=_pct_style(util)),
            _make_bar(util, 14),
        )
    return table

_DISK_ALL_COLS = ["PID", "Name", "R", "W", "D"]

def render_disk_view(proc_rows: List[dict], total_procs: int, top_n: int, sort_mode: str,
                     dstate: DiskLiveState) -> Panel:
    width  = term_width()
    height = term_height()
    inner  = max(1, width - 4)

    graph_lines   = 2 if dstate.graph_mode != "off" else 0
    footer_text   = "[v] view  [s] sort  [+/-] topN  ]/[ interval  [g] graphs  [x] label  [q] quit  ←/→ cols"
    cap_text      = f"  {min(top_n, 99)} of {total_procs} procs  │  sort: {sort_mode}"
    overhead      = 2 + graph_lines + 1 + 2 + _visual_lines(cap_text, inner) + _visual_lines(footer_text, inner)
    display_limit = max(1, min(top_n, height - overhead))

    offset       = min(dstate.col_offset, len(_DISK_ALL_COLS) - 1)
    visible_cols = _DISK_ALL_COLS[offset:] or _DISK_ALL_COLS[-1:]
    name_cap     = max(6, min(20, width - 30))

    ptable = Table(box=box.SIMPLE_HEAVY, expand=True, title="[bold]Per-Process Disk I/O[/bold]",
                   header_style="bold green", border_style="grey35")
    if "PID"  in visible_cols: ptable.add_column("PID",        justify="right", no_wrap=True, min_width=5)
    if "Name" in visible_cols and dstate.label_mode == "name":
        ptable.add_column("Name",       justify="left",  no_wrap=True, overflow="ellipsis", width=name_cap)
    if "R" in visible_cols: ptable.add_column("Read MB/s",  justify="right", no_wrap=True, min_width=9)
    if "W" in visible_cols: ptable.add_column("Write MB/s", justify="right", no_wrap=True, min_width=10)
    if "D" in visible_cols: ptable.add_column("Total MB/s", justify="right", no_wrap=True, min_width=10)

    for r in proc_rows[:display_limit]:
        row = []
        if "PID"  in visible_cols: row.append(str(r["pid"]))
        if "Name" in visible_cols and dstate.label_mode == "name": row.append(truncate(r["name"], name_cap))
        if "R"    in visible_cols: row.append(f"{r['r_mb_s']:.2f}")
        if "W"    in visible_cols: row.append(f"{r['w_mb_s']:.2f}")
        if "D"    in visible_cols: row.append(f"{r['d_mb_s']:.2f}")
        ptable.add_row(*row)

    scroll_hint = f"  ◀ {offset} cols hidden" if offset > 0 else ""
    inst  = disk_perdisk_snapshot(dstate)
    items: List = [_nav_bar("disk")]

    if dstate.graph_mode != "off":
        sw     = max(20, min(80, width - 18))
        latest = dstate.hist_total_mb_s[-1] if dstate.hist_total_mb_s else 0.0
        items.append(Text.assemble(("  Disk  ", "bold green"), f"  {latest:.2f} MB/s total"))
        items.append(_spark_text(dstate.hist_total_mb_s, sw, "        ", "green"))

    items.extend([Text(), ptable, Text(f"{cap_text}{scroll_hint}", style="dim")])

    if inst:
        items.extend([Text(), per_disk_perf_table(inst)])
    elif not dstate.per_disk_available:
        items.append(Text("  Per-disk stats unavailable (permissions / platform)", style="dim"))

    du = disk_usage_table()
    if du and width >= 90:
        items.extend([Text(), du])

    items.extend([Text(), _footer(footer_text)])
    return Panel(Group(*items), title="[bold]DISK[/bold]", border_style="green", box=box.HEAVY_EDGE)

# ═══════════════════════════ NET VIEW ════════════════════════════════════════
def _sysfs_sum_net_bytes() -> Optional[Tuple[int, int]]:
    base = "/sys/class/net"
    try:
        if not os.path.isdir(base): return None
        total_rx = total_tx = 0
        for iface in os.listdir(base):
            if iface == "lo": continue
            sd = os.path.join(base, iface, "statistics")
            try:
                with open(os.path.join(sd, "rx_bytes")) as f: total_rx += int(f.read())
                with open(os.path.join(sd, "tx_bytes")) as f: total_tx += int(f.read())
            except: continue
        return (total_tx, total_rx)
    except: return None

def get_total_counters() -> Tuple[int, int]:
    try:
        c = psutil.net_io_counters(pernic=False)
        return c.bytes_sent, c.bytes_recv
    except:
        return _sysfs_sum_net_bytes() or (0, 0)

def sum_active_link_capacity_mbps() -> float:
    total = 0.0
    try:
        for _, st in psutil.net_if_stats().items():
            if st.isup and st.speed and st.speed > 0:
                total += float(st.speed)
    except: pass
    return total

@dataclass
class NetState:
    units: str = "mb"
    prev_total: Tuple[int, int] = (0, 0)
    prev_time: float = 0.0
    link_cap_mbps: float = 0.0
    hist_total_mbps: List[float] = None
    per_proc_on: bool = True
    graph_mode: str = "total"
    label_mode: str = "name"
    col_offset: int = 0
    def __post_init__(self):
        if self.hist_total_mbps is None: self.hist_total_mbps = []

_NET_ALL_COLS = ["PID", "Name", "Σ"]

def render_net_panel(state: NetState, top_n: int, interval_hint: float,
                     proc_rows: List[dict]) -> Panel:
    now     = time.time()
    elapsed = max(1e-6, (now - state.prev_time) if state.prev_time else interval_hint)

    curr_total = get_total_counters()
    sent_bps   = (curr_total[0] - state.prev_total[0]) * 8.0 / elapsed
    recv_bps   = (curr_total[1] - state.prev_total[1]) * 8.0 / elapsed
    total_bps  = max(0.0, sent_bps + recv_bps)

    unit_label  = "MiB/s" if state.units == "mib" else "Mb/s"
    sent_mbps   = human_mbps(sent_bps,  state.units)
    recv_mbps   = human_mbps(recv_bps,  state.units)
    total_mbps  = human_mbps(total_bps, state.units)
    util        = (total_mbps / state.link_cap_mbps * 100.0) if state.link_cap_mbps > 0 else 0.0

    state.hist_total_mbps.append(total_mbps); del state.hist_total_mbps[:-120]

    width  = term_width()
    inner  = max(1, width - 4)
    footer = "[v] view  [s] sort  [+/-] topN  ]/[ interval  [m] units  [p] per-proc  [g] graphs  [x] label  [q] quit"
    overhead      = 2 + (1 if state.graph_mode != "off" else 0) + 4 + _visual_lines(footer, inner)
    display_limit = max(1, min(top_n, term_height() - overhead))

    offset       = min(state.col_offset, len(_NET_ALL_COLS) - 1)
    visible_cols = _NET_ALL_COLS[offset:] or _NET_ALL_COLS[-1:]
    name_cap     = max(8, min(24, width - 26))
    sigma_hdr    = "ΣMiB/s" if state.units == "mib" else "ΣMb/s"

    table = Table(box=box.SIMPLE_HEAVY, expand=True,
                  header_style="bold magenta", border_style="grey35")
    if "PID"  in visible_cols: table.add_column("PID",     justify="right", no_wrap=True, min_width=5)
    if "Name" in visible_cols and state.label_mode == "name":
        table.add_column("Process", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    if "Σ" in visible_cols: table.add_column(sigma_hdr, justify="right", no_wrap=True, min_width=8)

    if state.per_proc_on and proc_rows:
        for r in proc_rows[:display_limit]:
            row = []
            if "PID"  in visible_cols: row.append(str(r["pid"]))
            if "Name" in visible_cols and state.label_mode == "name": row.append(truncate(r["name"], name_cap))
            if "Σ"    in visible_cols: row.append(f"{r['d_mb_s']:.2f}")
            table.add_row(*row)
    else:
        row = []
        if "PID"  in visible_cols: row.append("-")
        if "Name" in visible_cols and state.label_mode == "name": row.append("(per-proc off  press [p])")
        if "Σ"    in visible_cols: row.append("-")
        table.add_row(*row)

    scroll_hint = f"   ◀ {offset} cols hidden" if offset > 0 else ""
    sw = max(20, min(80, width - 18))
    items: List = [_nav_bar("net"), Text()]

    summary = Text()
    down_style = _pct_style(min(100, recv_mbps / max(0.01, state.link_cap_mbps) * 100)) if state.link_cap_mbps else "cyan"
    up_style   = _pct_style(min(100, sent_mbps / max(0.01, state.link_cap_mbps) * 100)) if state.link_cap_mbps else "magenta"
    summary.append("  ↓ ", style="bold cyan");     summary.append(f"{recv_mbps:8.2f} {unit_label}", style=down_style)
    summary.append("    ↑ ", style="bold magenta"); summary.append(f"{sent_mbps:8.2f} {unit_label}", style=up_style)
    summary.append(f"    Σ {total_mbps:.2f}  ", style="bold white")
    if state.link_cap_mbps > 0:
        summary.append("util ", style="dim"); summary.append_text(_make_bar(util, 16))
    items.append(summary)

    if state.graph_mode != "off":
        items.append(_spark_text(state.hist_total_mbps, sw, "      ", "magenta"))

    link_cap_txt = (f"  Link capacity: {int(state.link_cap_mbps):,} Mb/s"
                    if state.link_cap_mbps > 0 else "  Link capacity: unknown")
    items.extend([Text(link_cap_txt, style="dim"), Text(),
                  table, Text(f"  {min(display_limit, len(proc_rows))} of {len(proc_rows)} procs{scroll_hint}", style="dim"),
                  Text(), _footer(footer)])

    state.prev_total = curr_total
    state.prev_time  = now
    return Panel(Group(*items), title="[bold]NETWORK[/bold]", border_style="magenta", box=box.HEAVY_EDGE)

# ═══════════════════════════ GPU VIEW ════════════════════════════════════════
@dataclass
class GpuState:
    hist_util: List[float]
    graph_mode: str = "total"

    def __init__(self):
        self.hist_util  = []
        self.graph_mode = "total"

def _gpu_info_safe() -> Tuple[List[dict], Optional[str]]:
    try:
        import GPUtil  # type: ignore
        return [{"name": g.name, "id": g.id, "load": g.load * 100.0,
                 "mem_used": g.memoryUsed, "mem_total": g.memoryTotal, "temp": g.temperature}
                for g in GPUtil.getGPUs()], None
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=name,index,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, text=True, timeout=1.5
        )
        rows = []
        for line in out.strip().splitlines():
            name, idx, util, mu, mt, temp = [s.strip() for s in line.split(",")]
            rows.append({"name": name, "id": int(idx), "load": float(util),
                         "mem_used": float(mu), "mem_total": float(mt), "temp": float(temp)})
        return rows, None
    except Exception:
        return [], "GPU info unavailable (install GPUtil or nvidia-smi)"

# Keep legacy name for sysmon_capture.py compatibility
def gpu_info() -> Tuple[List[dict], Optional[str]]:
    return _gpu_info_safe()

def render_gpu(gst: GpuState) -> Panel:
    width   = term_width()
    bar_w   = max(18, min(36, width - 42))
    spark_w = max(24, min(70, width - 18))
    rows, err = _gpu_info_safe()

    items: List = [_nav_bar("gpu"), Text()]
    if rows:
        for r in rows:
            mem_pct  = (r["mem_used"] / r["mem_total"] * 100.0) if r["mem_total"] else 0.0
            gpu_name = truncate(r["name"], max(10, min(36, width - 50)))
            items.append(Text(f"  GPU {r['id']}  {gpu_name}", style="bold blue"))
            items.append(Text())
            items.append(Text.assemble(("    Util   ", "bold magenta"), _make_bar(r["load"], bar_w)))
            items.append(Text.assemble(("    Memory ", "bold blue"),
                                       _make_bar(mem_pct, bar_w),
                                       Text(f"   {r['mem_used']:.0f} / {r['mem_total']:.0f} MB", style="dim")))
            items.append(Text.assemble(("    Temp   ", "bold yellow"),
                                       Text(f"{r['temp']:.0f} °C",
                                            style="bold red" if r["temp"] >= 85
                                            else "yellow" if r["temp"] >= 70 else "green")))
            if gst.graph_mode != "off":
                gst.hist_util.append(r["load"]); del gst.hist_util[:-120]
                items.append(_spark_text(gst.hist_util, spark_w, "    Hist   ", "magenta"))
            items.append(Text())
    else:
        items.append(Text(f"  {err or 'No GPU detected'}", style="dim"))
        items.append(Text())

    items.append(_footer("[v] cycle views", "[g] toggle graphs", "[q] quit"))
    return Panel(Group(*items), title="[bold]GPU[/bold]", border_style="blue", box=box.HEAVY_EDGE)

# ═══════════════════════════ CLI / Main ══════════════════════════════════════
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Beautiful system monitor — CPU/NET/DISK/GPU TUI")
    p.add_argument("-t", "--top",      type=int,   default=15,        help="Top N process rows (1-99)")
    p.add_argument("-i", "--interval", type=float, default=0.25,
                   help="Data refresh interval in seconds (0.1–5.0, default 0.25)")
    p.add_argument("-g", "--glob",     type=str,   default="*",       help="Process name glob filter (CPU/DISK views)")
    p.add_argument("-w", "--view",     choices=VIEWS, default="overall", help="Initial view")
    p.add_argument("-S", "--sort",     choices=CPU_SORTS + NET_SORTS + DISK_SORTS, default="cpu",
                   help="Initial sort mode")
    p.add_argument("-u", "--units",    choices=UNITS, default="mb",   help="Network units (mb or mib)")
    p.add_argument("--low-prio",       action="store_true",           help="Lower this process priority")
    p.add_argument("-v", "--verbose",  action="store_true",           help="Verbose logs to stderr")
    return p.parse_args(argv)

def set_low_priority() -> None:
    try:
        if os.name == "nt": psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:               os.nice(5)
    except Exception: pass

def main(argv: Optional[Sequence[str]] = None) -> None:
    args     = parse_args(argv)
    if args.low_prio: set_low_priority()

    top_n    = int(clamp(args.top, 1, 99))
    interval = float(clamp(args.interval, 0.1, 5.0))

    cpu_sort  = args.sort if args.sort in CPU_SORTS  else "cpu"
    net_sort  = args.sort if args.sort in NET_SORTS  else "mbps"
    disk_sort = args.sort if args.sort in DISK_SORTS else "total"
    view_idx  = VIEWS.index(args.view)

    ncpu = psutil.cpu_count(logical=True) or 1

    cpu_state  = CpuState()
    net_state  = NetState(units=args.units)
    net_state.prev_total    = get_total_counters()
    net_state.prev_time     = time.time()
    net_state.link_cap_mbps = sum_active_link_capacity_mbps()
    net_state.per_proc_on   = True
    disk_state = DiskLiveState()
    disk_state.prev = safe_disk_io_counters_perdisk()
    over_state = OverallState()
    gpu_state  = GpuState()

    prev_snaps:     Dict[int, ProcSnap] = {}
    prev_net_snaps: Dict[int, ProcSnap] = {}
    help_on        = False
    render_deadline = 0.0   # render immediately on first tick

    # ── Key-polling loop: checks keys at ~20 Hz, renders at `interval` Hz ──
    with KeyReader() as keys, Live(refresh_per_second=20, redirect_stdout=False) as live:
        while True:
            ch = keys.read()
            if ch:
                low = ch.lower()
                v   = VIEWS[view_idx]
                if   low == "q": break
                elif low == "v": view_idx = (view_idx + 1) % len(VIEWS)
                elif low == "s":
                    if   v == "cpu":  cpu_sort  = CPU_SORTS[ (CPU_SORTS.index(cpu_sort)   + 1) % len(CPU_SORTS)]
                    elif v == "net":  net_sort  = NET_SORTS[ (NET_SORTS.index(net_sort)   + 1) % len(NET_SORTS)]
                    elif v == "disk": disk_sort = DISK_SORTS[(DISK_SORTS.index(disk_sort) + 1) % len(DISK_SORTS)]
                elif ch == "+": top_n = int(clamp(top_n + 1, 1, 99))
                elif ch == "-": top_n = int(clamp(top_n - 1, 1, 99))
                elif ch == "]": interval = float(clamp(interval + 0.1, 0.1, 5.0))
                elif ch == "[": interval = float(clamp(interval - 0.1, 0.1, 5.0))
                elif low == "m": net_state.units = "mib" if net_state.units == "mb" else "mb"
                elif low == "p": net_state.per_proc_on = not net_state.per_proc_on
                elif low == "g":
                    modes = GRAPH_MODES
                    if   v == "overall": over_state.graph_mode  = modes[(modes.index(over_state.graph_mode)  + 1) % 2]
                    elif v == "cpu":     cpu_state.graph_mode   = modes[(modes.index(cpu_state.graph_mode)   + 1) % 2]
                    elif v == "net":     net_state.graph_mode   = modes[(modes.index(net_state.graph_mode)   + 1) % 2]
                    elif v == "disk":    disk_state.graph_mode  = modes[(modes.index(disk_state.graph_mode)  + 1) % 2]
                    elif v == "gpu":     gpu_state.graph_mode   = modes[(modes.index(gpu_state.graph_mode)   + 1) % 2]
                elif low == "x":
                    if   v == "cpu":  cpu_state.label_mode  = "pid" if cpu_state.label_mode  == "name" else "name"
                    elif v == "net":  net_state.label_mode  = "pid" if net_state.label_mode  == "name" else "name"
                    elif v == "disk": disk_state.label_mode = "pid" if disk_state.label_mode == "name" else "name"
                elif ch == "RIGHT":
                    if   v == "cpu":  cpu_state.col_offset  = min(cpu_state.col_offset  + 1, len(_CPU_ALL_COLS) - 1)
                    elif v == "net":  net_state.col_offset  = min(net_state.col_offset  + 1, len(_NET_ALL_COLS) - 1)
                    elif v == "disk": disk_state.col_offset = min(disk_state.col_offset + 1, len(_DISK_ALL_COLS) - 1)
                elif ch == "LEFT":
                    if   v == "cpu":  cpu_state.col_offset  = max(0, cpu_state.col_offset  - 1)
                    elif v == "net":  net_state.col_offset  = max(0, net_state.col_offset  - 1)
                    elif v == "disk": disk_state.col_offset = max(0, disk_state.col_offset - 1)
                elif low == "h":
                    help_on = not help_on
                # Any key press forces an immediate re-render
                render_deadline = 0.0

            # ── Skip render if interval hasn't elapsed ─────────────────────
            now = time.time()
            if now < render_deadline:
                time.sleep(0.05)   # poll keys at ~20 Hz while waiting
                continue

            render_deadline = now + interval

            # ── Collect data and render active view ────────────────────────
            current_view = VIEWS[view_idx]

            if current_view in ("cpu", "disk"):
                curr_snaps  = iter_snaps(args.glob)
                rows        = deltas(prev_snaps, curr_snaps, ncpu)
                total_procs = len(curr_snaps)
                prev_snaps  = curr_snaps

                if current_view == "cpu":
                    rows_cpu = list(rows)
                    sort_cpu_rows(rows_cpu, cpu_sort)
                    panel = render_cpu_table(rows_cpu, total=total_procs, limit=top_n,
                                             sort_mode=cpu_sort, cpu_state=cpu_state)
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
                    curr_snaps     = iter_snaps("*")
                    proc_rows      = deltas(prev_net_snaps, curr_snaps, ncpu)
                    prev_net_snaps = curr_snaps
                    proc_rows.sort(key=lambda r: r["d_mb_s"] if net_sort == "mbps" else r["name"].lower(),
                                   reverse=(net_sort == "mbps"))
                panel = render_net_panel(net_state, top_n=top_n, interval_hint=interval,
                                         proc_rows=proc_rows)

            elif current_view == "overall":
                _now = time.time()
                if net_state.prev_time == 0.0:
                    net_state.prev_time  = _now
                    net_state.prev_total = get_total_counters()
                else:
                    ct  = get_total_counters()
                    _el = max(1e-6, _now - net_state.prev_time)
                    _bps = max(0.0, ((ct[0] - net_state.prev_total[0]) +
                                     (ct[1] - net_state.prev_total[1])) * 8.0 / _el)
                    net_state.hist_total_mbps.append(human_mbps(_bps, net_state.units))
                    del net_state.hist_total_mbps[:-120]
                    net_state.prev_total, net_state.prev_time = ct, _now
                _ = disk_perdisk_snapshot(disk_state)
                panel = render_overall(over_state, net_state, disk_state, gpu_state)

            else:  # gpu
                panel = render_gpu(gpu_state)

            if help_on:
                help_text = Text(
                    "q quit  •  v cycle views  •  s sort  •  +/- top rows  •  ]/[ interval\n"
                    "m units (NET)  •  p per-proc (NET)  •  g graphs  •  x label (Name↔PID)\n"
                    "Views: overall  cpu  net  disk  gpu\n"
                    "CPU sort: cpu memory disk name random  │  NET: mbps name  │  DISK: read write total name",
                    style="yellow",
                )
                live.update(Panel(Group(panel,
                                        Panel(help_text, title="[bold yellow]Help[/bold yellow]",
                                              border_style="yellow"))))
            else:
                live.update(panel)
            # No sleep here — loop immediately to poll keys


if __name__ == "__main__":
    main()
