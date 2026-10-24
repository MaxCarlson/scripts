"""
Command-line interface for videocompress.
Follows scripts repository rules: every user-facing option has short and long forms.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Sequence

from . import __version__
from .capabilities import probe_capabilities
from .contracts import (
    CompressionReport,
    EligibilityDecision,
    Prediction,
    SourceIdentity,
    VideoAsset,
    VideoEstimationPlan,
    VideoRecipe,
    VideoStream,
)
from .eligibility import parse_bitrate, parse_duration, parse_resolution, parse_size
from .events import ProgressEmitter
from .inventory import InventoryReport, InventoryStore, scan_inventory
from .plan import build_estimation_plan
from .predictor import FeasibilityAssessment, evaluate_feasibility
from .recipes import DEFAULT_RECIPE_ID, STANDARD_RECIPES, get_recipe, list_standard_recipes
from .workspace import resolve_workspace


def _format_bytes(num_bytes: int | float | None) -> str:
    """Format byte counts into human-readable binary units (KiB, MiB, GiB)."""
    if num_bytes is None:
        return "N/A"
    b = float(num_bytes)
    if abs(b) >= 1024**3:
        return f"{b / (1024**3):.2f} GiB"
    elif abs(b) >= 1024**2:
        return f"{b / (1024**2):.1f} MiB"
    elif abs(b) >= 1024:
        return f"{b / 1024:.1f} KiB"
    return f"{int(b)} B"


def _format_bps(bps: int | float | None) -> str:
    """Format bitrates into human-readable metric units (kbps, Mbps)."""
    if bps is None:
        return "unknown"
    b = float(bps)
    if b >= 1_000_000:
        return f"{b / 1_000_000:.2f} Mbps"
    elif b >= 1_000:
        return f"{b / 1_000:.0f} kbps"
    return f"{int(b)} bps"


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level vcompress argument parser."""
    # Common base parser for flags available globally and inside subcommands
    common_base = argparse.ArgumentParser(add_help=False)
    common_base.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable verbose diagnostic logging to stderr.",
    )
    common_base.add_argument(
        "-J",
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Output structured JSON results to stdout.",
    )
    common_base.add_argument(
        "-N",
        "--no-ui",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable interactive terminal UI/progress widgets.",
    )

    parser = argparse.ArgumentParser(
        prog="vcompress",
        description="Estimation-first media-aware video compression and preservation backend.",
        parents=[common_base],
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program version and exit.",
    )

    subparsers = parser.add_subparsers(
        dest="operation",
        title="Operations",
        description="Available video compression operations",
        required=True,
    )

    # 1. capabilities
    cap_parser = subparsers.add_parser(
        "capabilities",
        parents=[common_base],
        help="Probe and report host FFmpeg, NVENC, and filter capabilities.",
    )
    cap_parser.add_argument(
        "-c",
        "--check-encode",
        action="store_true",
        default=False,
        help="Perform a bounded smoke encode to verify hardware encoder functionality.",
    )

    # Common parent parser for target-scoped operations
    common_target = argparse.ArgumentParser(add_help=False)
    common_target.add_argument(
        "-i",
        "--input",
        dest="input_target",
        required=True,
        help="Target media file or directory to process.",
    )
    common_target.add_argument(
        "-I",
        "--workspace",
        dest="workspace_root",
        default=None,
        help="External workspace root directory (must reside outside input media tree).",
    )

    # Common filter parent parser
    common_filters = argparse.ArgumentParser(add_help=False)
    common_filters.add_argument(
        "-B",
        "--min-video-bitrate",
        dest="min_video_bitrate",
        default=None,
        help="Minimum video-stream bitrate (e.g. 4M, 2500k, 5000000). Excludes files below threshold.",
    )
    common_filters.add_argument(
        "-R",
        "--min-resolution",
        dest="min_resolution",
        default=None,
        help="Minimum video resolution in WIDTHxHEIGHT format (e.g. 1920x1080).",
    )
    common_filters.add_argument(
        "-S",
        "--min-size",
        dest="min_size",
        default=None,
        help="Minimum container file size (e.g. 100M, 1G).",
    )
    common_filters.add_argument(
        "-D",
        "--min-duration",
        dest="min_duration",
        default=None,
        help="Minimum media duration in seconds (e.g. 60, 300).",
    )

    # Common plan selector
    common_plan = argparse.ArgumentParser(add_help=False)
    common_plan.add_argument(
        "-r",
        "--plan-id",
        dest="plan_id",
        default=None,
        help="Identifier of the frozen estimation plan to execute.",
    )

    # 2. inventory
    inv_parser = subparsers.add_parser(
        "inventory",
        parents=[common_base, common_target, common_filters],
        help="Inventory media library metadata (FFprobe, stream layout, eligibility) without encoding.",
    )
    inv_parser.add_argument(
        "-d",
        "--depth",
        dest="inventory_depth",
        choices=["files", "probe", "deep"],
        default="probe",
        help="Inventory depth: 'files' (stat only), 'probe' (FFprobe streams, default), 'deep' (packet accounting).",
    )
    inv_parser.add_argument(
        "-f",
        "--force",
        "--force-refresh",
        dest="force_refresh",
        action="store_true",
        help="Force re-probing of all files, ignoring cached stat fingerprints.",
    )

    # 3. plan
    plan_parser = subparsers.add_parser(
        "plan",
        parents=[common_base, common_target, common_filters],
        help="Freeze eligible source population, candidate recipes, and sampling windows into an immutable plan.",
    )
    plan_parser.add_argument(
        "-c",
        "--codec",
        dest="target_codec",
        choices=["av1", "hevc", "h264"],
        default="av1",
        help="Target video codec family (default: av1).",
    )
    plan_parser.add_argument(
        "-p",
        "--preset",
        dest="encoder_preset",
        default="p5",
        help="Target encoder speed/quality preset (default: p5 for nvenc).",
    )
    plan_parser.add_argument(
        "-e",
        "--recipe",
        dest="recipe_id",
        default=DEFAULT_RECIPE_ID,
        help=f"Target standard recipe ID (default: {DEFAULT_RECIPE_ID}). Choices: {', '.join(sorted(STANDARD_RECIPES.keys()))}.",
    )
    plan_parser.add_argument(
        "-y",
        "--strategy",
        dest="sampling_strategy",
        choices=["uniform_3x20", "uniform_5x20", "uniform_3x10", "uniform_5x10", "none"],
        default="uniform_3x20",
        help="Deterministic temporal sampling schedule for trial encoding (default: uniform_3x20).",
    )
    plan_parser.add_argument(
        "-f",
        "--force",
        "--force-refresh",
        dest="force_refresh",
        action="store_true",
        help="Force re-probing of all files, ignoring cached stat fingerprints.",
    )

    # 4. estimate
    est_parser = subparsers.add_parser(
        "estimate",
        parents=[common_base, common_target, common_filters, common_plan],
        help="Estimate compression feasibility, file size, and potential savings.",
    )
    est_parser.add_argument(
        "-e",
        "--recipe",
        dest="recipe_id",
        default=DEFAULT_RECIPE_ID,
        help=f"Target standard recipe ID (default: {DEFAULT_RECIPE_ID}).",
    )
    est_parser.add_argument(
        "-E",
        "--estimate-tier",
        dest="estimate_tier",
        choices=["metadata", "features", "sampled", "calibrated"],
        default="metadata",
        help="Estimation tier: 'metadata' (zero-encode prior, default), 'sampled' (bounded trial encodes), etc.",
    )
    est_parser.add_argument(
        "-P",
        "--min-savings-pct",
        dest="min_savings_pct",
        type=float,
        default=None,
        help="Minimum required percentage savings (e.g. 20.0).",
    )
    est_parser.add_argument(
        "-s",
        "--min-savings-bytes",
        dest="min_savings_bytes",
        default=None,
        help="Minimum required byte savings (e.g. '50M', 50000000).",
    )
    est_parser.add_argument(
        "-p",
        "--savings-policy",
        dest="savings_policy",
        choices=["both", "either"],
        default="both",
        help="Savings policy when both percentage and bytes are set: 'both' (%% AND bytes) or 'either' (%% OR bytes).",
    )
    est_parser.add_argument(
        "-f",
        "--force",
        "--force-refresh",
        dest="force_refresh",
        action="store_true",
        help="Force re-probing of all files, ignoring cached stat fingerprints.",
    )
    est_parser.add_argument(
        "-M",
        "--max-time",
        dest="max_time",
        default=None,
        help="Maximum wall-time budget for new trial encoding (e.g. 5m, 300s).",
    )
    est_parser.add_argument(
        "-T",
        "--max-trials",
        dest="max_trials",
        type=int,
        default=None,
        help="Maximum number of new sample encoding trials allowed.",
    )

    # 5. analyze
    subparsers.add_parser(
        "analyze",
        parents=[common_base, common_target, common_plan],
        help="Execute sample trials across multiple candidate recipes for comparison.",
    )

    # 6. compare
    subparsers.add_parser(
        "compare",
        parents=[common_base, common_target, common_plan],
        help="Compare measured compression savings and quality metrics across candidate recipes.",
    )

    # 7. preview
    prev_parser = subparsers.add_parser(
        "preview",
        parents=[common_base, common_target, common_plan],
        help="Generate side-by-side or sequential video clips with manifest for visual inspection.",
    )
    prev_parser.add_argument(
        "-n",
        "--num-clips",
        dest="num_clips",
        type=int,
        default=3,
        help="Number of preview clips to generate per source (default: 3).",
    )

    # 8. apply
    app_parser = subparsers.add_parser(
        "apply",
        parents=[common_base, common_target, common_plan],
        help="Execute authorized video transcoding and publication under media safety contracts.",
    )
    app_parser.add_argument(
        "-w",
        "--write",
        dest="allow_write",
        action="store_true",
        default=False,
        help="Authorize executing live encoding work instead of dry-run inspection.",
    )
    app_parser.add_argument(
        "-L",
        "--allow-lossy",
        dest="allow_lossy",
        action="store_true",
        default=False,
        help="Explicit consent to replace or create lossy compressed outputs.",
    )
    app_parser.add_argument(
        "-o",
        "--output-root",
        dest="output_root",
        default=None,
        help="External output directory tree for published files (source files remain untouched).",
    )

    # 9. recover
    rec_parser = subparsers.add_parser(
        "recover",
        parents=[common_base, common_target],
        help="Inspect or repair interrupted/failed compression jobs.",
    )
    rec_parser.add_argument(
        "-w",
        "--write",
        dest="allow_write",
        action="store_true",
        default=False,
        help="Authorize writing changes to repair or clean up jobs (default is read-only inspection).",
    )
    rec_parser.add_argument(
        "-t",
        "--confirm-token",
        dest="confirm_token",
        default=None,
        help="Scoped confirmation token required for irreversible recovery actions.",
    )

    return parser


def run_capabilities(args: argparse.Namespace) -> int:
    """Inspect and report FFmpeg/GPU capabilities."""
    caps = probe_capabilities(check_encode=getattr(args, "check_encode", False))
    if getattr(args, "json", False):
        print(json.dumps(caps, indent=2))
    else:
        print("=== videocompress Host Capabilities ===")
        print(f"FFmpeg binary: {caps.get('ffmpeg_path', 'Not found')}")
        print(f"FFmpeg version: {caps.get('ffmpeg_version', 'Unknown')}")
        print(f"FFprobe binary: {caps.get('ffprobe_path', 'Not found')}")
        print(f"NVIDIA GPU: {caps.get('gpu_name', 'None detected')}")
        print(f"Hardware Encoders: {', '.join(caps.get('hardware_encoders', []))}")
        print(f"VMAF Support: {caps.get('vmaf_available', False)}")
        print(f"Curses UI Available: {caps.get('curses_available', False)}")
    return 0


def run_inventory(args: argparse.Namespace) -> int:
    """Execute inventory scan and report results."""
    is_json = getattr(args, "json", False)
    no_ui = getattr(args, "no_ui", False)
    run_id = f"inv-{int(time.time())}"

    def cli_sink(event: Any) -> None:
        if not is_json and not no_ui:
            if event.message:
                print(f"[{event.phase}] {event.message}", file=sys.stderr)

    emitter = ProgressEmitter(run_id=run_id, sink=cli_sink)

    report = scan_inventory(
        target=args.input_target,
        workspace_root=getattr(args, "workspace_root", None),
        min_video_bitrate=getattr(args, "min_video_bitrate", None),
        min_resolution=getattr(args, "min_resolution", None),
        min_size=getattr(args, "min_size", None),
        min_duration=getattr(args, "min_duration", None),
        inventory_depth=getattr(args, "inventory_depth", "probe"),
        emitter=emitter,
        force_refresh=getattr(args, "force_refresh", False),
    )

    if is_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        gib_total = report.total_bytes / (1024**3)
        gib_eligible = report.eligible_bytes / (1024**3)
        print("=== videocompress Inventory Report ===")
        print(f"Target: {report.target}")
        print(f"Workspace: {report.workspace_root}")
        print(f"Depth: {report.inventory_depth}")
        print(f"Total Sources: {report.total_sources} ({gib_total:.2f} GiB)")
        print(f"Eligible Sources: {report.eligible_sources} ({gib_eligible:.2f} GiB)")
        print(f"Excluded Sources: {report.excluded_sources}")
        print(f"Unknown Sources: {report.unknown_sources}")
        print(f"Unsupported Sources: {report.unsupported_sources}")
        print(f"Failed Sources: {report.failed_sources}")
        print(f"Cache Hits: {report.cache_hits} | Misses: {report.cache_misses} | Pruned: {report.pruned_sources}")
        print(f"Scan Duration: {report.elapsed_seconds:.2f}s")
    return 0


def run_plan(args: argparse.Namespace) -> int:
    """Execute estimation planning and candidate freezing."""
    recipe = get_recipe(getattr(args, "recipe_id", None))

    plan = build_estimation_plan(
        target=args.input_target,
        recipes=[recipe],
        workspace_root=getattr(args, "workspace_root", None),
        min_video_bitrate=getattr(args, "min_video_bitrate", None),
        min_resolution=getattr(args, "min_resolution", None),
        min_size=getattr(args, "min_size", None),
        min_duration=getattr(args, "min_duration", None),
        sampling_strategy=getattr(args, "sampling_strategy", "uniform_3x20"),
        force_refresh=getattr(args, "force_refresh", False),
    )

    if getattr(args, "json", False):
        print(json.dumps(plan.to_dict(), indent=2))
    else:
        print("=== videocompress Estimation Plan ===")
        print(f"Plan ID: {plan.plan_id}")
        print(f"Target Scope: {plan.target_scope}")
        print(f"Eligible Sources: {len(plan.source_ids)}")
        print(f"Target Recipe: {recipe.recipe_id} ({recipe.encoder}, cq={recipe.rate_control_value}, {recipe.preset})")
        print(f"Sampling Windows: {len(plan.sampling_windows)} scheduled intervals")
        print(f"Artifact Saved: {plan.workspace_parent}/plans/{plan.plan_id}.json")
    return 0


def run_estimate(args: argparse.Namespace) -> int:
    """Execute feasibility screening and file-size estimation."""
    is_json = getattr(args, "json", False)
    tier = getattr(args, "estimate_tier", "metadata")
    if tier != "metadata":
        sys.stderr.write(
            f"Note: Tier '{tier}' requested. Metadata feasibility screening will run first.\n"
        )

    # 1. Resolve workspace and inventory
    ws = resolve_workspace(args.input_target, parent=getattr(args, "workspace_root", None))
    store = InventoryStore(ws.inventory_db)

    # Parse savings thresholds
    min_savings_pct = getattr(args, "min_savings_pct", None)
    min_savings_bytes = parse_size(getattr(args, "min_savings_bytes", None))
    savings_policy = getattr(args, "savings_policy", "both")

    # Resolve recipe
    recipe_id = getattr(args, "recipe_id", None) or DEFAULT_RECIPE_ID
    recipe = get_recipe(recipe_id)

    # Gather target assets
    plan_id = getattr(args, "plan_id", None)
    if plan_id:
        plan_file = ws.plans_dir / f"{plan_id}.json"
        if not plan_file.exists():
            sys.stderr.write(f"Error: Specified plan file does not exist: {plan_file}\n")
            return 1
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
        target_sids = set(plan_data.get("source_ids", []))
        all_stored = store.list_assets()
        assets_to_assess = [a for a in all_stored if a.source_id in target_sids]
    else:
        # Run/load inventory scan
        inv_report = scan_inventory(
            target=args.input_target,
            workspace_root=ws.root,
            min_video_bitrate=getattr(args, "min_video_bitrate", None),
            min_resolution=getattr(args, "min_resolution", None),
            min_size=getattr(args, "min_size", None),
            min_duration=getattr(args, "min_duration", None),
            inventory_depth="probe",
            force_refresh=getattr(args, "force_refresh", False),
        )
        eligible_sids = {
            rec["source_id"]
            for rec in inv_report.per_source_records
            if rec.get("eligibility", {}).get("status") == "eligible"
        }
        all_stored = store.list_assets()
        assets_to_assess = [a for a in all_stored if a.source_id in eligible_sids]

    # 2. Evaluate feasibility for each asset
    assessments: list[FeasibilityAssessment] = []
    for asset in assets_to_assess:
        fa = evaluate_feasibility(
            asset=asset,
            recipe=recipe,
            min_savings_pct=min_savings_pct,
            min_savings_bytes=min_savings_bytes,
            savings_policy=savings_policy,
        )
        assessments.append(fa)

    # 3. Aggregate statistics
    total_sources = len(assessments)
    promising_count = sum(1 for a in assessments if a.decision == "eligible_promising")
    uncertain_count = sum(1 for a in assessments if a.decision == "eligible_uncertain")
    unlikely_count = sum(1 for a in assessments if a.decision in ("eligible_unlikely", "quality_floor_violation"))
    quality_floor_count = sum(1 for a in assessments if a.decision == "quality_floor_violation")
    infeasible_count = sum(1 for a in assessments if a.decision == "infeasible")
    abstained_count = sum(1 for a in assessments if a.decision == "abstained")

    total_source_bytes = sum(a.source_bytes for a in assessments)
    p10_total_saved = sum(a.p10_savings_bytes for a in assessments)
    p50_total_saved = sum(a.p50_savings_bytes for a in assessments)
    p90_total_saved = sum(a.p90_savings_bytes for a in assessments)

    conservative_saved = p90_total_saved
    expected_saved = p50_total_saved
    optimistic_saved = p10_total_saved

    if is_json:
        out_dict = {
            "schema_version": 1,
            "operation": "estimate",
            "tier": "metadata",
            "recipe": recipe.to_dict(),
            "target": str(args.input_target),
            "summary": {
                "total_evaluated_sources": total_sources,
                "promising_sources": promising_count,
                "uncertain_sources": uncertain_count,
                "unlikely_sources": unlikely_count,
                "quality_floor_violations": quality_floor_count,
                "infeasible_sources": infeasible_count,
                "abstained_sources": abstained_count,
                "total_source_bytes": total_source_bytes,
                "predicted_savings_bytes": {
                    "conservative": conservative_saved,
                    "expected": expected_saved,
                    "optimistic": optimistic_saved,
                    "p10": p10_total_saved,
                    "p50": p50_total_saved,
                    "p90": p90_total_saved,
                },
                "predicted_savings_pct": {
                    "conservative": round((conservative_saved / total_source_bytes * 100.0) if total_source_bytes > 0 else 0.0, 2),
                    "expected": round((expected_saved / total_source_bytes * 100.0) if total_source_bytes > 0 else 0.0, 2),
                    "optimistic": round((optimistic_saved / total_source_bytes * 100.0) if total_source_bytes > 0 else 0.0, 2),
                },
            },
            "per_source_assessments": [a.to_dict() for a in assessments],
            "calibration_caveat": (
                "Scenario projections are heuristic metadata assumptions, not statistically calibrated probability distributions. "
                "Empirical sample encoding (Stage 4) is required for reliable decision boundaries. "
                "A lower bitrate does not guarantee preserved perceptual quality."
            ),
        }
        print(json.dumps(out_dict, indent=2))
    else:
        print("=== videocompress Feasibility & Prediction Report (Tier 1 Metadata) ===")
        print(f"Target: {args.input_target}")
        print(f"Target Recipe: {recipe.recipe_id} ({recipe.encoder}, cq={recipe.rate_control_value})")
        if min_savings_pct or min_savings_bytes:
            print(f"Savings Criteria: min {min_savings_pct or 0}% {savings_policy.upper()} {_format_bytes(min_savings_bytes or 0)}")
        print(f"Evaluated Assets: {total_sources} ({_format_bytes(total_source_bytes)})")
        print(f"  Promising: {promising_count} | Uncertain: {uncertain_count} | Unlikely/Quality Risks: {unlikely_count}")
        print(f"  Infeasible: {infeasible_count} | Abstained: {abstained_count}")
        print(f"Predicted Library Savings: {_format_bytes(conservative_saved)} .. {_format_bytes(optimistic_saved)} [expected: {_format_bytes(expected_saved)}]")
        print("-" * 88)

        # Per source summary
        for a in assessments:
            prov_label = "" if a.bitrate_provenance == "ffprobe_stream" else f" ({a.bitrate_provenance})"
            vbitrate_str = _format_bps(a.video_bitrate_bps) + prov_label
            print(f"Asset [{a.source_id[:8]}]: {_format_bytes(a.source_bytes)} -> {_format_bytes(a.p50_output_bytes)} (exp) [{a.p50_savings_pct:.1f}% savings]")
            print(f"  Video: {vbitrate_str} | Non-Video: {_format_bytes(a.breakdown.total_nonvideo_bytes)}")
            print(f"  Plausible Range: {_format_bytes(a.p10_output_bytes)} .. {_format_bytes(a.p90_output_bytes)} | Decision: [{a.decision.upper()}] (conf: {a.confidence})")
            if a.reconciliation.unaccounted_container_bytes != 0:
                print(f"  * Size Reconciliation: {a.reconciliation.unaccounted_container_bytes:,} unaccounted container bytes ({a.reconciliation.unaccounted_ratio:.1%})")
            if a.rejection_reasons:
                for r in a.rejection_reasons:
                    print(f"  * Rejection: {r}")
            if a.warnings:
                for w in a.warnings:
                    print(f"  ! Warning: {w}")

        print("-" * 88)
        print("Notice: Zero encodes performed. Scenario predictions are exploratory heuristic assumptions and require empirical trial calibration.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for vcompress."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.operation == "capabilities":
        return run_capabilities(args)
    elif args.operation == "inventory":
        return run_inventory(args)
    elif args.operation == "plan":
        return run_plan(args)
    elif args.operation == "estimate":
        return run_estimate(args)

    # Staged implementation placeholder for other operations
    if getattr(args, "json", False):
        print(json.dumps({
            "operation": args.operation,
            "status": "staged",
            "message": f"Operation '{args.operation}' dispatched successfully (Stage 0 placeholder).",
        }, indent=2))
    else:
        print(f"videocompress {__version__}: operation '{args.operation}' dispatched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
