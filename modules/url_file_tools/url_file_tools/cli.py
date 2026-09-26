"""Command-line interface for URL file tools."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .archive import match_archive_urls
from .core import (
    DEFAULT_GLOBS,
    MergePlan,
    NormalizePlan,
    UrlFileError,
    atomic_write_text,
    backup_file,
    build_merge_plan,
    build_normalize_plan,
    discover_files,
    domain_filename,
    grouped_output,
    render_duplicate_report,
)

PROGRAM = "url-files"


def _add_mode_arguments(parser: argparse.ArgumentParser) -> None:
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("-a", "--apply", action="store_true", help="Write the planned changes.")
    modes.add_argument("-n", "--dry-run", action="store_true", help="Preview only (the default).")


def _add_discovery_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-r", "--recurse", action="store_true", help="Search subfolders recursively.")
    parser.add_argument(
        "-g",
        "--glob",
        action="append",
        dest="patterns",
        help="Input glob; repeat for more than one. Defaults to *.txt, *.url, and *.urls.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Dry-run-first URL file normalization, merging, deduplication, and domain splitting.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize", help="Remove numbered prefixes and optionally duplicate rows.")
    normalize.add_argument("-p", "--path", type=Path, required=True, help="Input file or folder.")
    _add_mode_arguments(normalize)
    _add_discovery_arguments(normalize)
    normalize.add_argument("-u", "--unique", action="store_true", help="Keep only the first normalized row.")
    normalize.add_argument(
        "-i", "--ignore-case", action="store_true", help="Compare duplicate rows case-insensitively."
    )
    normalize.add_argument(
        "-l", "--allow-leading-whitespace", action="store_true", help="Normalize indented numbering."
    )
    normalize.add_argument("-b", "--backup", action="store_true", help="Create timestamped backups before applying.")
    normalize.add_argument(
        "-m", "--max-preview", type=int, default=0, help="Maximum changes shown per file; 0 is unlimited."
    )

    merge = subparsers.add_parser("merge", help="Merge URL files into one file or one file per base domain.")
    merge.add_argument("-p", "--path", type=Path, required=True, help="Folder containing URL files.")
    _add_mode_arguments(merge)
    _add_discovery_arguments(merge)
    selection = merge.add_mutually_exclusive_group()
    selection.add_argument("-f", "--files", nargs="+", help="Relative file paths under the target folder.")
    selection.add_argument(
        "-L", "--file-list", type=Path, help="Text manifest of relative file paths under the target folder."
    )
    merge.add_argument("-o", "--output", type=Path, help="Output file, or output folder with --split-by-domain.")
    merge.add_argument(
        "-s", "--split-by-domain", action="store_true", help="Create one file per registered base domain."
    )
    merge.add_argument(
        "-D",
        "--duplicates",
        choices=("ask", "remove", "keep"),
        default="ask",
        help="Duplicate policy on apply; dry runs always report duplicates.",
    )
    merge.add_argument("-R", "--duplicate-report", type=Path, help="Custom duplicate report path.")
    merge.add_argument(
        "-N", "--no-duplicate-report", action="store_true", help="Do not write a duplicate sidecar report."
    )
    merge.add_argument("-l", "--allow-leading-whitespace", action="store_true", help="Normalize indented numbering.")
    merge.add_argument(
        "-m", "--max-preview", type=int, default=20, help="Maximum duplicate/invalid previews; 0 is unlimited."
    )
    merge.add_argument("-S", "--strict", action="store_true", help="Fail instead of skipping invalid URL rows.")

    archive = subparsers.add_parser("archive", help="Read-only downloader archive matching.")
    archive_subparsers = archive.add_subparsers(dest="archive_command", required=True)
    match = archive_subparsers.add_parser("match", help="Classify input URLs as downloaded or not downloaded.")
    match.add_argument("-p", "--path", type=Path, required=True, help="Folder containing URL files.")
    match.add_argument(
        "-a", "--archive", type=Path, required=True, help="ytaedl archive path or mangadl state database."
    )
    match.add_argument(
        "-t",
        "--archive-type",
        choices=("auto", "ytaedl", "mangadl"),
        default="auto",
        help="Archive adapter; auto detects by structure.",
    )
    match_modes = match.add_mutually_exclusive_group()
    match_modes.add_argument("-X", "--apply", action="store_true", help="Write match report files.")
    match_modes.add_argument("-n", "--dry-run", action="store_true", help="Preview only (the default).")
    _add_discovery_arguments(match)
    match_selection = match.add_mutually_exclusive_group()
    match_selection.add_argument("-f", "--files", nargs="+", help="Relative file paths under the target folder.")
    match_selection.add_argument("-L", "--file-list", type=Path, help="Manifest of relative URL-file paths.")
    match.add_argument("-o", "--output", type=Path, help="Report folder; defaults to <path>/archive_match.")
    match.add_argument("-l", "--allow-leading-whitespace", action="store_true", help="Normalize indented numbering.")
    match.add_argument(
        "-m", "--max-preview", type=int, default=20, help="Maximum URLs previewed per result group; 0 is unlimited."
    )
    match.add_argument("-S", "--strict", action="store_true", help="Fail instead of skipping invalid URL rows.")
    return parser


def _patterns(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(args.patterns) if args.patterns else DEFAULT_GLOBS


def _validate_preview(value: int) -> None:
    if value < 0:
        raise UrlFileError("--max-preview cannot be negative")


def _normalize_candidates(args: argparse.Namespace) -> list[Path]:
    target = args.path.resolve()
    if target.is_file():
        return [target]
    return discover_files(target, patterns=_patterns(args), recurse=args.recurse)


def _print_normalize_plan(plan: NormalizePlan, max_preview: int, applying: bool) -> None:
    verb = "Changing" if applying else "Would change"
    print(f"{verb}: {plan.path}")
    print(f"  Line changes: {len(plan.changes)}")
    selected = plan.changes if max_preview == 0 else plan.changes[:max_preview]
    for change in selected:
        print(f"  Line {change.line_number} [{change.kind}]")
        print(f"    From: {change.before}")
        print(f"    To  : {change.after}")
    omitted = len(plan.changes) - len(selected)
    if omitted:
        print(f"  ... omitted {omitted} additional change(s)")


def run_normalize(args: argparse.Namespace) -> int:
    _validate_preview(args.max_preview)
    candidates = _normalize_candidates(args)
    plans = [
        build_normalize_plan(
            path,
            allow_leading_whitespace=args.allow_leading_whitespace,
            unique=args.unique,
            ignore_case=args.ignore_case,
        )
        for path in candidates
    ]
    changed = [plan for plan in plans if plan.changes]
    total_changes = sum(len(plan.changes) for plan in changed)
    for plan in changed:
        _print_normalize_plan(plan, args.max_preview, args.apply)
        if args.apply:
            if args.backup:
                print(f"  Backup: {backup_file(plan.path)}")
            atomic_write_text(plan.path, plan.new_text, plan.original.encoding)

    print("\nSummary")
    print("-------")
    print(f"Mode                       : {'Apply' if args.apply else 'Dry run'}")
    print(f"Candidate files            : {len(candidates)}")
    print(f"Files with changes         : {len(changed)}")
    print(f"Files rewritten            : {len(changed) if args.apply else 0}")
    print(f"Total line changes         : {total_changes}")
    return 0


def _output_paths(args: argparse.Namespace, root: Path) -> tuple[Path, Path | None]:
    if args.split_by_domain:
        output = (args.output or (root / "merged_by_domain")).resolve()
        report = (args.duplicate_report or (output / "_duplicates.txt")).resolve()
    else:
        output = (args.output or (root / "merged_urls.txt")).resolve()
        report = (args.duplicate_report or output.with_name(f"{output.stem}.duplicates.txt")).resolve()
    return output, None if args.no_duplicate_report else report


def _choose_duplicate_removal(args: argparse.Namespace, plan: MergePlan) -> bool:
    if not plan.duplicates:
        return False
    if args.duplicates == "remove":
        return True
    if args.duplicates == "keep":
        return False
    if not args.apply:
        return False
    if not sys.stdin.isatty():
        raise UrlFileError("Duplicates were found but input is not interactive; use --duplicates remove or keep")
    answer = input(f"Remove {len(plan.duplicates)} later duplicate occurrence(s)? [y/N] ").strip().casefold()
    return answer in {"y", "yes"}


def _preview_items(items: Sequence, maximum: int) -> Sequence:
    return items if maximum == 0 else items[:maximum]


def _print_merge_plan(plan: MergePlan, args: argparse.Namespace, output: Path, report: Path | None) -> None:
    print(f"Mode: {'Apply' if args.apply else 'Dry run'}")
    print(f"Target: {plan.root}")
    print("Source files:")
    for path in plan.source_files:
        print(f"  {path.relative_to(plan.root)}")
    if plan.duplicates:
        print("\nDuplicate occurrences:")
        for duplicate in _preview_items(plan.duplicates, args.max_preview):
            print(f"  {duplicate.url}")
            print(f"    first:     {duplicate.first.display(plan.root)}")
            print(f"    duplicate: {duplicate.duplicate.display(plan.root)}")
    if plan.invalid:
        print("\nInvalid rows (skipped):")
        for invalid in _preview_items(plan.invalid, args.max_preview):
            print(f"  {invalid.source.display(plan.root)}: {invalid.text!r} ({invalid.reason})")
    print(f"\n{'Output' if args.apply else 'Would write'}: {output}")
    if report is not None and plan.duplicates:
        print(f"{'Duplicate report' if args.apply else 'Would write duplicate report'}: {report}")


def _write_merge_outputs(args: argparse.Namespace, plan: MergePlan, output: Path, remove_duplicates: bool) -> int:
    records = plan.selected_records(remove_duplicates)
    if args.split_by_domain:
        groups = grouped_output(records)
        for domain, urls in groups.items():
            atomic_write_text(output / domain_filename(domain), "".join(f"{url}\n" for url in urls))
        return len(groups)
    atomic_write_text(output, "".join(f"{record.url}\n" for record in records))
    return 1


def run_merge(args: argparse.Namespace) -> int:
    _validate_preview(args.max_preview)
    root = args.path.resolve()
    output, report = _output_paths(args, root)
    excluded_paths = [output] if not args.split_by_domain else []
    if report is not None:
        excluded_paths.append(report)
    excluded_directories = [output] if args.split_by_domain else []
    sources = discover_files(
        root,
        names=args.files,
        manifest=args.file_list,
        patterns=_patterns(args),
        recurse=args.recurse,
        excluded_paths=excluded_paths,
        excluded_directories=excluded_directories,
    )
    if not sources:
        raise UrlFileError("No source files matched")
    plan = build_merge_plan(root, sources, allow_leading_whitespace=args.allow_leading_whitespace)
    if args.strict and plan.invalid:
        first = plan.invalid[0]
        raise UrlFileError(f"Invalid URL at {first.source.display(root)}: {first.text!r} ({first.reason})")
    _print_merge_plan(plan, args, output, report)
    remove_duplicates = _choose_duplicate_removal(args, plan)
    outputs_written = 0
    if args.apply:
        outputs_written = _write_merge_outputs(args, plan, output, remove_duplicates)
        if report is not None and plan.duplicates:
            atomic_write_text(report, render_duplicate_report(plan))

    stats = plan.stats
    print("\nSummary")
    print("-------")
    print(f"Mode                       : {'Apply' if args.apply else 'Dry run'}")
    print(f"Source files               : {stats.source_files}")
    print(f"Rows read                  : {stats.rows_read}")
    print(f"Valid URL rows             : {stats.valid_urls}")
    print(f"Unique URLs                : {stats.unique_urls}")
    print(f"Duplicate occurrences      : {stats.duplicate_occurrences}")
    print(f"Duplicate URL groups       : {stats.duplicate_groups}")
    print(f"Unique base domains        : {stats.unique_base_domains}")
    print(f"Number prefixes removed    : {stats.numbered_prefixes_removed}")
    print(f"Mobile m. prefixes removed : {stats.mobile_prefixes_removed}")
    print(f"Blank rows skipped         : {stats.blank_rows}")
    print(f"Comment rows skipped       : {stats.comment_rows}")
    print(f"Invalid rows skipped       : {stats.invalid_rows}")
    if not args.apply and args.duplicates == "ask" and plan.duplicates:
        duplicate_action = "ask on apply"
    else:
        duplicate_action = "remove later occurrences" if remove_duplicates else "keep all occurrences"
    print(f"Duplicate action           : {duplicate_action}")
    print(f"Output files written       : {outputs_written}")
    return 0


def _render_match_rows(rows: Sequence) -> str:
    return "".join(f"{row.url}\n" for row in rows)


def _render_match_details(result) -> str:
    lines = ["url\tdownloaded\tarchive_status\tevidence_source\tevidence_line"]
    for row in result.evidence:
        lines.append(
            "\t".join(
                (
                    row.url,
                    "yes" if row.downloaded else "no",
                    row.archive_status,
                    row.evidence_source,
                    str(row.evidence_line or ""),
                )
            )
        )
    return "\n".join(lines) + "\n"


def run_archive_match(args: argparse.Namespace) -> int:
    _validate_preview(args.max_preview)
    root = args.path.resolve()
    output = (args.output or (root / "archive_match")).resolve()
    sources = discover_files(
        root,
        names=args.files,
        manifest=args.file_list,
        patterns=_patterns(args),
        recurse=args.recurse,
        excluded_directories=[output],
    )
    if not sources:
        raise UrlFileError("No source files matched")
    plan = build_merge_plan(root, sources, allow_leading_whitespace=args.allow_leading_whitespace)
    if args.strict and plan.invalid:
        first = plan.invalid[0]
        raise UrlFileError(f"Invalid URL at {first.source.display(root)}: {first.text!r} ({first.reason})")
    result = match_archive_urls(
        (record.url for record in plan.unique_records),
        args.archive,
        archive_type=args.archive_type,
    )

    print(f"Mode: {'Apply' if args.apply else 'Dry run'}")
    print(f"Archive type: {result.archive_type}")
    print(f"Archive: {result.archive_path}")
    print("\nDownloaded:")
    for row in _preview_items(result.downloaded, args.max_preview):
        location = f":{row.evidence_line}" if row.evidence_line else ""
        print(f"  {row.url} [{row.archive_status}; {row.evidence_source}{location}]")
    print("\nNot downloaded:")
    for row in _preview_items(result.not_downloaded, args.max_preview):
        print(f"  {row.url} [{row.archive_status}]")

    report_paths = (
        output / "downloaded_urls.txt",
        output / "not_downloaded_urls.txt",
        output / "archive_match.tsv",
    )
    for report_path in report_paths:
        print(f"{'Writing' if args.apply else 'Would write'}: {report_path}")
    if args.apply:
        atomic_write_text(report_paths[0], _render_match_rows(result.downloaded))
        atomic_write_text(report_paths[1], _render_match_rows(result.not_downloaded))
        atomic_write_text(report_paths[2], _render_match_details(result))

    print("\nSummary")
    print("-------")
    print(f"Mode                       : {'Apply' if args.apply else 'Dry run'}")
    print(f"Source files               : {len(sources)}")
    print(f"Unique valid URLs          : {len(plan.unique_records)}")
    print(f"Downloaded                 : {len(result.downloaded)}")
    print(f"Not downloaded             : {len(result.not_downloaded)}")
    print(f"Invalid rows skipped       : {len(plan.invalid)}")
    print(f"Reports written            : {len(report_paths) if args.apply else 0}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "normalize":
            return run_normalize(args)
        if args.command == "merge":
            return run_merge(args)
        if args.command == "archive" and args.archive_command == "match":
            return run_archive_match(args)
        raise UrlFileError(f"Unknown command: {args.command}")
    except UrlFileError as exc:
        parser.error(str(exc))
    except OSError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
