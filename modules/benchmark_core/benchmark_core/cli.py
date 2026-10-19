"""
Command-line interface for benchmark_core.

Subcommands:
- report: Load a run directory, summarize, and display or write reports (JSON, CSV, MD)
- compare: Compare two benchmark runs and display or write delta reports
- import: Import external benchmark results (e.g., Hyperfine) into standard benchmark_core format
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Optional, Sequence

from .compare import compare_runs, render_comparison_md
from .reporting import generate_reports
from .stats import summarize
from .storage import load_run


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser with short and long flags for every option."""
    parser = argparse.ArgumentParser(
        prog="benchmark-core",
        description="Lightweight, reusable benchmarking results normalization, aggregation, and reporting.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Subcommand: report
    report_parser = subparsers.add_parser("report", help="Summarize a benchmark run and generate reports")
    report_parser.add_argument(
        "-i", "--input-dir",
        default=".",
        help="Path to the benchmark run directory containing run.json and trials.jsonl (default: current directory)",
    )
    report_parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Destination directory to write derived reports (defaults to input directory)",
    )
    report_parser.add_argument(
        "-w", "--write",
        action="store_true",
        help="Write summary.json, summary.csv, and report.md to disk (default is read-only)",
    )
    report_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress console Markdown preview",
    )
    report_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed logging output",
    )

    # Subcommand: compare
    compare_parser = subparsers.add_parser("compare", help="Compare two benchmark runs")
    compare_parser.add_argument(
        "-b", "--baseline",
        required=True,
        help="Path to baseline run directory",
    )
    compare_parser.add_argument(
        "-c", "--candidate",
        required=True,
        help="Path to candidate run directory",
    )
    compare_parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Destination directory to save comparison report",
    )
    compare_parser.add_argument(
        "-w", "--write",
        action="store_true",
        help="Write comparison.md and comparison.json to disk (default is read-only)",
    )
    compare_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress console Markdown preview",
    )
    compare_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed logging output",
    )

    # Subcommand: import
    import_parser = subparsers.add_parser("import", help="Import external benchmark results into benchmark_core")
    import_parser.add_argument(
        "-f", "--format",
        required=True,
        choices=["hyperfine"],
        help="Source benchmark format to import",
    )
    import_parser.add_argument(
        "-i", "--input-file",
        required=True,
        help="Path to external benchmark export file",
    )
    import_parser.add_argument(
        "-o", "--output-dir",
        required=True,
        help="Directory to write imported run.json and trials.jsonl",
    )
    import_parser.add_argument(
        "-s", "--suite-id",
        default="hyperfine-benchmark",
        help="Suite identifier for the imported run",
    )
    import_parser.add_argument(
        "-w", "--write",
        action="store_true",
        help="Write imported records to disk (default is dry-run validation)",
    )
    import_parser.add_argument(
        "-O", "--overwrite",
        action="store_true",
        help="Authorize replacing existing run.json and trials.jsonl in output-dir",
    )
    import_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed logging output",
    )

    return parser


def handle_report(args: argparse.Namespace) -> int:
    """Handle the 'report' subcommand."""
    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"Error: Input directory {input_dir} does not exist.", file=sys.stderr)
        return 1

    try:
        run_info, trials = load_run(input_dir)
    except Exception as exc:
        print(f"Error loading benchmark run from {input_dir}: {exc}", file=sys.stderr)
        return 1

    summary = summarize(run_info, trials)
    out_dir = Path(args.output_dir) if args.output_dir else input_dir

    reports = generate_reports(summary, output_dir=out_dir, write=args.write)

    if not args.quiet:
        print(reports["report.md"])

    if args.write:
        print(f"Successfully generated summary.json, summary.csv, and report.md in {out_dir}")

    return 0


def handle_compare(args: argparse.Namespace) -> int:
    """Handle the 'compare' subcommand."""
    base_dir = Path(args.baseline)
    cand_dir = Path(args.candidate)

    if not base_dir.exists():
        print(f"Error: Baseline directory {base_dir} does not exist.", file=sys.stderr)
        return 1
    if not cand_dir.exists():
        print(f"Error: Candidate directory {cand_dir} does not exist.", file=sys.stderr)
        return 1

    try:
        base_run, base_trials = load_run(base_dir)
        cand_run, cand_trials = load_run(cand_dir)
    except Exception as exc:
        print(f"Error loading runs for comparison: {exc}", file=sys.stderr)
        return 1

    base_summary = summarize(base_run, base_trials)
    cand_summary = summarize(cand_run, cand_trials)

    comparison = compare_runs(base_summary, cand_summary)
    md_content = render_comparison_md(comparison)

    if not args.quiet:
        print(md_content)

    if args.write:
        out_dir = Path(args.output_dir) if args.output_dir else cand_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "comparison.md").write_text(md_content, encoding="utf-8")
        (out_dir / "comparison.json").write_text(comparison.to_json(), encoding="utf-8")
        print(f"Successfully wrote comparison.md and comparison.json to {out_dir}")

    return 0


def handle_import(args: argparse.Namespace) -> int:
    """Handle the 'import' subcommand (prepared for Phase 4 importer)."""
    input_file = Path(args.input_file)
    if not input_file.exists():
        print(f"Error: Input file {input_file} does not exist.", file=sys.stderr)
        return 1

    if args.format == "hyperfine":
        try:
            from .importers.hyperfine import import_hyperfine
            run_info, trials = import_hyperfine(
                input_file=input_file,
                suite_id=args.suite_id,
                output_dir=Path(args.output_dir) if args.write else None,
                write=args.write,
                overwrite=args.overwrite,
            )
            print(
                f"Successfully parsed Hyperfine benchmark: {len(run_info.variants)} variants, "
                f"{len(trials)} trials."
            )
            if args.write:
                print(f"Wrote run.json and trials.jsonl to {args.output_dir}")
            return 0
        except Exception as exc:
            print(f"Failed to import Hyperfine benchmark: {exc}", file=sys.stderr)
            return 1

    print(f"Unsupported format: {args.format}", file=sys.stderr)
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for benchmark_core."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "report":
        return handle_report(args)
    if args.subcommand == "compare":
        return handle_compare(args)
    if args.subcommand == "import":
        return handle_import(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
