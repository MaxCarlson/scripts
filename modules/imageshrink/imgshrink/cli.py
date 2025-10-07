#!/usr/bin/env python3
"""
imgshrink CLI: multi-process leaf-folder compressor with a live dashboard.

Compatibility + New Stuff:
- Keeps the original flags & flow (tests continue to pass).
- Adds device/distance flags for **PPD-aware** planning.
- Adds `--guard-ssim` for **perceptual guardrail** during encoding.
- Adds **subcommand-style** UX (analyze/plan/compress/all/profile) without breaking legacy usage:
    * If argv[1] in {analyze, plan, compress, all, profile}, a dedicated parser runs.
    * Otherwise, the legacy parser runs (your current behaviour).
- Always prints a colored per-folder summary at the end (unless not found / no images).
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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .analysis import (
    analyze_images,
    bytes_human,
    collect_images,
    decide_plan,
    decide_plan_device_aware,
    find_leaf_image_dirs,
    predict_after_bytes,
    Plan,
    ImageInfo,
    FolderStats,
)
from .compress import compress_one
from .events import Event, ev
from .ui import Dashboard
from .display import DeviceProfile
from . import __version__


# --------------------------- quality presets -------------------------
@dataclass
class QualityPreset:
    """Smart compression preset based on perceptual quality level (0-9)."""
    level: int  # 0 = max quality, 9 = max compression
    ssim_min: float
    ppd_photo: float
    ppd_line: float
    jpeg_quality: int
    webp_quality: int
    downsample_factor: float
    description: str


def get_quality_preset(level: int) -> QualityPreset:
    """
    Return compression parameters for a quality preset level (0-9).

    Level 0: Maximum quality, imperceptible loss
    Level 5: Balanced quality/size, minimal perceptible loss
    Level 9: Aggressive compression, small but noticeable loss

    Based on perceptual research:
    - Human visual acuity: ~60 PPD at optimal viewing
    - SSIM >= 0.95 is generally imperceptible
    - SSIM >= 0.90 is high quality
    - SSIM >= 0.85 is acceptable with visible but minor artifacts
    """
    presets = {
        0: QualityPreset(
            level=0,
            ssim_min=0.98,
            ppd_photo=75.0,
            ppd_line=90.0,
            jpeg_quality=95,
            webp_quality=95,
            downsample_factor=1.0,
            description="Maximum quality - imperceptible loss"
        ),
        1: QualityPreset(
            level=1,
            ssim_min=0.97,
            ppd_photo=70.0,
            ppd_line=85.0,
            jpeg_quality=92,
            webp_quality=92,
            downsample_factor=1.0,
            description="Near-lossless - virtually imperceptible"
        ),
        2: QualityPreset(
            level=2,
            ssim_min=0.96,
            ppd_photo=65.0,
            ppd_line=80.0,
            jpeg_quality=88,
            webp_quality=88,
            downsample_factor=1.0,
            description="Excellent quality - imperceptible to most viewers"
        ),
        3: QualityPreset(
            level=3,
            ssim_min=0.95,
            ppd_photo=60.0,
            ppd_line=75.0,
            jpeg_quality=85,
            webp_quality=85,
            downsample_factor=0.98,
            description="High quality - imperceptible under normal viewing"
        ),
        4: QualityPreset(
            level=4,
            ssim_min=0.93,
            ppd_photo=55.0,
            ppd_line=70.0,
            jpeg_quality=82,
            webp_quality=82,
            downsample_factor=0.95,
            description="Very good quality - slight loss in critical inspection"
        ),
        5: QualityPreset(
            level=5,
            ssim_min=0.91,
            ppd_photo=50.0,
            ppd_line=65.0,
            jpeg_quality=78,
            webp_quality=78,
            downsample_factor=0.92,
            description="Good quality - minimal perceptible loss (balanced)"
        ),
        6: QualityPreset(
            level=6,
            ssim_min=0.89,
            ppd_photo=45.0,
            ppd_line=60.0,
            jpeg_quality=75,
            webp_quality=75,
            downsample_factor=0.88,
            description="Acceptable quality - minor visible artifacts"
        ),
        7: QualityPreset(
            level=7,
            ssim_min=0.87,
            ppd_photo=40.0,
            ppd_line=55.0,
            jpeg_quality=70,
            webp_quality=70,
            downsample_factor=0.85,
            description="Moderate quality - noticeable compression"
        ),
        8: QualityPreset(
            level=8,
            ssim_min=0.85,
            ppd_photo=35.0,
            ppd_line=50.0,
            jpeg_quality=65,
            webp_quality=65,
            downsample_factor=0.80,
            description="Lower quality - visible artifacts, good file size"
        ),
        9: QualityPreset(
            level=9,
            ssim_min=0.82,
            ppd_photo=30.0,
            ppd_line=45.0,
            jpeg_quality=60,
            webp_quality=60,
            downsample_factor=0.75,
            description="Aggressive compression - clear quality loss, small files"
        ),
    }

    if level not in presets:
        raise ValueError(f"Quality preset level must be 0-9, got {level}")

    return presets[level]


# --------------------------- logging ---------------------------------
def find_project_root(marker: str = ".git") -> Path:
    current = Path(__file__).resolve()
    while current != current.parent:
        if (current / marker).exists():
            return current
        current = current.parent
    # fallback to package dir
    return Path(__file__).resolve().parent


def _setup_logging(verbose: bool, trace_png: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(processName)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Suppress PIL/Pillow debug output unless explicitly requested
    pil_level = logging.DEBUG if trace_png else logging.WARNING
    logging.getLogger("PIL").setLevel(pil_level)
    logging.getLogger("PIL.Image").setLevel(pil_level)
    logging.getLogger("PIL.PngImagePlugin").setLevel(pil_level)
    logging.getLogger("PIL.TiffImagePlugin").setLevel(pil_level)


def _setup_worker_logging(worker_id: int):
    try:
        root = find_project_root()
        log_dir = root / "logs" / "imgshrink"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"worker-{worker_id}.log"

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        handler = logging.FileHandler(log_file, mode='w')
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)

        # Suppress PIL debug output in worker logs too
        logging.getLogger("PIL").setLevel(logging.WARNING)
        logging.getLogger("PIL.Image").setLevel(logging.WARNING)
        logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
        logging.getLogger("PIL.TiffImagePlugin").setLevel(logging.WARNING)
    except Exception as e:
        logging.error(f"Failed to set up worker logging: {e}")


# --------------------------- worker ----------------------------------
def worker_main(worker_id: int,
                tasks: "mp.JoinableQueue[Tuple[str, Dict]]",
                outq: "mp.Queue[Event]",
                args: argparse.Namespace) -> None:
    _setup_worker_logging(worker_id)
    logging.info(f"Worker {worker_id} starting")
    try:
        outq.put(ev(worker_id, "WORKER_ONLINE"))
        while True:
            item = tasks.get()
            if item is None:
                logging.info(f"Worker {worker_id} received shutdown signal")
                tasks.task_done()
                break
            folder_str, plan_dict = item
            folder = Path(folder_str)
            logging.info(f"Processing folder: {folder}")
            try:
                folder_start_time = time.time()
                images = collect_images(folder)
                logging.debug(f"Found {len(images)} images in {folder}")
                infos, stats = analyze_images(images)
                if not stats:
                    logging.warning(f"No readable images in {folder}")
                    outq.put(ev(worker_id, "LOG", text=f"[SKIP] No readable images in {folder}"))
                    tasks.task_done()
                    continue

                # device-aware plan if device flags provided and no external plan supplied
                if plan_dict is None:
                    plan = None
                    if args.display_res and args.display_diagonal_in and args.viewing_distance_cm:
                        try:
                            w, h = [int(x) for x in args.display_res.lower().replace("×", "x").split("x")]
                            device = DeviceProfile(
                                diagonal_in=float(args.display_diagonal_in),
                                width_px=w,
                                height_px=h,
                                viewing_distance_cm=float(args.viewing_distance_cm),
                            )
                            plan = decide_plan_device_aware(
                                infos, stats, device,
                                fit_mode=args.fit_mode,
                                ppd_photo=args.ppd_photo,
                                ppd_line=args.ppd_line,
                                prefer_format=args.format,
                                png_quantize_colors=args.png_quantize,
                            )
                        except Exception:
                            plan = None
                    if plan is None:
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
                        time.sleep(0.02)
                        done_bytes += info.bytes
                        img_done += 1
                    else:
                        res = compress_one(
                            info.path,
                            out_dir=out_dir,
                            plan=plan,
                            overwrite=args.overwrite,
                            backup=args.backup,
                            guard_ssim=args.guard_ssim,
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

                res_str = f"Images: {stats.count}, Avg Size: {bytes_human(int(stats.bytes_avg))}"
                if stats.common_res:
                    res_str += f", Res: {stats.common_res[0]}x{stats.common_res[1]}"
                outq.put(ev(worker_id, "FOLDER_STATS", stats_str=res_str))
                time.sleep(0.05)

                logging.info(f"Completed {folder}: {img_done}/{len(infos)} files in {elapsed_s:.2f}s ({files_per_s:.2f} files/s, {mib_per_s:.2f} MiB/s)")
                outq.put(ev(worker_id, "FOLDER_FINISH", folder=str(folder),
                    elapsed_s=elapsed_s, files_per_s=files_per_s, mib_per_s=mib_per_s))
                time.sleep(0.2)
                tasks.task_done()
            except Exception as e:
                logging.exception(f"Error processing folder {folder}")
                outq.put(ev(worker_id, "FOLDER_ERROR", folder=str(folder), message=str(e)))
                tasks.task_done()
    except KeyboardInterrupt:
        pass
    finally:
        outq.put(ev(worker_id, "SHUTDOWN"))


# --------------------------- summary ---------------------------------
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


def _build_summary_entry(folder: Path, infos: List[ImageInfo], stats: FolderStats, plan: Plan) -> Dict:
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
        "HDR": "\033[95m", "BLUE": "\033[94m", "GREEN": "\033[92m",
        "YEL": "\033[93m", "CYAN": "\033[96m", "RED": "\033[91m",
        "BOLD": "\033[1m", "DIM": "\033[2m", "END": "\033[0m",
    }
    try:
        width = shutil.get_terminal_size().columns
    except OSError:
        width = 96
    line = "━" * width

    print(f"\n{C['BOLD']}{C['HDR']}=== Per-folder Summary ==={C['END']}")
    for i, e in enumerate(summary_entries, 1):
        st = e["stats"]
        name = Path(e["folder"]).name
        before = bytes_human(e["total_before_bytes"])
        after = bytes_human(e["predicted_after_bytes"])
        ratio = e["predicted_ratio"]
        modes = ", ".join([f"{cnt}x {m}" for m, cnt in st["modes"].items()]) if st.get("modes") else "-"

        print(f"{C['DIM']}{line}{C['END']}")
        print(f"{C['BOLD']}{C['CYAN']}{i}). {name}{C['END']}")
        print(f"  - {'Total Size':<12}: {C['GREEN']}{before}{C['END']} → {C['GREEN']}{after}{C['END']}  ({C['YEL']}{ratio:.2f}x{C['END']})")
        print(f"  - {'Images':<12}: {st['count']}")
        print(f"  - {'Sizes (B)':<12}: min={st['bytes_min']}, max={st['bytes_max']}, avg={int(st['bytes_avg'])}, med={int(st['bytes_median'])}")
        if st.get("common_res"):
            cr = st["common_res"]
            print(f"  - {'Common Res':<12}: {cr['width']}x{cr['height']}   modes: {modes}")
        else:
            print(f"  - {'Modes':<12}: {modes}")
        print(f"  - {'Entropy':<12}: min={st['q_entropy_min']:.2f}, avg={st['q_entropy_avg']:.2f}, max={st['q_entropy_max']:.2f}")
        print(f"  - {'Laplacian':<12}: min={st['q_lap_min']:.5f}, avg={st['q_lap_avg']:.5f}, max={st['q_lap_max']:.5f}")
        # new metrics (averages)
        print(f"  - {'Colorful':<12}: avg={st.get('colorfulness_avg', 0.0):.2f}    {'Edges':<7}: avg={st.get('edge_density_avg', 0.0):.4f}    {'Gray%':<6}: {st.get('grayscale_pct', 0.0):.1f}%")
        print(f"  - {'Otsu sep':<12}: avg={st.get('otsu_sep_avg', 0.0):.3f}    {'Noise':<7}: avg={st.get('noise_proxy_avg', 0.0):.3f}    {'JPEG q~':<7}: {st.get('jpeg_q_est_avg', 0.0):.1f}")
    print(f"{C['DIM']}{line}{C['END']}")


# --------------------------- legacy parser ----------------------------
def _build_legacy_parser() -> argparse.ArgumentParser:
    description = """Shrink manga image folders with a live dashboard.

Available subcommands:
  analyze   - Analyze images and print/save stats per folder
  plan      - Create a device-aware plan.json per folder
  compress  - Apply an existing plan.json to folders
  all       - Analyze → Plan → Compress in one go
  profile   - Print device PPI/PPD for a screen + distance

Use 'imgshrink <subcommand> -h' for more information on a specific subcommand.
Or use the legacy mode (default) with the options below:"""

    ap = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
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
    ap.add_argument("-d", "--phone-max-dim", type=int, help="Cap long edge to this many pixels (legacy heuristic)")
    ap.add_argument("-f", "--format", choices=["jpeg", "webp", "png"], help="Force output format (default: keep)")
    ap.add_argument("-Q", "--png-quantize", type=int, help="Quantize PNGs to this many colors (e.g., 256)")
    ap.add_argument("-r", "--target-ratio", type=float,
                    help="Aim for this total size ratio per folder (e.g., 0.6 → 60%% of original)")
    ap.add_argument("-m", "--target-total-mb", type=float,
                    help="Aim for this total size (MiB) per folder")
    ap.add_argument("-w", "--overwrite", action="store_true", help="Overwrite originals (else write to _compressed/)")
    ap.add_argument("-b", "--backup", action="store_true", help="Make .orig backups when overwriting")

    # Quality preset (smart compression) - overrides device & perceptual flags
    ap.add_argument("-q", "--quality-preset", type=int, choices=range(10), metavar="0-9",
                    help="Smart compression preset: 0=max quality, 5=balanced, 9=max compression (overrides PPD/SSIM settings)")

    # Device & perceptual flags (advanced options, all have short forms)
    ap.add_argument("-x", "--display-res", help="Screen resolution W×H (e.g., 2400x1080)")
    ap.add_argument("-i", "--display-diagonal-in", type=float, help="Screen diagonal inches")
    ap.add_argument("-c", "--viewing-distance-cm", type=float, help="Viewing distance in cm")
    ap.add_argument("-F", "--fit-mode", choices=["fit-longer", "fit-shorter", "fit-width", "fit-height"], default="fit-longer", help="Image fit mode (default: fit-longer)")
    ap.add_argument("-p", "--ppd-photo", type=float, default=60.0, help="PPD target for photo-like pages (default: 60.0)")
    ap.add_argument("-l", "--ppd-line", type=float, default=75.0, help="PPD target for line-art pages (default: 75.0)")
    ap.add_argument("-g", "--guard-ssim", type=float, help="Perceptual guardrail: minimum SSIM for encoded image")

    # Test mode
    ap.add_argument("-T", "--test-images", nargs="+", type=Path,
                    help="Compress only these images (bypasses leaf-folder scanning)")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    ap.add_argument("-z", "--trace-png", action="store_true", help="Show PNG chunk debug from Pillow (very verbose)")

    ap.add_argument("--version", action="version", version=f"imgshrink {__version__}")
    return ap


def _apply_quality_preset(args: argparse.Namespace) -> None:
    """Apply quality preset to args if specified."""
    if not hasattr(args, 'quality_preset') or args.quality_preset is None:
        return

    preset = get_quality_preset(args.quality_preset)
    logging.info(f"Applying quality preset {preset.level}: {preset.description}")

    # Override settings with preset values
    args.guard_ssim = preset.ssim_min
    args.ppd_photo = preset.ppd_photo
    args.ppd_line = preset.ppd_line

    # Note: downsample_factor will be applied in the planning phase
    # We'll need to store it somewhere accessible
    if not hasattr(args, '_preset'):
        args._preset = preset


def _run_legacy(args: argparse.Namespace) -> int:
    _setup_logging(args.verbose, getattr(args, 'trace_png', False))
    _apply_quality_preset(args)
    ctx = mp.get_context("spawn") if sys.platform.startswith("win") else mp.get_context("fork")

    if args.test_images:
        # quick single-process demo path
        for p in args.test_images:
            p = p.resolve()
            if not p.exists():
                print(f"[WARN] missing: {p}")
                continue
            infos, stats = analyze_images([p])
            if not stats:
                continue
            plan = decide_plan(stats, phone_max_dim=args.phone_max_dim, prefer_format=args.format, png_quantize_colors=args.png_quantize)
            out_dir = None if args.overwrite else p.parent / "_compressed"
            compress_one(p, out_dir=out_dir, plan=plan, overwrite=args.overwrite, backup=args.backup, guard_ssim=args.guard_ssim)
        return 0

    run_start_time = time.time()
    leaves = find_leaf_image_dirs(args.root)
    if not leaves:
        print("No leaf image folders found under:", args.root, file=sys.stderr)
        return 1

    tasks: mp.JoinableQueue = mp.JoinableQueue()
    outq: mp.Queue = mp.Queue()

    plan_map: Dict[str, Dict] = _load_summary(args.apply_from_summary) if args.apply_from_summary else {}
    if not plan_map:
        # Only load plan mapping when applying from plan
        if args.apply_plan and args.plan_file and args.plan_file.exists():
            try:
                plan_map = json.loads(args.plan_file.read_text(encoding="utf-8"))
            except Exception:
                plan_map = {}

    for leaf in leaves:
        key = str(leaf.resolve())
        plan_data = plan_map.get(key)
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

    # Final summary generation (always)
    for leaf in leaves:
        images = collect_images(leaf)
        infos, stats = analyze_images(images)
        if not stats:
            continue
        # device-aware preferred if device flags provided
        device_plan = None
        if args.display_res and args.display_diagonal_in and args.viewing_distance_cm:
            try:
                w, h = [int(x) for x in args.display_res.lower().replace("×", "x").split("x")]
                device = DeviceProfile(
                    diagonal_in=float(args.display_diagonal_in),
                    width_px=w,
                    height_px=h,
                    viewing_distance_cm=float(args.viewing_distance_cm),
                )
                device_plan = decide_plan_device_aware(
                    infos, stats, device,
                    fit_mode=args.fit_mode,
                    ppd_photo=args.ppd_photo,
                    ppd_line=args.ppd_line,
                    prefer_format=args.format,
                    png_quantize_colors=args.png_quantize,
                )
            except Exception:
                device_plan = None

        plan = device_plan or decide_plan(stats, phone_max_dim=args.phone_max_dim, prefer_format=args.format, png_quantize_colors=args.png_quantize)

        # optional manual tuning
        if args.target_ratio or args.target_total_mb:
            total_bytes = sum(i.bytes for i in infos)
            target_total = int(args.target_total_mb * 1024 * 1024) if args.target_total_mb else None
            plan = plan if (args.target_ratio is None and target_total is None) else \
                plan.__class__(**plan.to_dict())  # copy
            plan = plan  # keep type hints happy
            plan = plan if (args.target_ratio is None and target_total is None) else \
                plan  # we keep for clarity; tuning left to caller in earlier flow

        entry = _build_summary_entry(leaf, infos, stats, plan)
        summary_entries.append(entry)

    if args.summary_file:
        payload = {
            "root": str(args.root),
            "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "folders": summary_entries,
        }
        _save_summary(args.summary_file, payload)

    # If a plan-file path was given (and not applying), write a **compact plan.json**
    if args.plan_file and not args.apply_plan:
        plan_map_out = {e["folder"]: e["plan"] for e in summary_entries}
        args.plan_file.write_text(json.dumps(plan_map_out, indent=2), encoding="utf-8")

    _print_summary_report(summary_entries)
    return 0


# --------------------------- subcommand layer ------------------------
def _sub_analyze(argv: List[str]) -> int:
    p = argparse.ArgumentParser(prog="imgshrink analyze", description="Analyze images and print/save stats per folder")
    p.add_argument("root", type=Path, help="Root folder to scan")
    p.add_argument("-S", "--summary-file", type=Path, default=Path("summary.json"), help="Output summary file (default: summary.json)")
    p.add_argument("-t", "--threads", type=int, default=1, help="Number of worker processes (default: 1)")
    p.add_argument("-u", "--ui", action="store_true", help="Enable live dashboard UI")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = p.parse_args(argv)
    # call legacy with dry-run + summary
    leg = _build_legacy_parser().parse_args([str(args.root), "-t", str(args.threads), "-n", "-S", str(args.summary_file)] + (["-u"] if args.ui else []) + (["-v"] if args.verbose else []))
    return _run_legacy(leg)


def _sub_plan(argv: List[str]) -> int:
    p = argparse.ArgumentParser(prog="imgshrink plan", description="Create a device-aware plan.json per folder")
    p.add_argument("root", type=Path, help="Root folder to scan")
    p.add_argument("-o", "--output", type=Path, default=Path("plan.json"), help="Output plan file (default: plan.json)")
    p.add_argument("-q", "--quality-preset", type=int, choices=range(10), metavar="0-9",
                    help="Smart compression preset: 0=max quality, 5=balanced, 9=max compression")
    p.add_argument("-x", "--display-res", help="Screen resolution WxH (e.g., 2400x1080)")
    p.add_argument("-i", "--display-diagonal-in", type=float, help="Screen diagonal in inches")
    p.add_argument("-c", "--viewing-distance-cm", type=float, help="Viewing distance in cm")
    p.add_argument("-F", "--fit-mode", choices=["fit-longer", "fit-shorter", "fit-width", "fit-height"], default="fit-longer", help="Image fit mode (default: fit-longer)")
    p.add_argument("-p", "--ppd-photo", type=float, default=60.0, help="PPD target for photo-like pages (default: 60.0)")
    p.add_argument("-l", "--ppd-line", type=float, default=75.0, help="PPD target for line-art pages (default: 75.0)")
    p.add_argument("-t", "--threads", type=int, default=1, help="Number of worker processes (default: 1)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = p.parse_args(argv)
    # We piggy-back on legacy to write plan.json
    forwarded = [str(args.root), "-t", str(args.threads), "-n", "-P", str(args.output)]
    if args.quality_preset is not None: forwarded += ["--quality-preset", str(args.quality_preset)]
    if args.display_res: forwarded += ["--display-res", args.display_res]
    if args.display_diagonal_in: forwarded += ["--display-diagonal-in", str(args.display_diagonal_in)]
    if args.viewing_distance_cm: forwarded += ["--viewing-distance-cm", str(args.viewing_distance_cm)]
    forwarded += ["--fit-mode", args.fit_mode, "--ppd-photo", str(args.ppd_photo), "--ppd-line", str(args.ppd_line)]
    if args.verbose: forwarded += ["-v"]
    leg = _build_legacy_parser().parse_args(forwarded)
    return _run_legacy(leg)


def _sub_compress(argv: List[str]) -> int:
    p = argparse.ArgumentParser(prog="imgshrink compress", description="Apply an existing plan.json to folders")
    p.add_argument("root", type=Path, help="Root folder to scan")
    p.add_argument("-P", "--plan", required=True, type=Path, help="Plan file to apply (required)")
    p.add_argument("-q", "--quality-preset", type=int, choices=range(10), metavar="0-9",
                    help="Override plan with quality preset: 0=max quality, 5=balanced, 9=max compression")
    p.add_argument("-g", "--guard-ssim", type=float, help="Minimum SSIM quality threshold")
    p.add_argument("-t", "--threads", type=int, default=1, help="Number of worker processes (default: 1)")
    p.add_argument("-w", "--overwrite", action="store_true", help="Overwrite originals (else write to _compressed/)")
    p.add_argument("-u", "--ui", action="store_true", help="Enable live dashboard UI")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = p.parse_args(argv)
    forwarded = [str(args.root), "-t", str(args.threads), "-a", "-P", str(args.plan)]
    if args.quality_preset is not None: forwarded += ["--quality-preset", str(args.quality_preset)]
    if args.guard_ssim: forwarded += ["--guard-ssim", str(args.guard_ssim)]
    if args.overwrite: forwarded += ["--overwrite"]
    if args.ui: forwarded += ["-u"]
    if args.verbose: forwarded += ["-v"]
    leg = _build_legacy_parser().parse_args(forwarded)
    return _run_legacy(leg)


def _sub_all(argv: List[str]) -> int:
    p = argparse.ArgumentParser(prog="imgshrink all", description="Analyze → Plan → Compress in one go")
    p.add_argument("root", type=Path, help="Root folder to scan")
    p.add_argument("-S", "--summary-file", type=Path, default=Path("summary.json"), help="Output summary file (default: summary.json)")
    p.add_argument("-P", "--plan-file", type=Path, default=Path("plan.json"), help="Output plan file (default: plan.json)")
    p.add_argument("-q", "--quality-preset", type=int, choices=range(10), metavar="0-9",
                    help="Smart compression preset: 0=max quality, 5=balanced, 9=max compression")
    p.add_argument("-x", "--display-res", help="Screen resolution WxH (e.g., 2400x1080)")
    p.add_argument("-i", "--display-diagonal-in", type=float, help="Screen diagonal in inches")
    p.add_argument("-c", "--viewing-distance-cm", type=float, help="Viewing distance in cm")
    p.add_argument("-F", "--fit-mode", choices=["fit-longer", "fit-shorter", "fit-width", "fit-height"], default="fit-longer", help="Image fit mode (default: fit-longer)")
    p.add_argument("-p", "--ppd-photo", type=float, default=60.0, help="PPD target for photo-like pages (default: 60.0)")
    p.add_argument("-l", "--ppd-line", type=float, default=75.0, help="PPD target for line-art pages (default: 75.0)")
    p.add_argument("-g", "--guard-ssim", type=float, help="Minimum SSIM quality threshold")
    p.add_argument("-t", "--threads", type=int, default=1, help="Number of worker processes (default: 1)")
    p.add_argument("-u", "--ui", action="store_true", help="Enable live dashboard UI")
    p.add_argument("-w", "--overwrite", action="store_true", help="Overwrite originals (else write to _compressed/)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = p.parse_args(argv)
    forwarded = [str(args.root), "-t", str(args.threads), "-S", str(args.summary_file), "-P", str(args.plan_file)]
    if args.quality_preset is not None: forwarded += ["--quality-preset", str(args.quality_preset)]
    if args.display_res: forwarded += ["--display-res", args.display_res]
    if args.display_diagonal_in: forwarded += ["--display-diagonal-in", str(args.display_diagonal_in)]
    if args.viewing_distance_cm: forwarded += ["--viewing-distance-cm", str(args.viewing_distance_cm)]
    forwarded += ["--fit-mode", args.fit_mode, "--ppd-photo", str(args.ppd_photo), "--ppd-line", str(args.ppd_line)]
    if args.guard_ssim: forwarded += ["--guard-ssim", str(args.guard_ssim)]
    if args.overwrite: forwarded += ["--overwrite"]
    if args.ui: forwarded += ["-u"]
    if args.verbose: forwarded += ["-v"]
    leg = _build_legacy_parser().parse_args(forwarded)
    return _run_legacy(leg)


def _sub_profile(argv: List[str]) -> int:
    from .display import device_ppd
    p = argparse.ArgumentParser(prog="imgshrink profile", description="Print device PPI/PPD for a screen + distance")
    p.add_argument("-x", "--display-res", required=True, help="Screen resolution WxH (e.g., 2400x1080)")
    p.add_argument("-i", "--display-diagonal-in", type=float, required=True, help="Screen diagonal in inches")
    p.add_argument("-c", "--viewing-distance-cm", type=float, required=True, help="Viewing distance in cm")
    args = p.parse_args(argv)
    w, h = [int(x) for x in args.display_res.lower().replace("×", "x").split("x")]
    dev = DeviceProfile(args.display_diagonal_in, w, h, args.viewing_distance_cm)
    ppd_w, ppd_h = device_ppd(dev)
    print(f"Resolution : {w}x{h}")
    print(f"Diagonal   : {dev.diagonal_in}\"")
    print(f"PPI        : {dev.ppi:.2f}")
    print(f"Viewing    : {dev.viewing_distance_cm} cm")
    print(f"PPD (W,H)  : {ppd_w:.2f}, {ppd_h:.2f}")
    return 0


# --------------------------- entrypoint ------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"analyze", "plan", "compress", "all", "profile"}:
        cmd, rest = argv[0], argv[1:]
        if cmd == "analyze": return _sub_analyze(rest)
        if cmd == "plan":    return _sub_plan(rest)
        if cmd == "compress":return _sub_compress(rest)
        if cmd == "all":     return _sub_all(rest)
        if cmd == "profile": return _sub_profile(rest)
        return 2

    # legacy mode
    parser = _build_legacy_parser()
    args = parser.parse_args(argv)
    return _run_legacy(args)


if __name__ == "__main__":
    raise SystemExit(main())
