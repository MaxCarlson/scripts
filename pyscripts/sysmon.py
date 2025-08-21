#!/usr/bin/env python3
"""
sysmon.py — unified CPU / Memory / Disk / Network TUI for tiny terminals.

Keyboard (while running)
  q          Quit
  v          Toggle view (CPU ↔ NET)
  s          Cycle sort mode for current view
  + / -      Increase / decrease Top-N rows
  ] / [      Increase / decrease refresh interval
  m          Toggle Mb/s vs Mib/s (NET view)
  h          Toggle help overlay

Examples
  python sysmon.py
  python sysmon.py -i 1.5 -t 20
  python sysmon.py -g "vivaldi*"         # filter processes by name (CPU view)
  python sysmon.py -w net                 # start in NET view
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
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import psutil
from rich import box
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# --- Cross-platform non-blocking key polling ---------------------------------
if os.name == "nt":
    import msvcrt

    class KeyReader:
        """Non-blocking single-char reader for Windows (msvcrt)."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> Optional[str]:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                return ch
            return None

else:
    import tty
    import termios

    class KeyReader:
        """Non-blocking single-char reader for POSIX using raw stdin + select."""

        def __enter__(self):
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            try:
                tty.setcbreak(self.fd)  # immediate char, no Enter
                self.ok = sys.stdin.isatty()
            except Exception:
                self.ok = False
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
            except Exception:
                pass
            return False

        def read(self) -> Optional[str]:
            if not getattr(self, "ok", False):
                return None
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                ch = sys.stdin.read(1)
                return ch
            return None


# --- Constants ----------------------------------------------------------------
CPU_SORTS = ["cpu", "memory", "disk", "name", "random"]
NET_SORTS = ["mbps", "name"]  # applied to per-proc list
UNITS = ["mb", "mib"]  # network units

# --- Helpers ------------------------------------------------------------------
def term_width() -> int:
    return shutil.get_terminal_size((100, 24)).columns

def clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)

def truncate(s: str, width: int) -> str:
    if width <= 1:
        return ""
    return s if len(s) <= width else (s[: max(0, width - 1)] + "…")

def human_mbps(bits_per_sec: float, base: str) -> float:
    denom = 1_000_000 if base == "mb" else (1 << 20)
    return bits_per_sec / denom

def sparkline(values: Sequence[float], width: int = 30) -> str:
    """Render a tiny sparkline (unicode blocks, 8 levels)."""
    if width <= 0 or not values:
        return ""
    # downsample to width
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

# --- CPU sampling --------------------------------------------------------------
def iter_matched_processes(glob_pattern: str) -> Iterable[psutil.Process]:
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info["name"] or "").lower()
            if fnmatch.fnmatch(name, glob_pattern.lower()):
                yield p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

def sample_cpu_stats(processes: Iterable[psutil.Process], sample_ms: int) -> List[dict]:
    """Return list of dicts with cpu_pct, mem_mb, read_mb, write_mb, disk_mb."""
    entries = []
    for p in processes:
        try:
            p.cpu_percent(None)  # prime
            io0 = p.io_counters()
            entries.append((p, io0))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(sample_ms / 1000.0)

    rows = []
    for p, io0 in entries:
        try:
            cpu = p.cpu_percent(None)
            mem = p.memory_info().rss / 1024**2
            io1 = p.io_counters()
            read_mb = (io1.read_bytes - io0.read_bytes) / 1024**2
            write_mb = (io1.write_bytes - io0.write_bytes) / 1024**2
            rows.append(
                {
                    "pid": p.pid,
                    "name": p.name(),
                    "cpu_pct": cpu,
                    "mem_mb": mem,
                    "read_mb": read_mb,
                    "write_mb": write_mb,
                    "disk_mb": read_mb + write_mb,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows

def sort_cpu_rows(rows: List[dict], mode: str) -> None:
    if mode == "cpu":
        rows.sort(key=lambda r: r["cpu_pct"], reverse=True)
    elif mode == "memory":
        rows.sort(key=lambda r: r["mem_mb"], reverse=True)
    elif mode == "disk":
        rows.sort(key=lambda r: r["disk_mb"], reverse=True)
    elif mode == "name":
        rows.sort(key=lambda r: r["name"].lower())
    else:
        random.shuffle(rows)

def cpu_columns_for_width(width: int) -> List[str]:
    """Decide which columns to show on small screens."""
    # Start with most important on the left; hide as it gets tight.
    cols = ["PID", "Name", "CPU %", "Mem(MB)", "RΔ(MB)", "WΔ(MB)", "DΔ(MB)"]
    if width < 65:
        return ["PID", "Name", "CPU %"]
    if width < 80:
        return ["PID", "Name", "CPU %", "Mem(MB)"]
    if width < 95:
        return ["PID", "Name", "CPU %", "Mem(MB)", "DΔ(MB)"]
    if width < 110:
        return ["PID", "Name", "CPU %", "Mem(MB)", "RΔ(MB)", "WΔ(MB)"]
    return cols

def render_cpu_table(rows: List[dict], total: int, limit: int, sort_mode: str) -> Panel:
    width = term_width()
    cols = cpu_columns_for_width(width)
    name_cap = max(8, min(32, width - 40))  # prevent name-driven stretch

    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=True)
    if "PID" in cols:
        table.add_column("PID", justify="right", no_wrap=True)
    if "Name" in cols:
        table.add_column("Name", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    if "CPU %" in cols:
        table.add_column("CPU %", justify="right", no_wrap=True)
    if "Mem(MB)" in cols:
        table.add_column("Mem(MB)", justify="right", no_wrap=True)
    if "RΔ(MB)" in cols:
        table.add_column("RΔ(MB)", justify="right", no_wrap=True)
    if "WΔ(MB)" in cols:
        table.add_column("WΔ(MB)", justify="right", no_wrap=True)
    if "DΔ(MB)" in cols:
        table.add_column("DΔ(MB)", justify="right", no_wrap=True)

    for r in rows[:limit]:
        vals = []
        if "PID" in cols:
            vals.append(str(r["pid"]))
        if "Name" in cols:
            vals.append(truncate(r["name"], name_cap))
        if "CPU %" in cols:
            vals.append(f"{r['cpu_pct']:.2f}")
        if "Mem(MB)" in cols:
            vals.append(f"{r['mem_mb']:.1f}")
        if "RΔ(MB)" in cols:
            vals.append(f"{r['read_mb']:.2f}")
        if "WΔ(MB)" in cols:
            vals.append(f"{r['write_mb']:.2f}")
        if "DΔ(MB)" in cols:
            vals.append(f"{r['disk_mb']:.2f}")
        table.add_row(*vals)

    cap = f"Showing {min(limit, len(rows))} of {total} procs   |   mode: {sort_mode}"
    footer = Text("[v] view  [s] sort  [+/-] topN  []/[[] interval  [q] quit", style="dim")
    return Panel(Group(table, Text(cap, style="dim"), footer), title="CPU / Memory / Disk", border_style="cyan")


# --- Network sampling (with Termux-safe fallbacks) ----------------------------
def _sysfs_sum_net_bytes() -> Optional[Tuple[int, int]]:
    """
    Fallback for Android/Termux where /proc/net/dev is restricted.
    Sums rx_bytes/tx_bytes from /sys/class/net/*/statistics/.
    Returns (bytes_sent, bytes_recv) or None if not available.
    """
    base = "/sys/class/net"
    try:
        if not os.path.isdir(base):
            return None
        total_rx = 0
        total_tx = 0
        for iface in os.listdir(base):
            # Skip loopback and down/virtual interfaces if desired
            if iface == "lo":
                continue
            stats_dir = os.path.join(base, iface, "statistics")
            rx_path = os.path.join(stats_dir, "rx_bytes")
            tx_path = os.path.join(stats_dir, "tx_bytes")
            try:
                with open(rx_path, "r") as fr:
                    rx = int(fr.read().strip())
                with open(tx_path, "r") as ft:
                    tx = int(ft.read().strip())
                total_rx += rx
                total_tx += tx
            except (FileNotFoundError, PermissionError, ValueError):
                continue
        return (total_tx, total_rx)
    except Exception:
        return None

def get_total_counters() -> Tuple[int, int]:
    """
    Return (bytes_sent, bytes_recv) for the whole system.
    Uses psutil when possible, otherwise falls back to /sys/class/net.
    """
    try:
        c = psutil.net_io_counters(pernic=False)
        return c.bytes_sent, c.bytes_recv
    except PermissionError:
        alt = _sysfs_sum_net_bytes()
        if alt is not None:
            return alt
        # final safe default
        return (0, 0)

def sum_active_link_capacity_mbps() -> float:
    """
    Sum NIC speeds in Mbps. On Android/Termux this may be unavailable;
    return 0.0 if permission denied or unknown.
    """
    total = 0.0
    try:
        for _, st in psutil.net_if_stats().items():
            if st.isup and st.speed and st.speed > 0:
                total += float(st.speed)
    except PermissionError:
        return 0.0
    return total

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

@dataclass
class NetState:
    units: str = "mb"
    prev_total: Tuple[int, int] = (0, 0)
    prev_time: float = 0.0
    link_cap_mbps: float = 0.0
    hist_total_mbps: List[float] = field(default_factory=list)
    prev_proc_bytes: Dict[int, Tuple[int, str]] = field(default_factory=dict)
    sort_mode: str = "mbps"

    def init_baseline(self) -> None:
        self.prev_total = get_total_counters()
        self.prev_time = time.time()
        self.link_cap_mbps = sum_active_link_capacity_mbps()
        self.prev_proc_bytes.clear()
        # If socket listing is blocked, per-proc rows will be empty; totals still work.
        for pid in pids_with_sockets():
            b, nm = proc_io_bytes_and_name(pid)
            if b is not None:
                self.prev_proc_bytes[pid] = (b, nm or str(pid))

def render_net_panel(state: NetState, top_n: int, interval_hint: float) -> Panel:
    now = time.time()
    elapsed = now - state.prev_time if state.prev_time else interval_hint
    if elapsed <= 0:
        elapsed = interval_hint

    curr_total = get_total_counters()
    sent_bps = (curr_total[0] - state.prev_total[0]) * 8.0 / elapsed
    recv_bps = (curr_total[1] - state.prev_total[1]) * 8.0 / elapsed
    total_bps = sent_bps + recv_bps

    sent_mbps = human_mbps(sent_bps, state.units)
    recv_mbps = human_mbps(recv_bps, state.units)
    total_mbps = human_mbps(total_bps, state.units)
    util = (total_mbps / state.link_cap_mbps * 100.0) if state.link_cap_mbps > 0 else 0.0

    state.hist_total_mbps.append(total_mbps)
    if len(state.hist_total_mbps) > 80:
        state.hist_total_mbps = state.hist_total_mbps[-80:]

    # Per-proc rows (may be empty on Termux due to socket restrictions)
    rows, state.prev_proc_bytes = compute_net_rows(
        state.prev_proc_bytes, pids_with_sockets(), elapsed, state.units
    )
    if state.sort_mode == "name":
        rows.sort(key=lambda x: x[1].lower())

    # Table
    width = term_width()
    name_cap = max(8, min(30, width - 26))
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("PID", justify="right", no_wrap=True)
    table.add_column("Process", justify="left", no_wrap=True, overflow="ellipsis", width=name_cap)
    table.add_column("Σ ({}b/s)".format("Mi" if state.units == "mib" else "M"), justify="right", no_wrap=True)
    for pid, name, mbps in rows[:top_n]:
        table.add_row(str(pid), truncate(name, name_cap), f"{mbps:8.2f}")

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

    rendered = Group(hdr, Text(sk), Text(totals), Text(cap, style="dim"), table, footer)
    panel = Panel(rendered, title=f"NET — sort: {state.sort_mode}", border_style="magenta")
    # advance baseline
    state.prev_total = curr_total
    state.prev_time = now
    return panel


# --- Main ---------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unified CPU/NET process monitor")
    p.add_argument("-t", "--top", type=int, default=15, help="Top N rows (1-99)")
    p.add_argument("-i", "--interval", type=float, default=1.0, help="Refresh interval seconds (0.2–5)")
    p.add_argument("-a", "--analysis_ms", type=int, default=800, help="CPU sample window in ms (CPU view)")
    p.add_argument("-g", "--glob", type=str, default="*", help="Process name glob filter for CPU view")
    p.add_argument("-w", "--view", choices=["cpu", "net"], default="cpu", help="Initial view")
    p.add_argument("-S", "--sort", choices=CPU_SORTS + NET_SORTS, default="cpu", help="Initial sort mode")
    p.add_argument("-u", "--units", choices=UNITS, default="mb", help="Network units (mb or mib)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logs to stderr")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    top_n = int(clamp(args.top, 1, 99))
    interval = float(clamp(args.interval, 0.2, 5.0))
    cpu_sort = args.sort if args.sort in CPU_SORTS else "cpu"
    net_sort = args.sort if args.sort in NET_SORTS else "mbps"
    view = args.view

    if args.verbose:
        sys.stderr.write(
            f"[sysmon] start view={view} sort(cpu)={cpu_sort} sort(net)={net_sort} top={top_n} interval={interval}\n"
        )

    net_state = NetState(units=args.units, sort_mode=net_sort)
    net_state.init_baseline()

    help_on = False

    with KeyReader() as keys, Live(refresh_per_second=30, redirect_stdout=False) as live:
        while True:
            # Handle input
            ch = keys.read()
            if ch:
                if ch.lower() == "q":
                    break
                elif ch.lower() == "v":
                    view = "net" if view == "cpu" else "cpu"
                elif ch.lower() == "s":
                    if view == "cpu":
                        idx = (CPU_SORTS.index(cpu_sort) + 1) % len(CPU_SORTS)
                        cpu_sort = CPU_SORTS[idx]
                    else:
                        idx = (NET_SORTS.index(net_state.sort_mode) + 1) % len(NET_SORTS)
                        net_state.sort_mode = NET_SORTS[idx]
                elif ch == "+":
                    top_n = int(clamp(top_n + 1, 1, 99))
                elif ch == "-":
                    top_n = int(clamp(top_n - 1, 1, 99))
                elif ch == "]":
                    interval = float(clamp(interval + 0.1, 0.2, 5.0))
                elif ch == "[":
                    interval = float(clamp(interval - 0.1, 0.2, 5.0))
                elif ch.lower() == "m":
                    net_state.units = "mib" if net_state.units == "mb" else "mb"
                elif ch.lower() == "h":
                    help_on = not help_on

            # Render current view
            if view == "cpu":
                procs = list(
                    iter_matched_processes(
                        args.glob if any(c in args.glob for c in "*?[]") else f"*{args.glob}*"
                    )
                )
                rows = sample_cpu_stats(procs, args.analysis_ms)
                sort_cpu_rows(rows, cpu_sort)
                panel = render_cpu_table(rows, total=len(procs), limit=top_n, sort_mode=cpu_sort)
            else:
                panel = render_net_panel(net_state, top_n=top_n, interval_hint=interval)

            if help_on:
                help_text = Text(
                    "q quit • v view • s sort • +/- top rows • ]/[ interval • m units (NET)\n"
                    "CPU sort: cpu, memory, disk, name, random   |   NET sort: mbps, name",
                    style="yellow",
                )
                live.update(Panel(Group(panel, Panel(help_text, title="Help", border_style="yellow"))))
            else:
                live.update(panel)

            # pacing
            time.sleep(interval)

if __name__ == "__main__":
    main()
