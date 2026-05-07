from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gsearch.manager import create_next_trial
from gsearch.manager import export_trials
from gsearch.manager import initialize_experiment
from gsearch.manager import parse_json_object
from gsearch.manager import record_trial_result
from gsearch.manager import summarize_trials
from gsearch.manager import write_json_file
from gsearch.reporting import generate_report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gsearch",
        description="Durable adaptive grid-search manager and reporter.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version="gsearch 0.1.2",
    )

    subparsers = parser.add_subparsers(
        title="subcommands",
        dest="command",
        required=True,
    )

    init_parser = subparsers.add_parser(
        "init",
        help="Create or update an experiment from a grid JSON file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    init_parser.add_argument(
        "--database", "-d", required=True, help="SQLite database path."
    )
    init_parser.add_argument("--grid", "-g", required=True, help="Grid JSON file.")
    init_parser.add_argument(
        "--experiment", "-e", required=True, help="Experiment name."
    )

    next_parser = subparsers.add_parser(
        "next",
        help="Create and return the next planned trial.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    next_parser.add_argument(
        "--database", "-d", required=True, help="SQLite database path."
    )
    next_parser.add_argument(
        "--experiment", "-e", required=True, help="Experiment name."
    )
    next_parser.add_argument(
        "--output", "-o", default="-", help="Output trial JSON file, or '-' for stdout."
    )
    next_parser.add_argument(
        "--group-key", "-k", default=None, help="Optional group key, such as domain."
    )
    next_parser.add_argument(
        "--group-value",
        "-v",
        default=None,
        help="Optional group value, such as example.com.",
    )
    next_parser.add_argument(
        "--group-mode",
        "-G",
        choices=["global", "per-group", "hybrid"],
        default="hybrid",
        help="How group-specific history is used.",
    )
    next_parser.add_argument(
        "--mode",
        "-m",
        choices=["adaptive", "coverage", "random", "ucb", "neighbor"],
        default="adaptive",
        help="Selection mode.",
    )
    next_parser.add_argument(
        "--metadata-json", "-M", default=None, help="Additional metadata JSON object."
    )
    next_parser.add_argument(
        "--seed", "-s", type=int, default=None, help="Random seed."
    )

    record_parser = subparsers.add_parser(
        "record",
        help="Record the outcome of a planned trial.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    record_parser.add_argument(
        "--database", "-d", required=True, help="SQLite database path."
    )
    record_parser.add_argument(
        "--trial-id", "-t", required=True, help="Trial ID returned by next."
    )
    record_parser.add_argument(
        "--metric-value",
        "-v",
        type=float,
        default=None,
        help="Measured optimization metric value.",
    )
    record_parser.add_argument(
        "--status",
        "-s",
        choices=["ok", "failed", "cancelled"],
        default="ok",
        help="Trial status.",
    )
    record_parser.add_argument(
        "--metadata-json",
        "-M",
        default=None,
        help="Additional result metadata JSON object.",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Export all experiment trials as JSONL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    export_parser.add_argument(
        "--database", "-d", required=True, help="SQLite database path."
    )
    export_parser.add_argument(
        "--experiment", "-e", required=True, help="Experiment name."
    )
    export_parser.add_argument(
        "--output", "-o", required=True, help="Output JSONL path."
    )

    summary_parser = subparsers.add_parser(
        "summary",
        help="Print or write a JSON summary of top configurations.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    summary_parser.add_argument(
        "--database", "-d", required=True, help="SQLite database path."
    )
    summary_parser.add_argument(
        "--experiment", "-e", required=True, help="Experiment name."
    )
    summary_parser.add_argument(
        "--output", "-o", default="-", help="Output JSON file, or '-' for stdout."
    )
    summary_parser.add_argument(
        "--limit", "-l", type=int, default=20, help="Top config limit."
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Generate CSV, JSON, Markdown, and graph reports.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    report_parser.add_argument(
        "--database", "-d", required=True, help="SQLite database path."
    )
    report_parser.add_argument(
        "--experiment", "-e", required=True, help="Experiment name."
    )
    report_parser.add_argument(
        "--output-dir", "-o", required=True, help="Output report directory."
    )
    report_parser.add_argument(
        "--top-limit", "-l", type=int, default=20, help="Top config limit."
    )
    report_parser.add_argument(
        "--max-groups",
        "-g",
        type=int,
        default=20,
        help="Maximum groups to include in group performance plots.",
    )
    report_parser.add_argument(
        "--heatmap-x",
        "-x",
        default=None,
        help="Optional parameter name for heatmap x-axis.",
    )
    report_parser.add_argument(
        "--heatmap-y",
        "-y",
        default=None,
        help="Optional parameter name for heatmap y-axis.",
    )
    report_parser.add_argument(
        "--interaction-limit",
        "-i",
        type=int,
        default=30,
        help="Maximum pairwise interactions to summarize and plot.",
    )

    return parser.parse_args(argv)


def run_init(args: argparse.Namespace) -> int:
    initialize_experiment(
        database=args.database,
        grid_path=args.grid,
        experiment=args.experiment,
    )
    print(f"Initialized experiment: {args.experiment}", file=sys.stderr)
    return 0


def run_next(args: argparse.Namespace) -> int:
    payload = create_next_trial(
        database=args.database,
        experiment=args.experiment,
        output=None if args.output == "-" else args.output,
        group_key=args.group_key,
        group_value=args.group_value,
        group_mode=args.group_mode,
        selection_mode=args.mode,
        metadata=parse_json_object(args.metadata_json, "metadata JSON"),
        seed=args.seed,
    )

    if args.output == "-":
        print(json.dumps(payload, indent=4, ensure_ascii=False))
    else:
        print(
            f"Wrote trial: {Path(args.output).expanduser().resolve()}", file=sys.stderr
        )

    return 0


def run_record(args: argparse.Namespace) -> int:
    record_trial_result(
        database=args.database,
        trial_id=args.trial_id,
        status=args.status,
        metric_value=args.metric_value,
        metadata=parse_json_object(args.metadata_json, "metadata JSON"),
    )
    print(f"Recorded trial result: {args.trial_id}", file=sys.stderr)
    return 0


def run_export(args: argparse.Namespace) -> int:
    count = export_trials(
        database=args.database,
        experiment=args.experiment,
        output=args.output,
    )
    print(
        f"Exported {count} trial(s): {Path(args.output).expanduser().resolve()}",
        file=sys.stderr,
    )
    return 0


def run_summary(args: argparse.Namespace) -> int:
    payload = summarize_trials(
        database=args.database,
        experiment=args.experiment,
        limit=args.limit,
    )

    if args.output == "-":
        print(json.dumps(payload, indent=4, ensure_ascii=False))
    else:
        write_json_file(args.output, payload)
        print(
            f"Wrote summary: {Path(args.output).expanduser().resolve()}",
            file=sys.stderr,
        )

    return 0


def run_report(args: argparse.Namespace) -> int:
    manifest = generate_report(
        database=args.database,
        experiment=args.experiment,
        output_dir=args.output_dir,
        top_limit=args.top_limit,
        max_groups=args.max_groups,
        heatmap_x=args.heatmap_x,
        heatmap_y=args.heatmap_y,
        interaction_limit=args.interaction_limit,
    )
    print(json.dumps(manifest, indent=4, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if args.command == "init":
            return run_init(args)

        if args.command == "next":
            return run_next(args)

        if args.command == "record":
            return run_record(args)

        if args.command == "export":
            return run_export(args)

        if args.command == "summary":
            return run_summary(args)

        if args.command == "report":
            return run_report(args)

        raise ValueError(f"Unsupported command: {args.command}")
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
