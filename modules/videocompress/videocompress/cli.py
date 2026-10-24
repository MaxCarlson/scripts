"""
Command-line interface for videocompress.
Follows scripts repository rules: every user-facing option has short and long forms.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from . import __version__
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


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level vcompress argument parser."""
    # Common base parser for flags available globally and inside subcommands
    common_base = argparse.ArgumentParser(add_help=False)
    common_base.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose diagnostic logging to stderr.",
    )
    common_base.add_argument(
        "-J",
        "--json",
        action="store_true",
        default=False,
        help="Output structured JSON results to stdout.",
    )
    common_base.add_argument(
        "-N",
        "--no-ui",
        action="store_true",
        default=False,
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
        help="Perform a bounded 1-second smoke encode to verify hardware encoder functionality.",
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

    # Filter parent parser
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

    # Common plan selector
    common_plan = argparse.ArgumentParser(add_help=False)
    common_plan.add_argument(
        "-r",
        "--plan-id",
        dest="plan_id",
        required=True,
        help="Identifier of the frozen estimation plan to execute.",
    )

    # 4. estimate
    est_parser = subparsers.add_parser(
        "estimate",
        parents=[common_base, common_target, common_plan],
        help="Estimate compression feasibility, file size, and potential savings.",
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
        help="Transcode and publish candidate files under journaled media safety contracts.",
    )
    app_parser.add_argument(
        "-w",
        "--write",
        dest="allow_write",
        action="store_true",
        default=False,
        help="Authorize actual disk writes for publication (omitted means dry-run).",
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
    from .capabilities import probe_capabilities

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
    import time
    from .events import ProgressEmitter
    from .inventory import scan_inventory

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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for vcompress."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.operation == "capabilities":
        return run_capabilities(args)
    elif args.operation == "inventory":
        return run_inventory(args)

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
