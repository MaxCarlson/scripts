#!/usr/bin/env python3
"""
imgshrink CLI: multi-process leaf-folder compressor with a live dashboard.

Usage examples:

  Dry run + plan + summary (JSON):
    imgshrink /path/to/manga -t 6 -n -P plans.json -S summary.json --phone-max-dim 3200

  Apply using cached plan:
    imgshrink /path/to/manga -t 6 -a -P plans.json --phone-max-dim 3200 --ui

  Apply using a summary file (no re-analysis):
    imgshrink /path/to/manga -t 6 --apply-from-summary summary.json --ui

  Test a few images:
    imgshrink . -T page1.png page2.jpg --phone-max-dim 3200 -n

Notes:
- Dashboard uses a built-in ANSI UI; if 'termdash' is installed, it uses that instead.
- By default we write outputs to a _compressed/ subfolder. Use -w/--overwrite to replace originals
  (optionally -b/--backup to keep .orig copies).
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import os
import queue
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .analysis import (
    analyze_images,
    bytes_human,
    collect_images,
    decide_plan,
    find_leaf_image_dirs,
    predict_after_bytes,
    Plan,
)
from .compress import compress_one
from .events import Event, ev
from .ui import make_dashboard


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(processName)s %(message)s",
        datefmt="%H:%M:%S",
    )


def worker_main(worker_id: int,
                tasks: "mp.JoinableQueue[Tuple[str, Dict]]",
                outq: "mp.Queue[Event]",
                args: argparse.Namespace) -> None:
    """
    Worker process loop: receives (folder_path, plan_dict|None) and processes it.
    Sends Events to outq for UI updates.
    """
    try:
        outq.put(ev(worker_id, "WORKER_ONLINE"))
        while True:
            item = tasks.get()
            if item is None:
                tasks.task_done()
                break
            folder_str, plan_dict = item
            folder = Path(folder_str)
            try:
                images = collect_images(folder)
                infos, stats = analyze_images(images)
                if not stats:
                    outq.put(ev(worker_id, "LOG", text=f"[SKIP] No readable images in {folder}"))
                    tasks.task_done()
                    continue

                if plan_dict is None:
                    plan = decide_plan(
                        stats,
                        phone_max_dim=args.phone_max_dim,
                        prefer_format=args.format,
                        png_quantize_colors=args.png_quantize,
                    )
                else:
                    plan = Plan(**plan_dict)

                total_bytes = sum(i.bytes for i in infos)
                outq.put(ev(worker_id, "FOLDER_START", folder=str(folder), total_bytes=total_bytes))

                done_bytes = 0
                last = time.time()
                for info in infos:
                    if args.dry_run:
                        # Simulate progress based on size only
                        done_bytes += info.bytes
                        now = time.time()
                        dt = max(1e-6, now - last)
                        speed_mib = (info.bytes / dt) / (1024 * 1024)
                        last = now
                    else:
                        res = compress_one(
                            info.path,
                            out_dir=None if args.overwrite else folder / "_compressed",
                            plan=plan,
                            overwrite=args.overwrite,
                            backup=args.backup,
                        )
                        done_bytes += info.bytes
                        now = time.time()
                        dt = max(1e-6, now - last)
                        speed_mib = (res.before_bytes / dt) / (1024 * 1024)
                        last = now

                    remaining = max(0, total_bytes - done_bytes)
                    eta_s = None
                    if speed_mib > 0:
                        eta_s = (remaining / (1024 * 1024)) / speed_mib

                    outq.put(ev(worker_id, "FOLDER_PROGRESS",
                                done_bytes=done_bytes,
                                total_bytes=total_bytes,
                                speed_mib_s=speed_mib,
                                eta_s=eta_s))

                outq.put(ev(worker_id, "FOLDER_FINISH", folder=str(folder)))
                tasks.task_done()
            except Exception as e:
                outq.put(ev(worker_id, "FOLDER_ERROR", folder=str(folder), message=str(e)))
                outq.put(ev(worker_id, "LOG", text=f"[ERROR] {folder}: {e}"))
                tasks.task_done()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            outq.put(ev(worker_id, "SHUTDOWN"))
        except Exception:
            pass


def _load_plan(path: Optional[Path]) -> Dict[str, Dict]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_plan(path: Optional[Path], mapping: Dict[str, Dict]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")


def _save_summary(path: Optional[Path], summary: Dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _load_summary(path: Optional[Path]) -> Dict:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _build_summary_entry(folder: Path, infos, stats, plan: Plan) -> Dict:
    total_before = sum(i.bytes for i in infos)
    predicted_after = predict_after_bytes(infos, plan)
    ratio = float(predicted_after) / float(total_before) if total_before else 1.0
    return {
        "folder": str(folder.resolve()),
        "stats": stats.to_dict(),
        "plan": plan.to_dict(),
        "total_before_bytes": total_before,
        "predicted_after_bytes": predicted_after,
        "predicted_ratio": ratio,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Shrink manga image folders with a live dashboard")

    ap.add_argument("root", type=Path, help="Root folder to scan for leaf image directories")

    # Concurrency & UI
    ap.add_argument("-t", "--threads", type=int, default=os.cpu_count() or 4, help="Number of worker processes")
    ap.add_argument("-u", "--ui", action="store_true", help="Enable live dashboard UI")

    # Modes
    ap.add_argument("-n", "--dry-run", action="store_true", help="Analyze/predict only; do not write files")
    ap.add_argument("-P", "--plan-file", type=Path, help="Plan file (JSON) to write/read folder compression plans")
    ap.add_argument("-a", "--apply-plan", action="store_true",
                    help="Read per-folder plans from plan-file and apply without re-analysis planning")
    ap.add_argument("-S", "--summary-file", type=Path,
                    help="Write per-leaf-folder summary JSON (stats + predicted savings)")
    ap.add_argument("-R", "--apply-from-summary", type=Path,
                    help="Apply using a previously written summary file (no re-analysis)")

    # Image options
    ap.add_argument("-d", "--phone-max-dim", type=int, help="Cap long edge to this many pixels (e.g., 3200 for S21U)")
    ap.add_argument("-f", "--format", choices=["jpeg", "webp", "png"], help="Force output format (default: keep)")
    ap.add_argument("-Q", "--png-quantize", type=int, help="Quantize PNGs to this many colors (e.g., 256)")
    ap.add_argument("-w", "--overwrite", action="store_true", help="Overwrite originals (else write to _compressed/)")
    ap.add_argument("-b", "--backup", action="store_true", help="Make .orig backups when overwriting")

    # Test mode
    ap.add_argument("-T", "--test-images", nargs="+", type=Path,
                    help="Compress only these images (bypasses leaf-folder scanning)")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = ap.parse_args()
    _setup_logging(args.verbose)

    # Test mode
    if args.test_images:
        imgs = [p for p in args.test_images if p.exists()]
        if not imgs:
            print("No test images found.", file=sys.stderr)
            sys.exit(2)
        infos, stats = analyze_images(imgs)
        if not stats:
            print("Images unreadable.", file=sys.stderr)
            sys.exit(2)
        plan = decide_plan(stats, phone_max_dim=args.phone_max_dim,
                           prefer_format=args.format,
                           png_quantize_colors=args.png_quantize)
        before = sum(i.bytes for i in infos)
        after = predict_after_bytes(infos, plan)
        print("Test plan:", json.dumps(plan.to_dict(), indent=2))
        print(f"Estimated: {bytes_human(before)} -> {bytes_human(after)} (~{after/max(1,before):.2f}x)")
        if not args.dry_run:
            out_dir = None if args.overwrite else Path.cwd() / "_compressed_test"
            out_dir.mkdir(parents=True, exist_ok=True) if out_dir else None
            for i in infos:
                res = compress_one(i.path, out_dir=out_dir, plan=plan,
                                   overwrite=args.overwrite, backup=args.backup)
                print(f"{i.path.name}: {bytes_human(res.before_bytes)} -> {bytes_human(res.after_bytes)}")
        return

    # If applying from a summary, bypass scanning.
    if args.apply_from_summary:
        summary = _load_summary(args.apply_from_summary)
        folders = summary.get("folders", [])
        if not folders:
            print("Summary file has no folders.", file=sys.stderr)
            sys.exit(1)
        # Build tasks from summary (folder -> plan)
        tasks: mp.JoinableQueue = mp.JoinableQueue()
        outq: mp.Queue = mp.Queue()
        n_workers = max(1, int(args.threads))
        for entry in folders:
            tasks.put((entry["folder"], entry.get("plan")))
        for _ in range(n_workers):
            tasks.put(None)

        dash = make_dashboard(n_workers, refresh_hz=8.0) if args.ui else None
        if dash:
            dash.start()

        ctx = mp.get_context("spawn") if sys.platform.startswith("win") else mp.get_context("fork")
        procs: List[mp.Process] = []
        for wid in range(n_workers):
            p = ctx.Process(target=worker_main, args=(wid, tasks, outq, args), name=f"worker-{wid+1}")
            p.daemon = True
            p.start()
            procs.append(p)

        alive = len(procs)
        try:
            while alive > 0:
                if dash and dash.stop_requested:
                    break
                try:
                    evn: Event = outq.get(timeout=0.1)
                except queue.Empty:
                    alive = sum(1 for p in procs if p.is_alive())
                    continue
                if dash:
                    dash.apply(evn)
                if evn.type == "SHUTDOWN":
                    alive -= 1
            for p in procs:
                p.join(timeout=1.0)
        finally:
            if dash:
                dash.stop()
        return

    # Normal scan mode
    leaves = find_leaf_image_dirs(args.root)
    if not leaves:
        print("No leaf image folders found under:", args.root, file=sys.stderr)
        sys.exit(1)

    plan_map: Dict[str, Dict] = _load_plan(args.plan_file)

    # If applying from plan-file only, build tasks with stored plans; else ask workers to compute plan.
    tasks_data: List[Tuple[str, Optional[Dict]]] = []
    for leaf in leaves:
        key = str(leaf.resolve())
        if args.apply_plan and plan_map.get(key):
            tasks_data.append((key, plan_map[key]))
        else:
            tasks_data.append((key, None))  # compute plan in worker

    # Queues
    tasks: mp.JoinableQueue = mp.JoinableQueue()
    outq: mp.Queue = mp.Queue()

    # Preload tasks & sentinels
    for item in tasks_data:
        tasks.put(item)
    n_workers = max(1, int(args.threads))
    for _ in range(n_workers):
        tasks.put(None)

    # Dashboard
    dash = make_dashboard(n_workers, refresh_hz=8.0) if args.ui else None
    if dash:
        dash.start()

    # Start workers
    ctx = mp.get_context("spawn") if sys.platform.startswith("win") else mp.get_context("fork")
    procs: List[mp.Process] = []
    for wid in range(n_workers):
        p = ctx.Process(target=worker_main, args=(wid, tasks, outq, args), name=f"worker-{wid+1}")
        p.daemon = True
        p.start()
        procs.append(p)

    # Orchestrator event loop
    alive = len(procs)
    summary_entries: List[Dict] = []

    try:
        # If dry-run and summary-file requested, we compute summaries controller-side
        # after workers finish (fast enough and consistent).
        while alive > 0:
            if dash and dash.stop_requested:
                break
            try:
                evn: Event = outq.get(timeout=0.1)
            except queue.Empty:
                alive = sum(1 for p in procs if p.is_alive())
                continue
            if dash:
                dash.apply(evn)
            if evn.type == "SHUTDOWN":
                alive -= 1
    finally:
        for p in procs:
            p.join(timeout=1.0)
        if dash:
            dash.stop()

    # Write plan decisions (controller-side recompute; workers computed plans on the fly)
    if (args.plan_file or args.summary_file) and (args.dry_run and not args.apply_plan):
        new_plans: Dict[str, Dict] = {}
        totals_before = 0
        totals_pred_after = 0
        for leaf in leaves:
            key = str(leaf.resolve())
            images = collect_images(leaf)
            infos, stats = analyze_images(images)
            if not stats:
                continue
            plan = decide_plan(stats,
                               phone_max_dim=args.phone_max_dim,
                               prefer_format=args.format,
                               png_quantize_colors=args.png_quantize)
            entry = _build_summary_entry(leaf, infos, stats, plan)
            totals_before += entry["total_before_bytes"]
            totals_pred_after += entry["predicted_after_bytes"]
            new_plans[key] = plan.to_dict()
            summary_entries.append(entry)

        if args.plan_file:
            _save_plan(args.plan_file, new_plans)

        if args.summary_file:
            summary_doc = {
                "root": str(args.root.resolve()),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "phone_max_dim": args.phone_max_dim,
                "format": args.format,
                "png_quantize": args.png_quantize,
                "folders": summary_entries,
                "totals": {
                    "before_bytes": totals_before,
                    "predicted_after_bytes": totals_pred_after,
                    "predicted_ratio": float(totals_pred_after) / float(totals_before) if totals_before else 1.0,
                },
            }
            _save_summary(args.summary_file, summary_doc)