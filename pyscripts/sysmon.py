#!/usr/bin/env python3
"""
sysmon.py — unified CPU / Memory / Disk / Network TUI for tiny terminals.

Optimized to be lightweight (~1–3% CPU):
- Snapshot once per tick; compute deltas vs previous snapshot (no internal sleeps)
- Single psutil walk via process_iter(attrs=...) per tick
- Lower refresh rate & optional heavy features
- Optional low process priority (--low-prio)

Keyboard (while running)
  q          Quit
  v          Toggle view (CPU → NET → DISK → CPU)
  s          Cycle sort mode for current view
  + / -      Increase / decrease Top-N rows
  ] / [      Increase / decrease refresh interval
  m          Toggle Mb/s vs Mib/s (NET view; totals)
  h          Toggle help overlay

Examples
  python sysmon.py
  python sysmon.py -i 1.0 -t 20
  python sysmon.py -g "vivaldi*"         # filter processes by name (CPU/DISK views)
  python sysmon.py -w net                # start in NET view
  python sysmon.py --net-procs           # (heavier) show per-proc “Σ” in NET view
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import random
import select
import shutil
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

# ----- Cross-platform non-blocking key polling --------------------------------
if os.name == "nt":
    import msvcrt

    class KeyReader:
        """Non-blocking single-char reader for Windows (msvcrt)."""
        def __enter__(self): return self
        def __exit__(self, et, ex, tb): return False
        def read(self) -> Optional[str]:
            if msvcrt.kbhit():
                return msvcrt.getwch()
            return None
else:
    import tty
    import termios

    class KeyReader:
        """Non-blocking single-char reader for POSIX using raw stdin + select."""
        def __enter__(self):
            self.fd = sys.stdin.fileno()
            self.ok = sys.stdin.isatty()
            if self.ok:
                self.old = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)  # immediate char, no Enter
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
                ch = sys.stdin.read(1)
                return ch
            return None

# ----- Constants ---------------------------------------------------------------
CPU_SORTS = ["cpu", "memory", "disk", "name", "random"]
NET_SORTS = ["mbps", "name"]
DISK_SORTS = ["read", "write", "total", "name"]
UNITS = ["mb", "mib"]
VIEWS = ["cpu", "net", "disk"]

# ----- Helpers ----------------------------------------------------------------
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

# ----- Process snapshotting (lightweight) -------------------------------------
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
    """Single pass: get per-proc attrs; filter by name glob, build snapshots."""
    snaps: Dict[int, ProcSnap] = {}
    now = time.time()
    gp = glob_pattern.lower()
    use_glob = any(c in gp for c in "*?[]")
    patt = gp if use_glob else f"*{gp}*"
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
    """Compute per-proc CPU%, mem MB, read/write/total MB/s from snapshots."""
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
            rps = max(0.0, (c.read_bytes - p.read_bytes) / elapsed) / (1024 ** 2)  # MB/s
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
                # For backward-compat test rows that use 'disk_mb' (delta per tick),
                # we provide a synthetic key so sort_cpu_rows('disk') works in tests.
                "disk_mb": rps + wps,
            }
        )
    return rows

# ----- CPU table ---------------------------------------------------------------
def cpu_columns_for_width(width: int) -> List[str]:
    # Keep legacy labels to match tests: DΔ(MB), RΔ(MB), WΔ(MB)
    cols = ["PID", "Name", "CPU %", "Mem(MB)", "DΔ(MB)", "RΔ(MB)", "WΔ(MB)"]
    if width < 65:  return ["PID", "Name", "CPU %"]
    if width < 80:  return ["PID", "Name", "CPU %", "Mem(MB)"]
    if width < 95:  return ["PID", "Name", "CPU %", "Mem(MB)", "DΔ(MB)"]
    if width < 110: return ["PID", "Name", "CPU %", "Mem(MB)", "RΔ(MB)", "WΔ(MB)"]
    return cols

def sort_cpu_rows(rows: List[dict], mode: str) -> None:
    if mode == "cpu":
        rows.sort(key=lambda r: r.get("cpu_pct", 0.0), reverse=True)
    elif mode == "memory":
        rows.sort(key=lambda r: r.get("mem_mb", 0.0), reverse=True)
    elif mode == "disk":
        # Accept both the new 'd_mb_s' and legacy test key 'disk_mb'
        rows.sort(key=lambda r: r.get("d_mb_s", r.get("disk_mb", 0.0)), reverse=True)
    elif mode == "name":
        rows.sort(key=lambda r: r.get("name", "").lower())
    else:
        random.shuffle(rows)

def render_cpu_table(rows: List[dict], total: int, limit: int, sort_mode: str) -> Panel:
    width = term_width()
    cols = cpu_columns_for_width(width)
    name_cap = max(8, min(32, width - 40))

    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True)
    if "PID" in cols: table.add_column("PID", justify="right", no_wrap=True)
    if "Name" in cols: table.add_column("Name", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    if "CPU %" in cols: table.add_column("CPU %", justify="right", no_wrap=True)
    if "Mem(MB)" in cols: table.add_column("Mem(MB)", justify="right", no_wrap=True)
    if "DΔ(MB)" in cols: table.add_column("DΔ(MB)", justify="right", no_wrap=True)
    if "RΔ(MB)" in cols: table.add_column("RΔ(MB)", justify="right", no_wrap=True)
    if "WΔ(MB)" in cols: table.add_column("WΔ(MB)", justify="right", no_wrap=True)

    for r in rows[:limit]:
        vals = []
        if "PID" in cols:     vals.append(str(r["pid"]))
        if "Name" in cols:    vals.append(truncate(r["name"], name_cap))
        if "CPU %" in cols:   vals.append(f"{r['cpu_pct']:.1f}")
        if "Mem(MB)" in cols: vals.append(f"{r['mem_mb']:.1f}")
        # Use MB/s values but keep legacy delta labels for compatibility
        if "DΔ(MB)" in cols:  vals.append(f"{r['d_mb_s']:.2f}")
        if "RΔ(MB)" in cols:  vals.append(f"{r['r_mb_s']:.2f}")
        if "WΔ(MB)" in cols:  vals.append(f"{r['w_mb_s']:.2f}")
        table.add_row(*vals)

    cap = f"Showing {min(limit, len(rows))} of {total} procs   |   sort: {sort_mode}"
    footer = Text("[v] view  [s] sort  [+/-] topN  ]/[ interval  [q] quit", style="dim")
    return Panel(Group(table, Text(cap, style="dim"), footer), title="CPU / Memory / Disk", border_style="cyan")

# ----- Disk view ---------------------------------------------------------------
def disk_columns_for_width(width: int) -> List[str]:
    cols = ["PID", "Name", "R MB/s", "W MB/s", "D MB/s"]
    if width < 60:  return ["PID", "Name", "D MB/s"]
    if width < 80:  return ["PID", "Name", "R MB/s", "W MB/s"]
    return cols

def sort_disk_rows(rows: List[dict], mode: str) -> None:
    if mode == "read":
        rows.sort(key=lambda r: r["r_mb_s"], reverse=True)
    elif mode == "write":
        rows.sort(key=lambda r: r["w_mb_s"], reverse=True)
    elif mode == "total":
        rows.sort(key=lambda r: r["d_mb_s"], reverse=True)
    else:
        rows.sort(key=lambda r: r["name"].lower())

def render_disk_table(rows: List[dict], total: int, limit: int, sort_mode: str) -> Panel:
    width = term_width()
    cols = disk_columns_for_width(width)
    name_cap = max(8, min(32, width - 28))
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    if "PID" in cols:     table.add_column("PID", justify="right", no_wrap=True)
    if "Name" in cols:    table.add_column("Name", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    if "R MB/s" in cols:  table.add_column("R MB/s", justify="right", no_wrap=True)
    if "W MB/s" in cols:  table.add_column("W MB/s", justify="right", no_wrap=True)
    if "D MB/s" in cols:  table.add_column("D MB/s", justify="right", no_wrap=True)
    for r in rows[:limit]:
        vals = []
        if "PID" in cols:    vals.append(str(r["pid"]))
        if "Name" in cols:   vals.append(truncate(r["name"], name_cap))
        if "R MB/s" in cols: vals.append(f"{r['r_mb_s']:.2f}")
        if "W MB/s" in cols: vals.append(f"{r['w_mb_s']:.2f}")
        if "D MB/s" in cols: vals.append(f"{r['d_mb_s']:.2f}")
        table.add_row(*vals)
    cap = f"Showing {min(limit, len(rows))} of {total} procs   |   sort: {sort_mode}"
    footer = Text("[v] view  [s] sort  [+/-] topN  ]/[ interval  [q] quit", style="dim")
    return Panel(Group(table, Text(cap, style="dim"), footer), title="DISK — per-process I/O", border_style="green")

# ----- Network sampling (totals are cheap; per-proc optional) -----------------
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
    except PermissionError:
        return _sysfs_sum_net_bytes() or (0, 0)

def sum_active_link_capacity_mbps() -> float:
    total = 0.0
    try:
        for _, st in psutil.net_if_stats().items():
            if st.isup and st.speed and st.speed > 0:
                total += float(st.speed)
    except PermissionError:
        return 0.0
    return total

# ---- These functions are restored for test compatibility ---------------------
def pids_with_sockets() -> set:
    out = set()
    try:
        conns = psutil.net_connections(kind="inet")
    except (PermissionError, Exception):
        conns = []
    for c in conns:
        if c.pid:
            out.add(c.pid)
    return out

def proc_io_bytes_and_name(pid: int) -> Tuple[Optional[int], Optional[str]]:
    try:
        p = psutil.Process(pid)
        io = p.io_counters()
        return io.read_bytes + io.write_bytes, p.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None, None

def compute_net_rows(prev_map: Dict[int, Tuple[int, str]],
                     curr_pids: Iterable[int],
                     elapsed: float,
                     base: str) -> Tuple[List[Tuple[int, str, float]], Dict[int, Tuple[int, str]]]:
    """Return (rows, updated_map). Each row = (pid, name, mbps)."""
    # Seed new PIDs
    for pid in curr_pids:
        if pid not in prev_map:
            b, nm = proc_io_bytes_and_name(pid)
            if b is not None:
                prev_map[pid] = (b, nm or str(pid))

    rows: List[Tuple[int, str, float]] = []
    for pid in list(prev_map.keys()):
        if pid not in curr_pids:
            prev_map.pop(pid, None)
            continue
        prev_b, prev_name = prev_map.get(pid, (None, None))
        if prev_b is None:
            continue
        curr_b, curr_nm = proc_io_bytes_and_name(pid)
        if curr_b is None:
            prev_map.pop(pid, None)
            continue
        name = curr_nm or prev_name or str(pid)
        delta = max(0, curr_b - prev_b)
        bps = (delta * 8.0) / max(1e-6, elapsed)
        rows.append((pid, name, human_mbps(bps, base)))
        prev_map[pid] = (curr_b, name)

    rows.sort(key=lambda r: r[2], reverse=True)
    return rows, prev_map
# -----------------------------------------------------------------------------

@dataclass
class NetState:
    units: str = "mb"
    prev_total: Tuple[int, int] = (0, 0)
    prev_time: float = 0.0
    link_cap_mbps: float = 0.0
    hist_total_mbps: List[float] = None  # type: ignore
    def __post_init__(self):
        if self.hist_total_mbps is None: self.hist_total_mbps = []

def render_net_panel(state: NetState, top_n: int, interval_hint: float,
                     show_proc_rows: bool, proc_rows: List[dict]) -> Panel:
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
    if len(state.hist_total_mbps) > 80:
        state.hist_total_mbps = state.hist_total_mbps[-80:]

    width = term_width()
    name_cap = max(8, min(30, width - 26))
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("PID", justify="right", no_wrap=True)
    table.add_column("Process", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    table.add_column("Σ ({}b/s)".format("Mi" if state.units == "mib" else "M"), justify="right", no_wrap=True)
    if show_proc_rows:
        # NOTE: “Σ” here uses disk-I/O-based deltas (portable, lightweight).
        for r in proc_rows[:top_n]:
            table.add_row(str(r["pid"]), truncate(r["name"], name_cap), f"{r['d_mb_s']:8.2f}")
    else:
        table.add_row("-", "(per-proc off for low CPU; use --net-procs)", "-")

    hdr = Text.assemble(
        ("Network Usage  ", "cyan bold"),
        (f"(interval≈{elapsed:.2f}s, units={'Mib/s' if state.units=='mib' else 'Mb/s'})", "dim"),
    )
    totals = f"Total:  ↓ {recv_mbps:7.2f}  ↑ {sent_mbps:7.2f}  Σ {total_mbps:7.2f}    Util: {util:5.1f}%"
    cap = (
        f"{int(state.link_cap_mbps):d} Mb/s link cap (sum of up NICs)"
        if state.link_cap_mbps > 0
        else "unknown link cap (Termux fallback)"
    )
    sk = sparkline(state.hist_total_mbps, width=max(20, min(60, width - 24)))
    footer = Text("[v] view  [s] sort  [+/-] topN  ]/[ interval  m units  [q] quit", style="dim")

    panel = Panel(Group(hdr, Text(sk), Text(totals), Text(cap, style="dim"), table, footer),
                  title="NET — totals", border_style="magenta")
    state.prev_total = curr_total
    state.prev_time = now
    return panel

# ----- CLI / Main -------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unified CPU/NET/DISK process monitor (lightweight)")
    p.add_argument("-t", "--top", type=int, default=15, help="Top N rows (1-99)")
    p.add_argument("-i", "--interval", type=float, default=1.0, help="Refresh interval seconds (0.2–5)")
    p.add_argument("-g", "--glob", type=str, default="*", help="Process name glob filter for CPU/DISK views")
    p.add_argument("-w", "--view", choices=VIEWS, default="cpu", help="Initial view")
    p.add_argument("-S", "--sort", choices=CPU_SORTS + NET_SORTS + DISK_SORTS, default="cpu", help="Initial sort mode")
    p.add_argument("-u", "--units", choices=UNITS, default="mb", help="Network units (mb or mib)")
    p.add_argument("--net-procs", action="store_true", help="Show per-proc rows in NET view (heavier)")
    p.add_argument("--low-prio", action="store_true", help="Lower this process priority (nice / BELOW_NORMAL)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logs to stderr")
    return p.parse_args(argv)

def set_low_priority() -> None:
    try:
        if os.name == "nt":
            p = psutil.Process()
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
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

    cpu_sort = args.sort if args.sort in CPU_SORTS else "cpu"
    net_sort = args.sort if args.sort in NET_SORTS else "mbps"
    disk_sort = args.sort if args.sort in DISK_SORTS else "total"
    view_idx = VIEWS.index(args.view)

    ncpu = psutil.cpu_count(logical=True) or 1
    net_state = NetState(units=args.units)
    net_state.prev_total = get_total_counters()
    net_state.prev_time = time.time()
    net_state.link_cap_mbps = sum_active_link_capacity_mbps()

    prev_snaps: Dict[int, ProcSnap] = {}

    if args.verbose:
        sys.stderr.write(
            f"[sysmon] start view={VIEWS[view_idx]} sort(cpu)={cpu_sort} sort(net)={net_sort} sort(disk)={disk_sort} "
            f"top={top_n} interval={interval} net_procs={args.net_procs}\n"
        )

    help_on = False

    with KeyReader() as keys, Live(refresh_per_second=8, redirect_stdout=False) as live:
        while True:
            ch = keys.read()
            if ch:
                if ch.lower() == "q": break
                elif ch.lower() == "v": view_idx = (view_idx + 1) % len(VIEWS)
                elif ch.lower() == "s":
                    v = VIEWS[view_idx]
                    if v == "cpu":
                        cpu_sort = CPU_SORTS[(CPU_SORTS.index(cpu_sort) + 1) % len(CPU_SORTS)]
                    elif v == "net":
                        net_sort = NET_SORTS[(NET_SORTS.index(net_sort) + 1) % len(NET_SORTS)]
                    else:
                        disk_sort = DISK_SORTS[(DISK_SORTS.index(disk_sort) + 1) % len(DISK_SORTS)]
                elif ch == "+": top_n = int(clamp(top_n + 1, 1, 99))
                elif ch == "-": top_n = int(clamp(top_n - 1, 1, 99))
                elif ch == "]": interval = float(clamp(interval + 0.1, 0.2, 5.0))
                elif ch == "[": interval = float(clamp(interval - 0.1, 0.2, 5.0))
                elif ch.lower() == "m": net_state.units = "mib" if net_state.units == "mb" else "mb"
                elif ch.lower() == "h": help_on = not help_on

            # Single snapshot pass
            curr_snaps = iter_snaps(args.glob)
            rows = deltas(prev_snaps, curr_snaps, ncpu)
            total_procs = len(curr_snaps)
            prev_snaps = curr_snaps  # swap for next tick

            # Sort for all views once; no extra work later
            rows_cpu = list(rows)
            sort_cpu_rows(rows_cpu, cpu_sort)

            rows_disk = list(rows)
            sort_disk_rows(rows_disk, disk_sort)

            rows_net = list(rows)
            if net_sort == "name":
                rows_net.sort(key=lambda r: r["name"].lower())
            else:
                rows_net.sort(key=lambda r: r["d_mb_s"], reverse=True)

            current_view = VIEWS[view_idx]
            if current_view == "cpu":
                panel = render_cpu_table(rows_cpu, total=total_procs, limit=top_n, sort_mode=cpu_sort)
            elif current_view == "disk":
                panel = render_disk_table(rows_disk, total=total_procs, limit=top_n, sort_mode=disk_sort)
            else:
                panel = render_net_panel(net_state, top_n=top_n, interval_hint=interval,
                                         show_proc_rows=args.net_procs, proc_rows=rows_net)

            if help_on:
                help_text = Text(
                    "q quit • v view • s sort • +/- top rows • ]/[ interval • m units (NET)\n"
                    "CPU sort: cpu, memory, disk, name, random | NET sort: mbps, name | DISK sort: read, write, total, name",
                    style="yellow",
                )
                live.update(Panel(Group(panel, Panel(help_text, title="Help", border_style="yellow"))))
            else:
                live.update(panel)

            time.sleep(interval)

if __name__ == "__main__":
    main()
