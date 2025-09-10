#!/usr/bin/env python3
"""
TermDash CLI Demos

Visual confirmation demos for TermDash features. Default behavior: do NOT clear
the screen at the end; instead, print a compact plain snapshot so you can see
the final state. Pass --clear to skip the snapshot.

Usage:
    python -m termdash --help

Examples:
    python -m termdash progress --total 50 --interval 0.05
    python -m termdash stats --duration 3
    python -m termdash multistats --processes 6 --duration 4 --proc ytdlp
    python -m termdash threads --threads 6 --duration 4
    python -m termdash seemake --steps 5 --with-bar
"""
from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Tuple

from . import Stat, Line, TermDash
from .progress import ProgressBar
from .seemake import SeemakePrinter
from .simpleboard import SimpleBoard


# ---------------------------------------------------------------------------

def _sleep(sec: float) -> None:
    if sec > 0:
        time.sleep(sec)


def _print_snapshot(title: str, rows: List[Tuple[str, List[Stat]]]) -> None:
    print("\n=== TermDash Demo Snapshot:", title, "===")
    for name, stats in rows:
        line = " | ".join(s.prefix + (s.format_string.format(s.value)) + (s.unit or "") for s in stats)
        print(f"{name:>12}: {line}")


# ------------------------------ PROGRESS -------------------------------------

def demo_progress(args: argparse.Namespace) -> int:
    total = max(1, args.total)
    interval = max(0.0, args.interval)

    if args.plain:
        for i in range(total + 1):
            pct = int(round(100 * i / total))
            inner = int(max(0, args.width - 2) * i / total)
            bar = "[" + "#" * inner + "-" * (max(0, args.width - 2) - inner) + "]" if args.width >= 2 else ""
            if args.no_percent:
                print(f"{pct:3d}% {bar}")
            else:
                print(f"{pct:3d}% {bar} ({i}/{total})")
            _sleep(interval)
        return 0

    pb = ProgressBar("bar", total=total, width=args.width, charset=("ascii" if args.ascii else "block"), show_percent=not args.no_percent)
    td = TermDash(status_line=True, refresh_rate=0.05)

    rows: List[Tuple[str, List[Stat]]] = []

    with td:
        td.add_line("header", Line("header", stats=[Stat("title", "Progress Demo", format_string="{}", color="1;36")], style="header"))
        s_done = Stat("done", 0, prefix="Done: ")
        s_total = Stat("total", total, prefix="Total: ")
        td.add_line("row", Line("row", stats=[s_done, s_total, pb.cell()]))
        rows.append(("row", [s_done, s_total, pb.cell()]))

        for i in range(total + 1):
            pb.set(i)
            td.update_stat("row", "done", i)
            _sleep(interval)

    if not args.clear:
        _print_snapshot("progress", rows)
    return 0


# ------------------------------- STATS ---------------------------------------

def demo_stats(args: argparse.Namespace) -> int:
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)

    if args.plain:
        t0 = time.time()
        done = 0
        total = 100
        while time.time() - t0 < duration:
            done = min(total, done + random.randint(1, 3))
            print(f"Done: {done} | Total: {total}")
            _sleep(update)
        return 0

    board = SimpleBoard(title="Stats Demo")
    pb = ProgressBar("bar", total=100, width=args.width)

    board.add_row("r1",
                  Stat("done", 0, prefix="Done: "),
                  Stat("total", 100, prefix="Total: "))
    pb.bind(current_fn=lambda: board.read_stat("r1", "done"),
            total_fn=lambda: board.read_stat("r1", "total"))
    board.add_row("r2", pb.cell())

    final_done = 0
    with board:
        t0 = time.time()
        done = 0
        while time.time() - t0 < duration and done < 100:
            done = min(100, done + random.randint(1, 3))
            final_done = done
            board.update("r1", "done", done)
            _sleep(update)

    if not args.clear:
        _print_snapshot("stats", [("r1", [Stat("done", final_done, prefix="Done: "), Stat("total", 100, prefix="Total: ")])])
    return 0


# ----------------------------- MULTI-STATS -----------------------------------

@dataclass
class SimProc:
    name: str
    total: int
    done: int = 0
    speed: float = 0.0
    status: str = "queued"


def _proc_profile(kind: str) -> tuple[int, int]:
    if kind == "ytdlp":
        return (1, 6)
    if kind == "copy":
        return (5, 25)
    if kind == "compute":
        return (1, 3)
    return (1, 5)


def demo_multistats(args: argparse.Namespace) -> int:
    n = max(1, args.processes)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)
    kind = args.proc

    procs = [SimProc(name=f"proc-{i+1}", total=random.randint(60, 120)) for i in range(n)]

    if args.plain:
        t0 = time.time()
        while time.time() - t0 < duration and any(p.done < p.total for p in procs):
            for p in procs:
                if p.done >= p.total:
                    p.status = "done"
                    continue
                step = random.randint(*_proc_profile(kind))
                p.done = min(p.total, p.done + step)
                p.speed = 0.5 * p.speed + 0.5 * step / max(update, 1e-6)
                p.status = "downloading" if kind == "ytdlp" else "running"
                print(f"{p.name:>8} | {p.status:12} | {p.done:4}/{p.total:<4} | {p.speed:6.1f} u/s")
            _sleep(update)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)
    rows: List[Tuple[str, List[Stat]]] = []

    with td:
        td.add_line("hdr", Line("hdr", stats=[Stat("title", f"Multi-Stats Demo ({kind})", format_string="{}", color="1;36")], style="header"))

        for p in procs:
            s_status = Stat("status", p.status, prefix="")
            s_done = Stat("done", p.done, prefix="Done: ")
            s_total = Stat("total", p.total, prefix="Total: ")
            pb = ProgressBar("bar", total=p.total, width=args.width)
            pb.bind(current_fn=lambda p=p: p.done, total_fn=lambda p=p: p.total)
            td.add_line(p.name, Line(p.name, stats=[s_status, s_done, s_total, pb.cell()]))
            rows.append((p.name, [s_status, s_done, s_total, pb.cell()]))

        t0 = time.time()
        while time.time() - t0 < duration and any(p.done < p.total for p in procs):
            for p in procs:
                if p.done >= p.total:
                    p.status = "done"
                    td.update_stat(p.name, "status", p.status)
                    continue
                step = random.randint(*_proc_profile(kind))
                p.done = min(p.total, p.done + step)
                p.speed = 0.5 * p.speed + 0.5 * step / max(update, 1e-6)
                p.status = "downloading" if kind == "ytdlp" else "running"
                td.update_stat(p.name, "status", p.status)
                td.update_stat(p.name, "done", p.done)
            _sleep(update)

    if not args.clear:
        _print_snapshot("multistats", rows)
    return 0


# --------------------------- MULTI-THREADED ----------------------------------

def demo_threads(args: argparse.Namespace) -> int:
    """Demonstrate thread-safe updates: each worker thread owns a row."""
    threads = max(1, args.threads)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)

    if args.plain:
        # Plain mode: simulate threaded updates with printed lines.
        t0 = time.time()
        counters = [0] * threads
        totals = [random.randint(60, 120) for _ in range(threads)]
        while time.time() - t0 < duration and any(c < t for c, t in zip(counters, totals)):
            for i in range(threads):
                if counters[i] < totals[i]:
                    counters[i] = min(totals[i], counters[i] + random.randint(1, 5))
                print(f"thr-{i+1:02d}: {counters[i]}/{totals[i]}")
            _sleep(update)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)

    with td:
        td.add_line("hdr", Line("hdr", stats=[Stat("title", "Multi-Threaded Demo", format_string="{}", color="1;36")], style="header"))

        totals = [random.randint(60, 120) for _ in range(threads)]
        for i in range(threads):
            name = f"thr-{i+1:02d}"
            pb = ProgressBar("bar", total=totals[i], width=args.width)
            td.add_line(name, Line(name, stats=[Stat("done", 0, prefix="Done: "), Stat("total", totals[i], prefix="Total: "), pb.cell()]))

        stop_time = time.time() + duration

        def worker(idx: int) -> None:
            name = f"thr-{idx+1:02d}"
            total = totals[idx]
            done = 0
            while time.time() < stop_time and done < total:
                step = random.randint(1, 5)
                done = min(total, done + step)
                td.update_stat(name, "done", done)
                # progress bar cell value is updated indirectly via Stat set (the bar binds when added)
                _sleep(update)

        ts: List[threading.Thread] = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

    # Snapshot omitted; each row is per-thread and visible above.
    return 0


# ------------------------------- SEEMAKE -------------------------------------

def demo_seemake(args: argparse.Namespace) -> int:
    steps = max(1, args.steps)
    kinds = ["scan", "build", "build", "link", "success"]
    kinds = (kinds * ((steps + len(kinds) - 1) // len(kinds)))[:steps]

    if args.plain:
        for i, k in enumerate(kinds, 1):
            pct = int(round(100 * i / steps))
            print(f"[{pct:3d}%] {k.upper()}: step {i}/{steps}")
            _sleep(args.interval)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)
    with td:
        sm = SeemakePrinter(total=steps, td=td, with_bar=args.with_bar, bar_width=args.width, label="Build", out=sys.stdout)
        for i, k in enumerate(kinds, 1):
            msg = {
                "scan": "Scanning dependencies of target demo",
                "build": f"Building CXX object src/file_{i}.o",
                "link": "Linking CXX executable demo",
                "success": "Built target demo",
            }[k]
            sm.step(msg, kind=k)
            _sleep(args.interval)

    return 0


# ------------------------------ ARGPARSE -------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="termdash", description="TermDash CLI demos")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser):
        sp.add_argument("--clear", action="store_true", help="Clear the screen at exit (default: keep a plain snapshot).")
        sp.add_argument("--plain", action="store_true", help="Print plain output without starting TermDash.")
        sp.add_argument("--seed", type=int, default=1234, help="Random seed for repeatable demos.")

    # progress
    sp = sub.add_parser("progress", help="Single progress bar demo.")
    add_common(sp)
    sp.add_argument("--total", "-t", type=int, default=100)
    sp.add_argument("--interval", "-i", type=float, default=0.05)
    sp.add_argument("--width", "-w", type=int, default=28)
    sp.add_argument("--ascii", action="store_true", help="Use ASCII bar instead of Unicode.")
    sp.add_argument("--no-percent", action="store_true", dest="no_percent", help="Hide percent text inside the bar.")
    sp.set_defaults(func=demo_progress)

    # stats
    sp = sub.add_parser("stats", help="Two stats + bound progress bar demo.")
    add_common(sp)
    sp.add_argument("--duration", "-d", type=float, default=4.0)
    sp.add_argument("--update", "-u", type=float, default=0.1, help="Update interval seconds.")
    sp.add_argument("--width", "-w", type=int, default=28)
    sp.set_defaults(func=demo_stats)

    # multistats
    sp = sub.add_parser("multistats", help="Multiple processes with per-row stats.")
    add_common(sp)
    sp.add_argument("--processes", "-p", type=int, default=6)
    sp.add_argument("--proc", choices=["ytdlp", "copy", "compute"], default="ytdlp")
    sp.add_argument("--duration", "-d", type=float, default=5.0)
    sp.add_argument("--update", "-u", type=float, default=0.15)
    sp.add_argument("--width", "-w", type=int, default=26)
    sp.set_defaults(func=demo_multistats)

    # threads
    sp = sub.add_parser("threads", help="Multi-threaded stats demo (each thread updates its own row).")
    add_common(sp)
    sp.add_argument("--threads", "-n", type=int, default=6)
    sp.add_argument("--duration", "-d", type=float, default=5.0)
    sp.add_argument("--update", "-u", type=float, default=0.10)
    sp.add_argument("--width", "-w", type=int, default=26)
    sp.set_defaults(func=demo_threads)

    # seemake
    sp = sub.add_parser("seemake", help="CMake-like build output demo.")
    add_common(sp)
    sp.add_argument("--steps", "-s", type=int, default=5)
    sp.add_argument("--interval", "-i", type=float, default=0.05)
    sp.add_argument("--with-bar", action="store_true")
    sp.add_argument("--width", "-w", type=int, default=24)
    sp.set_defaults(func=demo_seemake)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    random.seed(args.seed)
    return int(bool(args.func(args)))


if __name__ == "__main__":
    raise SystemExit(main())
