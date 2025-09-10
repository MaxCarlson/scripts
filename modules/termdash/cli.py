#!/usr/bin/env python3
"""
TermDash CLI Demos

Visual confirmation demos for TermDash features.

Defaults:
- Do NOT clear the screen at exit; instead, print a compact plain snapshot.
- Multistats/threads show NO per-row bars by default.
- Headers are off by default.

Quick examples:
    termdash progress -t 50 -i 0.04
    termdash stats -d 3 -b
    termdash multistats -r 6 -d 5 --proc ytdlp -b -H -B
    termdash threads -n 6 -d 4 -b -H -B
    termdash seemake -s 40 -i 0.08 -B
"""
from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Tuple

from . import Stat, Line, TermDash
from .progress import ProgressBar
from .seemake import SeemakePrinter
from .simpleboard import SimpleBoard


# ---------------------------------------------------------------------------
# Helpers

def _sleep(sec: float) -> None:
    if sec > 0:
        time.sleep(sec)


def _print_snapshot(title: str, rows: List[Tuple[str, List[Stat]]]) -> None:
    """Plain, copyable snapshot of the final rows."""
    print("\n=== TermDash Demo Snapshot:", title, "===")
    for name, stats in rows:
        parts = []
        for s in stats:
            try:
                parts.append(s.prefix + (s.format_string.format(s.value)) + (s.unit or ""))
            except Exception:
                # if a bound widget uses a dynamic render, just show the name
                parts.append(f"<{s.name}>")
        print(f"{name:>12}: " + " | ".join(parts))


def _add_header(td: TermDash, name: str, text: str, with_bar: bool = False,
                total_fn: Optional[Callable[[], float]] = None,
                current_fn: Optional[Callable[[], float]] = None,
                bar_width: int = 28) -> Optional[ProgressBar]:
    td.add_line(name, Line(name, stats=[Stat("title", text, format_string="{}", color="1;36")], style="header"))
    if with_bar and total_fn and current_fn:
        pb = ProgressBar(f"{name}:bar", total=1, width=bar_width, charset="block", show_percent=True)
        pb.bind(current_fn=current_fn, total_fn=total_fn)
        td.add_line(f"{name}:bar", Line(f"{name}:bar", stats=[pb.cell()]))
        return pb
    return None


# ---------------------------------------------------------------------------
# PROGRESS

def demo_progress(args: argparse.Namespace) -> int:
    total = max(1, args.total)
    interval = max(0.0, args.interval)

    if args.plain:
        for i in range(total + 1):
            pct = int(round(100 * i / total))
            inner = int(max(0, args.width - 2) * i / total)
            bar = "[" + "#" * inner + "-" * (max(0, args.width - 2) - inner) + "]" if args.width >= 2 else ""
            out = f"{pct:3d}% {bar}" if args.no_percent else f"{pct:3d}% {bar} ({i}/{total})"
            print(out)
            _sleep(interval)
        return 0

    # Bind the bar to the live values so it cannot visually "complete" early.
    done_val = {"v": 0}

    pb = ProgressBar("bar", total=total, width=args.width,
                     charset=("ascii" if args.ascii else "block"),
                     show_percent=not args.no_percent)
    pb.bind(current_fn=lambda: done_val["v"], total_fn=lambda: total)

    td = TermDash(status_line=True, refresh_rate=0.05)
    rows: List[Tuple[str, List[Stat]]] = []

    with td:
        _add_header(td, "header", "Progress Demo")
        s_done = Stat("done", 0, prefix="Done: ")
        s_total = Stat("total", total, prefix="Total: ")
        td.add_line("row", Line("row", stats=[s_done, s_total]))
        if args.bars:
            td.add_line("row:bar", Line("row:bar", stats=[pb.cell()]))
            rows.append(("row:bar", [pb.cell()]))

        rows.append(("row", [s_done, s_total]))
        for i in range(total + 1):
            done_val["v"] = i
            td.update_stat("row", "done", i)
            _sleep(interval)

    if not args.clear:
        _print_snapshot("progress", rows)
    return 0


# ---------------------------------------------------------------------------
# STATS (single row that mirrors one row of multistats)

def _extras_for_row(k: int) -> List[Stat]:
    """Generate a rotating set of demo stats (rate/eta/errs)."""
    # It’s a demo; light simulation.
    choices = [
        Stat("rate", 0.0, prefix="Rate: ", format_string="{:.1f}", unit="u/s"),
        Stat("eta",  "--", prefix="ETA: "),
        Stat("errs", 0,    prefix="Errs: "),
    ]
    return choices[:k]


def demo_stats(args: argparse.Namespace) -> int:
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)
    total = max(1, args.total)

    if args.plain:
        t0 = time.time()
        done = 0
        while time.time() - t0 < duration and done < total:
            done = min(total, done + random.randint(1, 3))
            print(f"Done: {done} | Total: {total}")
            _sleep(update)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)
    rows: List[Tuple[str, List[Stat]]] = []
    done_val = {"v": 0}

    with td:
        if args.header:
            _add_header(
                td, "hdr", "Stats Demo",
                with_bar=args.header_bar,
                total_fn=lambda: total,
                current_fn=lambda: done_val["v"],
                bar_width=args.width,
            )

        # Row stats
        stats_cells: List[Stat] = [Stat("done", 0, prefix="Done: "), Stat("total", total, prefix="Total: ")]
        stats_cells += _extras_for_row(args.extra_stats)
        td.add_line("row", Line("row", stats=stats_cells))
        rows.append(("row", stats_cells))

        # Optional row bar (placed BELOW the row, as requested)
        if args.bars:
            pb = ProgressBar("bar", total=1, width=args.width)
            pb.bind(current_fn=lambda: done_val["v"], total_fn=lambda: total)
            td.add_line("row:bar", Line("row:bar", stats=[pb.cell()]))
            rows.append(("row:bar", [pb.cell()]))

        # Drive updates
        t0 = time.time()
        while time.time() - t0 < duration and done_val["v"] < total:
            inc = random.randint(1, 3)
            done_val["v"] = min(total, done_val["v"] + inc)
            td.update_stat("row", "done", done_val["v"])
            # Update demo extras
            if args.extra_stats > 0:
                rate = inc / max(update, 1e-6)
                td.update_stat("row", "rate", rate)
                remain = max(0, total - done_val["v"])
                eta = f"{int(remain / max(rate, 1e-6))}s" if rate > 0 else "--"
                if args.extra_stats >= 2:
                    td.update_stat("row", "eta", eta)
                if args.extra_stats >= 3:
                    if random.random() < 0.05:
                        td.update_stat("row", "errs", random.randint(0, 2))
            _sleep(update)

    if not args.clear:
        _print_snapshot("stats", rows)
    return 0


# ---------------------------------------------------------------------------
# MULTI-STATS

@dataclass
class SimProc:
    name: str
    total: int
    done: int = 0
    status: str = "queued"
    rate: float = 0.0
    errs: int = 0


def _proc_profile(kind: str) -> tuple[int, int]:
    if kind == "ytdlp":
        return (1, 6)
    if kind == "copy":
        return (5, 25)
    if kind == "compute":
        return (1, 3)
    return (1, 5)


def demo_multistats(args: argparse.Namespace) -> int:
    n = max(1, args.rows or args.processes)
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
                p.rate = 0.6 * p.rate + 0.4 * (step / max(update, 1e-6))
                p.status = "downloading" if kind == "ytdlp" else "running"
                print(f"{p.name:>8} | {p.status:12} | {p.done:4}/{p.total:<4} | {p.rate:6.1f} u/s")
            _sleep(update)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)
    rows: List[Tuple[str, List[Stat]]] = []

    def total_all() -> float:
        return float(sum(p.total for p in procs))

    def done_all() -> float:
        return float(sum(p.done for p in procs))

    with td:
        if args.header:
            _add_header(
                td, "hdr", f"Multi-Stats Demo ({kind})",
                with_bar=args.header_bar,
                total_fn=total_all,
                current_fn=done_all,
                bar_width=args.width,
            )

        # Build stat rows (+ optional bar rows below each)
        for p in procs:
            s_status = Stat("status", p.status)
            s_done = Stat("done", p.done, prefix="Done: ")
            s_total = Stat("total", p.total, prefix="Total: ")
            cells = [s_status, s_done, s_total]
            if args.extra_stats >= 1:
                cells.append(Stat("rate", 0.0, prefix="Rate: ", format_string="{:.1f}", unit="u/s"))
            if args.extra_stats >= 2:
                cells.append(Stat("errs", 0, prefix="Errs: "))
            td.add_line(p.name, Line(p.name, stats=cells))
            rows.append((p.name, cells))

            if args.bars:
                pb = ProgressBar(f"{p.name}:bar", total=1, width=args.width)
                pb.bind(current_fn=lambda p=p: p.done, total_fn=lambda p=p: p.total)
                td.add_line(f"{p.name}:bar", Line(f"{p.name}:bar", stats=[pb.cell()]))
                rows.append((f"{p.name}:bar", [pb.cell()]))

        # Drive updates
        t0 = time.time()
        while time.time() - t0 < duration and any(p.done < p.total for p in procs):
            for p in procs:
                if p.done >= p.total:
                    if p.status != "done":
                        p.status = "done"
                        td.update_stat(p.name, "status", p.status)
                    continue
                step = random.randint(*_proc_profile(kind))
                p.done = min(p.total, p.done + step)
                p.rate = 0.6 * p.rate + 0.4 * (step / max(update, 1e-6))
                p.status = "downloading" if kind == "ytdlp" else "running"
                td.update_stat(p.name, "status", p.status)
                td.update_stat(p.name, "done", p.done)
                if args.extra_stats >= 1:
                    td.update_stat(p.name, "rate", p.rate)
                if args.extra_stats >= 2 and random.random() < 0.03:
                    p.errs += 1
                    td.update_stat(p.name, "errs", p.errs)
            _sleep(update)

    if not args.clear:
        _print_snapshot("multistats", rows)
    return 0


# ---------------------------------------------------------------------------
# MULTI-THREADED

def demo_threads(args: argparse.Namespace) -> int:
    """Each worker thread owns a row; optional per-row bars below; header optional."""
    threads = max(1, args.threads)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)

    if args.plain:
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
    totals = [random.randint(60, 120) for _ in range(threads)]
    dones = [0 for _ in range(threads)]

    def total_all() -> float:
        return float(sum(totals))

    def done_all() -> float:
        return float(sum(dones))

    with td:
        if args.header:
            _add_header(
                td, "hdr", "Multi-Threaded Demo",
                with_bar=args.header_bar,
                total_fn=total_all,
                current_fn=done_all,
                bar_width=args.width,
            )

        for i in range(threads):
            name = f"thr-{i+1:02d}"
            cells = [Stat("done", 0, prefix="Done: "), Stat("total", totals[i], prefix="Total: ")]
            if args.extra_stats >= 1:
                cells.append(Stat("rate", 0.0, prefix="Rate: ", format_string="{:.1f}", unit="u/s"))
            td.add_line(name, Line(name, stats=cells))

            if args.bars:
                pb = ProgressBar(f"{name}:bar", total=1, width=args.width)
                pb.bind(current_fn=lambda i=i: dones[i], total_fn=lambda i=i: totals[i])
                td.add_line(f"{name}:bar", Line(f"{name}:bar", stats=[pb.cell()]))

        stop_time = time.time() + duration

        def worker(idx: int) -> None:
            name = f"thr-{idx+1:02d}"
            total = totals[idx]
            done = 0
            while time.time() < stop_time and done < total:
                step = random.randint(1, 5)
                done = min(total, done + step)
                dones[idx] = done
                td.update_stat(name, "done", done)
                if args.extra_stats >= 1:
                    td.update_stat(name, "rate", step / max(update, 1e-6))
                _sleep(update)

        ts: List[threading.Thread] = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

    return 0


# ---------------------------------------------------------------------------
# SEEMAKE (CMake-like output)

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
        sm = SeemakePrinter(total=steps, td=td, with_bar=args.header_bar, bar_width=args.width,
                            label="Build", out=sys.stdout)
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


# ---------------------------------------------------------------------------
# ARGPARSE

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="termdash", description="TermDash CLI demos")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser):
        sp.add_argument("-c", "--clear", action="store_true", help="Clear the screen at exit (default: print snapshot).")
        sp.add_argument("-P", "--plain", action="store_true", help="Run without live dashboard; print plain text.")
        sp.add_argument("-S", "--seed", type=int, default=1234, help="Random seed for repeatable demos.")

    # progress
    sp = sub.add_parser("progress", help="Single progress demo (optionally bar below).")
    add_common(sp)
    sp.add_argument("-t", "--total", type=int, default=100)
    sp.add_argument("-i", "--interval", type=float, default=0.05)
    sp.add_argument("-w", "--width", type=int, default=28)
    sp.add_argument("-a", "--ascii", action="store_true", help="Use ASCII bar instead of Unicode.")
    sp.add_argument("-n", "--no-percent", action="store_true", help="Hide percent text inside the bar.")
    sp.add_argument("-b", "--bars", action="store_true", help="Show a bar below the row.")
    sp.set_defaults(func=demo_progress)

    # stats
    sp = sub.add_parser("stats", help="Single row of stats (like one multistats row).")
    add_common(sp)
    sp.add_argument("-d", "--duration", type=float, default=4.0)
    sp.add_argument("-u", "--update", type=float, default=0.1, help="Update interval seconds.")
    sp.add_argument("-w", "--width", type=int, default=28)
    sp.add_argument("-t", "--total", type=int, default=100)
    sp.add_argument("-b", "--bars", action="store_true", help="Bar below the row.")
    sp.add_argument("-e", "--extra-stats", type=int, default=0, help="Extra stats per row (0..3).")
    sp.add_argument("-H", "--header", action="store_true", help="Add a header line with title.")
    sp.add_argument("-B", "--header-bar", action="store_true", help="Add a header bar (cumulated when applicable).")
    sp.set_defaults(func=demo_stats)

    # multistats
    sp = sub.add_parser("multistats", help="Multiple rows with per-row stats; optional bars below.")
    add_common(sp)
    sp.add_argument("-r", "--rows", type=int, default=0, help="Number of rows (alias of --processes).")
    sp.add_argument("-p", "--processes", type=int, default=6, help="Number of rows.")
    sp.add_argument("-g", "--proc", choices=["ytdlp", "copy", "compute"], default="ytdlp", help="Row profile.")
    sp.add_argument("-d", "--duration", type=float, default=5.0)
    sp.add_argument("-u", "--update", type=float, default=0.15)
    sp.add_argument("-w", "--width", type=int, default=26)
    sp.add_argument("-b", "--bars", action="store_true", help="Show a bar **below** each row.")
    sp.add_argument("-e", "--extra-stats", type=int, default=0, help="Extra stats per row (0..2).")
    sp.add_argument("-H", "--header", action="store_true", help="Add a header totals row.")
    sp.add_argument("-B", "--header-bar", action="store_true", help="Add a header bar (combined progress).")
    sp.set_defaults(func=demo_multistats)

    # threads
    sp = sub.add_parser("threads", help="Multi-threaded updates; optional bars below each row.")
    add_common(sp)
    sp.add_argument("-n", "--threads", type=int, default=6)
    sp.add_argument("-d", "--duration", type=float, default=5.0)
    sp.add_argument("-u", "--update", type=float, default=0.10)
    sp.add_argument("-w", "--width", type=int, default=26)
    sp.add_argument("-b", "--bars", action="store_true", help="Show a bar below each thread row.")
    sp.add_argument("-e", "--extra-stats", type=int, default=0, help="Extra per-row stats (0..1).")
    sp.add_argument("-H", "--header", action="store_true", help="Add a header totals row.")
    sp.add_argument("-B", "--header-bar", action="store_true", help="Add a header bar (combined progress).")
    sp.set_defaults(func=demo_threads)

    # seemake
    sp = sub.add_parser("seemake", help="CMake-like scrolling output.")
    add_common(sp)
    sp.add_argument("-s", "--steps", type=int, default=25, help="Number of build steps.")
    sp.add_argument("-i", "--interval", type=float, default=0.08, help="Sleep between steps.")
    sp.add_argument("-B", "--header-bar", action="store_true", help="Show a bottom progress bar row.")
    sp.add_argument("-w", "--width", type=int, default=24)
    sp.set_defaults(func=demo_seemake)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    random.seed(args.seed)
    return int(bool(args.func(args)))


if __name__ == "__main__":
    raise SystemExit(main())
