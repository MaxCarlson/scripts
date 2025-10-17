#!/usr/bin/env python3
from __future__ import annotations

import curses
import time
from typing import Deque, List
from collections import deque

from .probes import (
    CPUStats,
    GPUStats,
    ProcSampler,
    probe_cpu,
    probe_disk,
    probe_gpu,
    probe_mem,
    probe_net,
)

try:
    import plotille  # type: ignore
except Exception:  # pragma: no cover
    plotille = None


def _sparkline(values: List[float], width: int = 30, lo: float = 0.0, hi: float = 100.0) -> str:
    """
    Render a compact sparkline (1-line) from recent values.
    Uses plotille when available; otherwise a simple ASCII bar of the last value.
    """
    width = max(10, width)
    if not values:
        return "[" + "-" * (min(20, width) - 2) + "]"

    if not plotille or len(values) < 2:
        last = values[-1]
        filled = int((last - lo) / max(1e-6, (hi - lo)) * min(20, width - 2))
        filled = max(0, min(min(20, width - 2), filled))
        return "[" + "#" * filled + "-" * (min(20, width - 2) - filled) + "]"

    # Downsample or pad to width points
    if len(values) > width:
        step = len(values) / width
        vals = [values[int(i * step)] for i in range(width)]
    else:
        vals = values + [values[-1]] * (width - len(values))

    fig = plotille.Figure()
    fig.width = width
    fig.height = 6
    fig.set_x_limits(min_=0, max_=len(vals) - 1)
    fig.set_y_limits(min_=lo, max_=hi)
    fig.color_mode = None
    fig.register_label_formatter(float, lambda v, p: "")
    fig.plot(range(len(vals)), vals)
    lines = fig.show().splitlines()
    return lines[-1] if lines else ""


class UIState:
    def __init__(self, topn: int, refresh: float, start_mode: str) -> None:
        self.mode = start_mode  # "overview" | "cpu" | "procs"
        self.sort_mode = "cpu"  # "cpu" | "avg10" | "avg60" | "mem"
        self.topn = topn
        self.refresh = max(0.2, refresh)

        self.cpu_hist: Deque[float] = deque(maxlen=240)
        self.mem_hist: Deque[float] = deque(maxlen=240)
        self.gpu_hist: Deque[float] = deque(maxlen=240)


def _fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    f = float(n)
    for u in units:
        if f < 1024.0:
            return f"{f:0.1f}{u}"
        f /= 1024.0
    return f"{f:0.1f}EB"


def _draw_header(stdscr, width: int, title: str) -> None:
    stdscr.attron(curses.A_BOLD)
    stdscr.addnstr(0, 1, title, width - 2)
    stdscr.attroff(curses.A_BOLD)
    stdscr.hline(1, 0, curses.ACS_HLINE, width)


def _draw_footer(stdscr, height: int, width: int, state: UIState) -> None:
    stdscr.hline(height - 2, 0, curses.ACS_HLINE, width)
    hints = (
        "[Tab] Modes  [O]verview  [C]PU  [P]rocs   "
        "Sort: [1]CPU [2]Avg10s [3]Avg60s [4]Mem   "
        "[Q]uit"
    )
    stdscr.addnstr(height - 1, 1, hints, width - 2)


def _draw_overview(stdscr, height: int, width: int, state: UIState, sampler: ProcSampler) -> None:
    row = 2
    col = 2
    inner_w = max(20, width - 4)

    cpu: CPUStats = probe_cpu()
    mem = probe_mem()
    net = probe_net()
    disk = probe_disk()
    gpu: GPUStats = probe_gpu()

    state.cpu_hist.append(cpu.avg_percent or 0.0)
    state.mem_hist.append(mem.percent or 0.0)
    state.gpu_hist.append(gpu.percent if gpu.percent is not None else 0.0)

    stdscr.addnstr(row, col, f"CPU  {cpu.avg_percent:5.1f}%  freq: {cpu.freq_current_mhz or 0.0:0.0f} MHz", inner_w)
    row += 1
    stdscr.addnstr(row, col, _sparkline(list(state.cpu_hist), width=min(50, inner_w)), inner_w)
    row += 1

    stdscr.addnstr(row, col, f"MEM  {mem.percent:5.1f}%  used: {_fmt_bytes(mem.used)}/{_fmt_bytes(mem.total)}", inner_w)
    row += 1
    stdscr.addnstr(row, col, _sparkline(list(state.mem_hist), width=min(50, inner_w)), inner_w)
    row += 1

    gpu_txt = "N/A" if gpu.percent is None else f"{gpu.percent:5.1f}%"
    freq_txt = "" if gpu.freq_mhz is None else f"  freq: {gpu.freq_mhz:0.0f} MHz"
    model_txt = f"  ({gpu.model})" if gpu.model else ""
    stdscr.addnstr(row, col, f"GPU  {gpu_txt}{freq_txt}{model_txt}", inner_w)
    row += 1
    stdscr.addnstr(row, col, _sparkline(list(state.gpu_hist), width=min(50, inner_w)), inner_w)
    row += 1

    stdscr.addnstr(row, col, f"LOAD 1/5/15: {cpu.loadavg_1:0.2f} {cpu.loadavg_5:0.2f} {cpu.loadavg_15:0.2f}", inner_w)
    row += 1
    stdscr.addnstr(row, col, f"NET  sent/recv: {_fmt_bytes(net.bytes_sent)} / {_fmt_bytes(net.bytes_recv)}", inner_w)
    row += 1
    stdscr.addnstr(row, col, f"DISK r/w: {_fmt_bytes(disk.read_bytes)} / {_fmt_bytes(disk.write_bytes)}", inner_w)
    row += 2

    sampler.sample()
    prows = sampler.topn(state.topn, sort_mode=state.sort_mode)
    stdscr.attron(curses.A_BOLD)
    stdscr.addnstr(row, col, f"Top {state.topn} processes (sort: {state.sort_mode})", inner_w)
    stdscr.attroff(curses.A_BOLD)
    row += 1
    stdscr.addnstr(row, col, f"{'PID':>6}  {'CPU%':>6} {'10s%':>6} {'60s%':>6} {'RSS':>8}  NAME", inner_w)
    row += 1
    for pr in prows:
        line = f"{pr.pid:6d}  {pr.cpu:6.1f} {pr.cpu_avg_10s:6.1f} {pr.cpu_avg_60s:6.1f} {_fmt_bytes(pr.mem_rss):>8}  {pr.name}"
        stdscr.addnstr(row, col, line, inner_w)
        row += 1


def _draw_cpu(stdscr, height: int, width: int, state: UIState, sampler: ProcSampler) -> None:
    row = 2
    col = 2
    inner_w = max(20, width - 4)

    cpu = probe_cpu()
    state.cpu_hist.append(cpu.avg_percent or 0.0)

    stdscr.addnstr(row, col, f"CPU avg: {cpu.avg_percent:5.1f}%  load: {cpu.loadavg_1:0.2f}/{cpu.loadavg_5:0.2f}/{cpu.loadavg_15:0.2f}", inner_w)
    row += 1
    stdscr.addnstr(row, col, _sparkline(list(state.cpu_hist), width=min(60, inner_w)), inner_w)
    row += 1

    # Per-core rows
    if cpu.per_core_percent:
        for idx, val in enumerate(cpu.per_core_percent):
            bar = _sparkline([val], width=20)
            stdscr.addnstr(row, col, f"cpu{idx:02d}: {val:5.1f}% {bar}", inner_w)
            row += 1
            if row >= height - 8:
                break

    # Bottom: process slice
    sampler.sample()
    prows = sampler.topn(state.topn, sort_mode=state.sort_mode)
    stdscr.attron(curses.A_BOLD)
    stdscr.addnstr(row, col, f"Top {state.topn} by {state.sort_mode}", inner_w)
    stdscr.attroff(curses.A_BOLD)
    row += 1
    stdscr.addnstr(row, col, f"{'PID':>6}  {'CPU%':>6} {'10s%':>6} {'60s%':>6} {'RSS':>8}  NAME", inner_w)
    row += 1
    for pr in prows:
        line = f"{pr.pid:6d}  {pr.cpu:6.1f} {pr.cpu_avg_10s:6.1f} {pr.cpu_avg_60s:6.1f} {_fmt_bytes(pr.mem_rss):>8}  {pr.name}"
        stdscr.addnstr(row, col, line, inner_w)
        row += 1
        if row >= height - 3:
            break


def _draw_procs(stdscr, height: int, width: int, state: UIState, sampler: ProcSampler) -> None:
    row = 2
    col = 2
    inner_w = max(20, width - 4)

    sampler.sample()
    prows = sampler.topn(max(state.topn, height - 8), sort_mode=state.sort_mode)

    stdscr.attron(curses.A_BOLD)
    stdscr.addnstr(row, col, f"Processes (sort: {state.sort_mode})", inner_w)
    stdscr.attroff(curses.A_BOLD)
    row += 1
    stdscr.addnstr(row, col, f"{'PID':>6}  {'CPU%':>6} {'10s%':>6} {'60s%':>6} {'RSS':>8}  NAME", inner_w)
    row += 1

    for pr in prows:
        line = f"{pr.pid:6d}  {pr.cpu:6.1f} {pr.cpu_avg_10s:6.1f} {pr.cpu_avg_60s:6.1f} {_fmt_bytes(pr.mem_rss):>8}  {pr.name}"
        stdscr.addnstr(row, col, line, inner_w)
        row += 1
        if row >= height - 3:
            break


def run_curses(topn: int, refresh: float, start_mode: str = "overview") -> None:
    """
    Start the curses UI.
    """
    state = UIState(topn=topn, refresh=refresh, start_mode=start_mode)
    sampler = ProcSampler()

    def _loop(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.keypad(True)

        last_draw = 0.0
        while True:
            h, w = stdscr.getmaxyx()
            now = time.time()
            if now - last_draw >= state.refresh:
                stdscr.erase()
                _draw_header(stdscr, w, f"phonemon | mode: {state.mode}")
                if state.mode == "overview":
                    _draw_overview(stdscr, h, w, state, sampler)
                elif state.mode == "cpu":
                    _draw_cpu(stdscr, h, w, state, sampler)
                else:
                    _draw_procs(stdscr, h, w, state, sampler)
                _draw_footer(stdscr, h, w, state)
                stdscr.refresh()
                last_draw = now

            try:
                ch = stdscr.getch()
            except Exception:
                ch = -1

            if ch == -1:
                time.sleep(0.02)
                continue

            c = chr(ch).lower() if 0 <= ch < 256 else ""
            if c == "q":
                break
            elif ch == 9:  # Tab
                state.mode = {"overview": "cpu", "cpu": "procs", "procs": "overview"}[state.mode]
            elif c == "o":
                state.mode = "overview"
            elif c == "c":
                state.mode = "cpu"
            elif c == "p":
                state.mode = "procs"
            elif c == "1":
                state.sort_mode = "cpu"
            elif c == "2":
                state.sort_mode = "avg10"
            elif c == "3":
                state.sort_mode = "avg60"
            elif c == "4":
                state.sort_mode = "mem"

    curses.wrapper(_loop)
