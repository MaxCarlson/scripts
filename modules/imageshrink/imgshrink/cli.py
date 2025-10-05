#!/usr/bin/env python3
"""
imgshrink CLI: multi-process leaf-folder compressor with a live dashboard.
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import os
import queue
import shutil
import sys
import time
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
from .ui import Dashboard


def find_project_root(marker: str = ".git") -> Path:
    """Find the project root by searching upwards for a marker file/dir."""
    current = Path(__file__).resolve()
    while current != current.parent:
        if (current / marker).exists():
            return current
        current = current.parent
    raise FileNotFoundError(f"Project root marker '{marker}' not found.")

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(processName)s %(message)s",
        datefmt="%H:%M:%S",
    )

def _setup_worker_logging(worker_id: int):
    """Configure file logging for a worker process."""
    try:
        root = find_project_root()
        log_dir = root / "logs" / "imgshrink"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"worker-{worker_id}.log"

        logger = logging.getLogger()
        # Remove any existing handlers to avoid duplicate console output
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        # Add new file handler
        handler = logging.FileHandler(log_file, mode='w')
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except Exception as e:
        logging.error(f"Failed to set up worker logging: {e}")

def worker_main(worker_id: int,
                tasks: "mp.JoinableQueue[Tuple[str, Dict]]",
                outq: "mp.Queue[Event]",
                args: argparse.Namespace) -> None:
    """
    Worker process loop: receives (folder_path, plan_dict|None) and processes it.
    Sends Events to outq for UI updates.
    """
    _setup_worker_logging(worker_id)
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
                folder_start_time = time.time()
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
                outq.put(ev(worker_id, "FOLDER_START", folder=str(folder), img_total=len(infos)))

                done_bytes = 0
                last_bytes = 0
                last_t = time.time()
                img_done = 0
                last_pct = -1
                out_dir = None if args.overwrite else folder / "_compressed"

                for info in infos:
                    if args.dry_run:
                        time.sleep(0.05)
                        done_bytes += info.bytes
                        img_done += 1
                    else:
                        res = compress_one(
                            info.path,
                            out_dir=out_dir,
                            plan=plan,
                            overwrite=args.overwrite,
                            backup=args.backup,
                        )
                        done_bytes += info.bytes
                        img_done += 1

                    current_pct = int((img_done / len(infos)) * 100)
                    if current_pct // 10 > last_pct // 10:
                        now = time.time()
                        dt = max(1e-6, now - last_t)
                        speed_mib = (done_bytes - last_bytes) / dt / (1024 * 1024) if dt > 0 else 0
                        last_t, last_bytes = now, done_bytes
                        eta_s = (total_bytes - done_bytes) / (speed_mib * 1024 * 1024) if speed_mib > 0 else None
                        outq.put(ev(worker_id, "FOLDER_PROGRESS", img_done=img_done, img_total=len(infos), speed_mib_s=speed_mib, eta_s=eta_s))
                        last_pct = current_pct

                elapsed_s = time.time() - folder_start_time
                files_per_s = stats.count / max(1e-6, elapsed_s)
                mib_per_s = (total_bytes / max(1e-6, elapsed_s)) / (1024 * 1024)

                stats_str = f"Images: {stats.count}, Avg Size: {bytes_human(stats.bytes_avg)}, Res: {stats.common_res[0]}x{stats.common_res[1]}"
                outq.put(ev(worker_id, "FOLDER_STATS", stats_str=stats_str))
                time.sleep(0.1)

                outq.put(ev(worker_id, "FOLDER_FINISH", folder=str(folder),
                    elapsed_s=elapsed_s, files_per_s=files_per_s, mib_per_s=mib_per_s))
                time.sleep(0.5) # Final sleep to ensure UI processes events
                tasks.task_done()
            except Exception as e:
                logging.exception(f"Error processing folder {folder}")
                outq.put(ev(worker_id, "FOLDER_ERROR", folder=str(folder), message=str(e)))
                tasks.task_done()
    except KeyboardInterrupt:
        pass
    finally:
        outq.put(ev(worker_id, "SHUTDOWN"))


def _load_summary(path: Optional[Path]) -> Dict:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_summary(path: Optional[Path], summary: Dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _build_summary_entry(folder: Path, infos, stats, plan: Plan) -> Dict:
    total_before = sum(i.bytes for i in infos)
    predicted_after = predict_after_bytes(infos, plan)
    ratio = float(predicted_after) / float(total_before) if total_before else 1.0
    return {
        "folder": str(folder.resolve()),
        "stats": stats.to_dict(),
        "plan": plan.to_dict(),
        "images": [{**i.__dict__, 'path': str(i.path)} for i in infos],
        "total_before_bytes": total_before,
        "predicted_after_bytes": predicted_after,
        "predicted_ratio": ratio,
    }

def _print_summary_report(summary_entries: List[Dict]) -> None:
    if not summary_entries:
        return

    C = {
        "HEADER": "\033[95m", "BLUE": "\033[94m", "GREEN": "\033[92m",
        "YELLOW": "\033[93m", "END": "\033[0m", "BOLD": "\033[1m",
    }
    
    try:
        term_width = shutil.get_terminal_size().columns
    except OSError:
        term_width = 80

    print(f"\n{C['BOLD']}{C['HEADER']}=== Per-folder Summary ==={C['END']}")
    for i, e in enumerate(summary_entries, 1):
        st = e["stats"]
        name = Path(e["folder"]).name
        before = bytes_human(e["total_before_bytes"])
        after = bytes_human(e["predicted_after_bytes"])
        ratio = e["predicted_ratio"]
        modes_str = ", ".join([f"{count}x {mode}" for mode, count in st['modes'].items()])

        print("\n" + ("~" * term_width))
        print(f"{C['BOLD']}{i}). {name}{C['END']}")
        print(f"    - {'Total Size':<12}: {C['GREEN']}{before} -> {after}{C['END']} ({C['YELLOW']}{ratio:.2f}x{C['END']})")
        print(f"    - {'Images':<12}: {st['count']}")
        print(f"      - {'Sizes (bytes)':<12}: min={st['bytes_min']}, max={st['bytes_max']}, avg={int(st['bytes_avg'])}, median={int(st['bytes_median'])}")
        print(f"      - {'Modes':<12}: {modes_str}")
        print(f"    - {'Entropy':<12}: min={st['q_entropy_min']:.2f}, avg={st['q_entropy_avg']:.2f}, max={st['q_entropy_max']:.2f}")
        print(f"    - {'Laplacian':<12}: min={st['q_lap_min']:.3g}, avg={st['q_lap_avg']:.3g}, max={st['q_lap_max']:.3g}")

def main() -> None:
    ap = argparse.ArgumentParser(description="Shrink manga image folders with a live dashboard")

    ap.add_argument("root", type=Path, help="Root folder to scan for leaf image directories")

    # Concurrency & UI
    ap.add_argument("-t", "--threads", type=int, default=1, help="Number of worker processes (default: 1)")
    ap.add_argument("-u", "--ui", action="store_true", help="Enable live dashboard UI")

    # Modes
    ap.add_argument("-n", "--dry-run", action="store_true", help="Analyze mode: predict changes without writing files")
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
    ap.add_argument("-r", "--target-ratio", type=float,
                    help="Aim for this total size ratio per folder (e.g., 0.6 → 60%% of original)")
    ap.add_argument("-m", "--target-total-mb", type=float,
                    help="Aim for this total size (MiB) per folder")
    ap.add_argument("-w", "--overwrite", action="store_true", help="Overwrite originals (else write to _compressed/)")
    ap.add_argument("-b", "--backup", action="store_true", help="Make .orig backups when overwriting")

    # Test mode
    ap.add_argument("-T", "--test-images", nargs="+", type=Path,
                    help="Compress only these images (bypasses leaf-folder scanning)")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    ap.add_argument("-z", "--trace-png", action="store_true", help="Show PNG chunk debug from Pillow (very verbose)")

    args = ap.parse_args()
    _setup_logging(args.verbose)

    ctx = mp.get_context("spawn") if sys.platform.startswith("win") else mp.get_context("fork")

    if args.test_images:
        # ... (test mode remains the same)
        return

    # Main application flow
    run_start_time = time.time()
    leaves = find_leaf_image_dirs(args.root)
    if not leaves:
        print("No leaf image folders found under:", args.root, file=sys.stderr)
        sys.exit(1)

    tasks: mp.JoinableQueue = mp.JoinableQueue()
    outq: mp.Queue = mp.Queue()
    
    plan_map: Dict[str, Dict] = _load_summary(args.apply_from_summary) if args.apply_from_summary else {}
    if not plan_map:
        plan_map = _load_plan(args.plan_file) if args.apply_plan else {}

    for leaf in leaves:
        key = str(leaf.resolve())
        plan_data = plan_map.get(key) or (plan_map.get("folders", [{}])[0].get("plan") if key in str(plan_map) else None)
        tasks.put((str(leaf), plan_data))

    n_workers = max(1, int(args.threads))
    for _ in range(n_workers):
        tasks.put(None)

    dash = Dashboard(n_workers, root_path=args.root, refresh_hz=10.0) if args.ui else None
    if dash:
        dash.start()

    procs: List[mp.Process] = []
    for wid in range(n_workers):
        p = ctx.Process(target=worker_main, args=(wid, tasks, outq, args), name=f"worker-{wid+1}")
        p.daemon = True
        p.start()
        procs.append(p)

    alive = len(procs)
    summary_entries: List[Dict] = []
    while alive > 0:
        if dash and dash.stop_requested:
            break
        try:
            evn: Event = outq.get(timeout=0.1)
            if dash:
                dash.apply(evn)
            if evn.type == "SHUTDOWN":
                alive -= 1
        except queue.Empty:
            alive = sum(1 for p in procs if p.is_alive())
            continue

    for p in procs:
        p.join(timeout=1.0)
    if dash:
        dash.stop()

    # Final summary generation
    print("Generating final summary...")
    all_infos = []
    for leaf in leaves:
        images = collect_images(leaf)
        infos, stats = analyze_images(images)
        if not stats:
            continue
        all_infos.extend(infos)
        plan = decide_plan(stats, phone_max_dim=args.phone_max_dim, prefer_format=args.format, png_quantize_colors=args.png_quantize)
        entry = _build_summary_entry(leaf, infos, stats, plan)
        summary_entries.append(entry)

    if args.summary_file:
        # ... (save summary logic remains the same)
        pass

    _print_summary_report(summary_entries)
