#!/usr/bin/env python3
"""
sysmon-capture — render every sysmon tab to SVG for visual inspection.

Usage:
    sysmon-capture [--out-dir DIR] [--width N] [--wait N]
"""
import argparse
import io
import time
from pathlib import Path

import psutil
from rich.console import Console

import sysmon.cli as _sm


def _capture_view(panel, title: str, width: int, out_path: Path) -> None:
    buf     = io.StringIO()
    console = Console(record=True, width=width, force_terminal=True, no_color=False, file=buf)
    console.print(panel)
    svg = console.export_svg(title=title)
    out_path.write_text(svg, encoding="utf-8")
    print(f"  ok  {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Render every sysmon tab to SVG")
    ap.add_argument("-o", "--out-dir", default=str(Path.cwd() / "sysmon_svgs"),
                    help="Output directory (default: ./sysmon_svgs)")
    ap.add_argument("-W", "--width",   type=int, default=130,
                    help="Simulated terminal width (default: 130)")
    ap.add_argument("-n", "--wait",    type=int, default=1,
                    help="Seconds to collect live data before rendering (default: 1)")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ncpu = psutil.cpu_count(logical=True) or 1

    cpu_state  = _sm.CpuState()
    net_state  = _sm.NetState()
    net_state.prev_total    = _sm.get_total_counters()
    net_state.prev_time     = time.time()
    net_state.link_cap_mbps = _sm.sum_active_link_capacity_mbps()
    net_state.per_proc_on   = True
    disk_state = _sm.DiskLiveState()
    disk_state.prev = _sm.safe_disk_io_counters_perdisk()
    over_state = _sm.OverallState()
    gpu_state  = _sm.GpuState()

    print(f"Collecting {args.wait}s of process data …")
    prev_snaps = _sm.iter_snaps("*")
    time.sleep(max(1, args.wait))
    curr_snaps = _sm.iter_snaps("*")
    rows       = _sm.deltas(prev_snaps, curr_snaps, ncpu)
    rows_cpu   = sorted(rows, key=lambda r: r["cpu_pct"], reverse=True)
    rows_disk  = sorted(rows, key=lambda r: r["d_mb_s"],  reverse=True)

    # Let net state accumulate one tick of history
    time.sleep(1)

    print("Rendering views …")
    _capture_view(
        _sm.render_overall(over_state, net_state, disk_state, gpu_state),
        "sysmon – overall", args.width, out / "sysmon_overall.svg",
    )
    _capture_view(
        _sm.render_cpu_table(rows_cpu, total=len(curr_snaps), limit=20,
                             sort_mode="cpu", cpu_state=cpu_state),
        "sysmon – cpu", args.width, out / "sysmon_cpu.svg",
    )
    _capture_view(
        _sm.render_disk_view(rows_disk, len(rows_disk), 15, "total", disk_state),
        "sysmon – disk", args.width, out / "sysmon_disk.svg",
    )
    _capture_view(
        _sm.render_net_panel(net_state, top_n=15, interval_hint=1.0, proc_rows=rows),
        "sysmon – net", args.width, out / "sysmon_net.svg",
    )
    _capture_view(
        _sm.render_gpu(gpu_state),
        "sysmon – gpu", args.width, out / "sysmon_gpu.svg",
    )

    print(f"\nAll SVGs in: {out}")
    print("Open in any browser to inspect.")


if __name__ == "__main__":
    main()
