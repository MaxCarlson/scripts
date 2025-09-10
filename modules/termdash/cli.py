#!/usr/bin/env python3
"""
TermDash CLI Demos (revised)

- `multistats` is the canonical demo. Use `-r 1` to mimic "single process" stats.
- `threads` runs multiple independent `multistats` rows concurrently.
- Bars below rows are full-width and independent of column alignment.
- `stats` is kept as an alias of `multistats -r 1` to ease transition.

Single-letter flags exist for all options.
"""
from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import Stat, Line, TermDash
from .progress import ProgressBar
from .seemake import SeemakePrinter


# ---------------------------------------------------------------------------
# Helpers

def _sleep(sec: float) -> None:
    if sec > 0:
        time.sleep(sec)


def _print_snapshot(title: str, rows: List[Tuple[str, List[Stat]]]) -> None:
    print("\n=== TermDash Demo Snapshot:", title, "===")
    for name, stats in rows:
        try:
            line = " | ".join(s.prefix + (s.format_string.format(s.value)) + (s.unit or "") for s in stats)
        except Exception:
            line = " | ".join(f"<{s.name}>" for s in stats)
        print(f"{name:>12}: {line}")


def _add_header(td: TermDash, name: str, text: str) -> None:
    td.add_line(name, Line(name, stats=[Stat("title", text, format_string="{}", color="1;36")], style="header"))


def _add_fullwidth_bar_line(td: TermDash, line_name: str,
                            current_fn: Callable[[], float],
                            total_fn: Callable[[], float],
                            width_hint: int) -> None:
    """A bar that spans the terminal width on its *own* line."""
    pb = ProgressBar(f"{line_name}:bar", total=1, width=max(10, width_hint),
                     show_percent=True, full_width=True, margin=0)
    pb.bind(current_fn=current_fn, total_fn=total_fn)
    td.add_line(f"{line_name}:bar", Line(f"{line_name}:bar", stats=[pb.cell()]))


# ---------------------------------------------------------------------------
# MULTISTATS

@dataclass
class SimRow:
    name: str
    total: int
    done: int = 0
    status: str = "queued"
    rate: float = 0.0
    errs: int = 0


def _profile(kind: str) -> Tuple[int, int]:
    return {
        "ytdlp": (1, 6),
        "copy": (5, 25),
        "compute": (1, 3),
    }.get(kind, (1, 5))


def demo_multistats(args: argparse.Namespace) -> int:
    rows = max(1, args.rows or args.processes)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)
    kind = args.proc

    items = [SimRow(name=f"row-{i+1}", total=random.randint(60, 120)) for i in range(rows)]

    td = None
    snap: List[Tuple[str, List[Stat]]] = []

    if args.plain:
        t0 = time.time()
        while time.time() - t0 < duration and any(r.done < r.total for r in items):
            for r in items:
                if r.done < r.total:
                    step = random.randint(*_profile(kind))
                    r.done = min(r.total, r.done + step)
                    r.rate = 0.6 * r.rate + 0.4 * (step / max(update, 1e-6))
                    r.status = "downloading" if kind == "ytdlp" else "running"
                else:
                    r.status = "done"
                print(f"{r.name:>8} | {r.status:12} | {r.done:4}/{r.total:<4} | {r.rate:6.1f} u/s | errs={r.errs}")
            _sleep(update)
        return 0

    td = TermDash(status_line=True, refresh_rate=0.05)
    with td:
        if args.header:
            _add_header(td, "hdr", f"Multi-Stats Demo ({kind})")
            if args.header_bar:
                _add_fullwidth_bar_line(
                    td, "hdr",
                    current_fn=lambda: float(sum(r.done for r in items)),
                    total_fn=lambda: float(sum(r.total for r in items)),
                    width_hint=args.width,
                )

        # Rows
        for r in items:
            cells = [Stat("status", r.status),
                     Stat("done", r.done, prefix="Done: "),
                     Stat("total", r.total, prefix="Total: ")]
            if args.extra_stats >= 1:
                cells.append(Stat("rate", 0.0, prefix="Rate: ", format_string="{:.1f}", unit="u/s"))
            if args.extra_stats >= 2:
                cells.append(Stat("errs", 0, prefix="Errs: "))

            td.add_line(r.name, Line(r.name, stats=cells))
            snap.append((r.name, cells))

            if args.bars:
                _add_fullwidth_bar_line(
                    td, r.name,
                    current_fn=lambda r=r: r.done,
                    total_fn=lambda r=r: r.total,
                    width_hint=args.width,
                )

        # Drive updates
        t0 = time.time()
        while time.time() - t0 < duration and any(r.done < r.total for r in items):
            for r in items:
                if r.done >= r.total:
                    if r.status != "done":
                        r.status = "done"
                        td.update_stat(r.name, "status", r.status)
                    continue
                step = random.randint(*_profile(kind))
                r.done = min(r.total, r.done + step)
                r.rate = 0.6 * r.rate + 0.4 * (step / max(update, 1e-6))
                r.status = "downloading" if kind == "ytdlp" else "running"

                td.update_stat(r.name, "status", r.status)
                td.update_stat(r.name, "done", r.done)
                if args.extra_stats >= 1:
                    td.update_stat(r.name, "rate", r.rate)
                if args.extra_stats >= 2 and random.random() < 0.03:
                    r.errs += 1
                    td.update_stat(r.name, "errs", r.errs)
            _sleep(update)

    if not args.clear:
        _print_snapshot("multistats", snap)
    return 0


# ---------------------------------------------------------------------------
# THREADS  => multiple multistats asynchronously

def demo_threads(args: argparse.Namespace) -> int:
    threads = max(1, args.threads)
    duration = max(0.1, args.duration)
    update = max(0.01, args.update)
    kind = args.proc

    totals = [random.randint(60, 120) for _ in range(threads)]
    dones = [0 for _ in range(threads)]
    rates = [0.0 for _ in range(threads)]
    errs = [0 for _ in range(threads)]

    td = TermDash(status_line=True, refresh_rate=0.05)
    with td:
        if args.header:
            _add_header(td, "hdr", "Multi-Threaded Demo")
            if args.header_bar:
                _add_fullwidth_bar_line(
                    td, "hdr",
                    current_fn=lambda: float(sum(dones)),
                    total_fn=lambda: float(sum(totals)),
                    width_hint=args.width,
                )

        # one row per thread (equals a multistats row)
        for i in range(threads):
            name = f"thr-{i+1:02d}"
            cells = [Stat("done", 0, prefix="Done: "),
                     Stat("total", totals[i], prefix="Total: ")]
            if args.extra_stats >= 1:
                cells.append(Stat("rate", 0.0, prefix="Rate: ", format_string="{:.1f}", unit="u/s"))

            td.add_line(name, Line(name, stats=cells))

            if args.bars:
                _add_fullwidth_bar_line(
                    td, name,
                    current_fn=lambda i=i: float(dones[i]),
                    total_fn=lambda i=i: float(totals[i]),
                    width_hint=args.width,
                )

        stop = time.time() + duration

        def worker(idx: int) -> None:
            while time.time() < stop and dones[idx] < totals[idx]:
                lo, hi = _profile(kind)
                step = random.randint(lo, hi)
                dones[idx] = min(totals[idx], dones[idx] + step)
                rates[idx] = 0.6 * rates[idx] + 0.4 * (step / max(update, 1e-6))
                td.update_stat(f"thr-{idx+1:02d}", "done", dones[idx])
                if args.extra_stats >= 1:
                    td.update_stat(f"thr-{idx+1:02d}", "rate", rates[idx])
                _sleep(update)

        ts = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads)]
        for t in ts: t.start()
        for t in ts: t.join()

    return 0


# ---------------------------------------------------------------------------
# SEEMAKE

def demo_seemake(args: argparse.Namespace) -> int:
    steps = max(1, args.steps)

    if args.plain:
        # Plain mode: simple colored-like text (no ANSI here to keep logs clean)
        for i in range(1, steps + 1):
            pct = int(round(100 * i / steps))
            print(f"[{pct:3d}%] step {i}/{steps}")
            _sleep(args.interval)
        return 0

    # Leaner TermDash config to reduce flicker and avoid the "lock" feel.
    td = TermDash(status_line=False, refresh_rate=0.05, reserve_extra_rows=0)
    with td:
        sm = SeemakePrinter(
            total=steps, td=td, with_bar=args.header_bar,
            bar_width=args.width, label="Build", out=sys.stdout
        )
        # Typical sequence: scan -> build -> (optional link) -> success
        kinds = ["scan", "build", "build", "link", "success"]
        for i in range(1, steps + 1):
            k = kinds[(i - 1) % len(kinds)]
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
        sp.add_argument("-c", "--clear", action="store_true", help="Clear screen at exit (default: print snapshot).")
        sp.add_argument("-P", "--plain", action="store_true", help="Run without live dashboard; print plain text.")
        sp.add_argument("-S", "--seed", type=int, default=1234, help="Random seed for repeatability.")

    # multistats (canonical)
    sp = sub.add_parser("multistats", help="Multiple rows; per-row stats; optional full-width bars below rows.")
    add_common(sp)
    sp.add_argument("-r", "--rows", type=int, default=0, help="Number of rows (alias of --processes).")
    sp.add_argument("-p", "--processes", type=int, default=6, help="Number of rows.")
    sp.add_argument("-g", "--proc", choices=["ytdlp", "copy", "compute"], default="ytdlp", help="Profile of row updates.")
    sp.add_argument("-d", "--duration", type=float, default=5.0)
    sp.add_argument("-u", "--update", type=float, default=0.15)
    sp.add_argument("-w", "--width", type=int, default=26, help="Width hint for bars (full-width ignores this mostly).")
    sp.add_argument("-b", "--bars", action="store_true", help="Show a full-width bar on its own line below each row.")
    sp.add_argument("-e", "--extra-stats", type=int, default=0, help="Extra stats per row (0..2).")
    sp.add_argument("-H", "--header", action="store_true", help="Header with title.")
    sp.add_argument("-B", "--header-bar", action="store_true", help="Header progress bar (combined progress).")
    sp.set_defaults(func=demo_multistats)

    # threads (many multistats concurrently)
    sp = sub.add_parser("threads", help="Multiple rows updated by threads; same flags as multistats.")
    add_common(sp)
    sp.add_argument("-n", "--threads", type=int, default=6)
    sp.add_argument("-g", "--proc", choices=["ytdlp", "copy", "compute"], default="ytdlp")
    sp.add_argument("-d", "--duration", type=float, default=5.0)
    sp.add_argument("-u", "--update", type=float, default=0.10)
    sp.add_argument("-w", "--width", type=int, default=26)
    sp.add_argument("-b", "--bars", action="store_true")
    sp.add_argument("-e", "--extra-stats", type=int, default=0)
    sp.add_argument("-H", "--header", action="store_true")
    sp.add_argument("-B", "--header-bar", action="store_true")
    sp.set_defaults(func=demo_threads)

    # seamake
    sp = sub.add_parser("seemake", help="CMake-like scrolling output (optionally with a bottom bar).")
    add_common(sp)
    sp.add_argument("-s", "--steps", type=int, default=25)
    sp.add_argument("-i", "--interval", type=float, default=0.08)
    sp.add_argument("-B", "--header-bar", action="store_true", help="Show a bottom progress bar row.")
    sp.add_argument("-w", "--width", type=int, default=24)
    sp.set_defaults(func=demo_seemake)

    # stats (alias of multistats -r 1)
    sp = sub.add_parser("stats", help="Alias of: multistats -r 1")
    add_common(sp)
    sp.add_argument("-b", "--bars", action="store_true")
    sp.add_argument("-e", "--extra-stats", type=int, default=0)
    sp.add_argument("-H", "--header", action="store_true")
    sp.add_argument("-B", "--header-bar", action="store_true")
    sp.add_argument("-w", "--width", type=int, default=28)
    sp.set_defaults(func=lambda a: demo_multistats(argparse.Namespace(
        cmd="multistats",
        clear=a.clear, plain=a.plain, seed=a.seed,
        rows=1, processes=1, proc="ytdlp",
        duration=4.0, update=0.1, width=a.width,
        bars=a.bars, extra_stats=a.extra_stats, header=a.header, header_bar=a.header_bar,
    )))

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    random.seed(args.seed)
    return int(bool(args.func(args)))


if __name__ == "__main__":
    raise SystemExit(main())
