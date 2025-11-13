#!/usr/bin/env python
"""
Main CLI entry point for the file-utils tool.
"""
from __future__ import annotations

import argparse
import sys
from typing import Sequence
import logging
import json as _json
from cross_platform.system_utils import SystemUtils
from . import diskspace
from . import wsltool


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A collection of file utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- ls command ---
    ls_parser = subparsers.add_parser("ls", help="Interactive file and directory lister.")
    ls_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to inspect (defaults to current directory).",
    )
    ls_parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=0,
        help="Recursion depth. 0 for current directory only.",
    )
    ls_parser.add_argument(
        "-g",
        "--glob",
        metavar="PATTERN",
        help="Initial glob pattern to filter entries (e.g. '*.py').",
    )
    ls_parser.add_argument(
        "-s",
        "--sort",
        choices=("created", "modified", "accessed", "size", "name", "c", "m", "a", "s", "n"),
        default="created",
        help="Initial sort field: created/c, modified/m, accessed/a, size/s, name/n.",
    )
    ls_parser.add_argument(
        "-o",
        "--order",
        choices=("asc", "desc"),
        default="desc",
        help="Initial sort order to use.",
    )
    ls_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output in JSON format instead of launching TUI.",
    )
    ls_parser.add_argument(
        "--no-dirs-first",
        action="store_true",
        help="Don't group directories before files (default: dirs first).",
    )
    ls_parser.add_argument(
        "-S",
        "--calc-sizes",
        action="store_true",
        help="Calculate actual recursive sizes for directories.",
    )

    # --- replace command ---
    replace_parser = subparsers.add_parser(
        "replace",
        help="Mass find and replace using ripgrep.",
        description="Find and replace text across multiple files using ripgrep. "
                    "Supports replacing text or deleting entire lines.",
    )
    replace_parser.add_argument(
        "-p",
        "--pattern",
        required=True,
        help="Regex pattern to search for.",
    )
    replace_parser.add_argument(
        "-r",
        "--replacement",
        default=None,
        help="Replacement text. Cannot be used with --delete-line.",
    )
    replace_parser.add_argument(
        "-d",
        "--delete-line",
        action="store_true",
        help="Delete entire line containing match. Cannot be used with --replacement.",
    )
    replace_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making actual changes.",
    )
    replace_parser.add_argument(
        "-f",
        "--first-only",
        action="store_true",
        help="Only replace the first match in each file.",
    )
    replace_parser.add_argument(
        "-l",
        "--line-number",
        type=int,
        metavar="N",
        help="Only replace matches on line number N (1-indexed).",
    )
    replace_parser.add_argument(
        "-m",
        "--max-per-file",
        type=int,
        metavar="N",
        help="Maximum number of replacements per file.",
    )
    replace_parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="Case insensitive search.",
    )
    replace_parser.add_argument(
        "-g",
        "--glob",
        metavar="PATTERN",
        help="Glob pattern to filter files (e.g., '*.py').",
    )
    replace_parser.add_argument(
        "-t",
        "--type",
        metavar="TYPE",
        help="File type filter (e.g., 'py', 'js'). Uses ripgrep's --type.",
    )
    replace_parser.add_argument(
        "--path",
        default=".",
        help="Directory or file to search in (default: current directory).",
    )
    replace_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output showing each file processed.",
    )
    replace_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode - only show errors.",
    )
    replace_parser.add_argument(
        "-a",
        "--analyze",
        action="store_true",
        help="Analyze mode - show statistics about matches without making changes.",
    )
    replace_parser.add_argument(
        "-s",
        "--show-stats",
        action="store_true",
        help="Show detailed statistics after replacements.",
    )
    replace_parser.add_argument(
        "-b",
        "--blank-on-delete",
        action="store_true",
        help="Leave blank line when deleting (default: pull up line below).",
    )

    # --- disk command (scan/clean families) ---
    disk_parser = subparsers.add_parser("disk", help="Disk space tools (scan/clean).")
    disk_sub = disk_parser.add_subparsers(dest="disk_cmd", required=True)

    # disk scan
    scan_p = disk_sub.add_parser("scan", help="Scan disk usage: largest, caches, containers, space.")
    scan_sub = scan_p.add_subparsers(dest="scan_cmd")

    sc_largest = scan_sub.add_parser("largest", help="List largest files.")
    sc_largest.add_argument("-p", "--path", default=None, help="Scan root path.")
    sc_largest.add_argument("-n", "--top", type=int, default=50, help="Number of results.")
    sc_largest.add_argument("-m", "--min-size", default=None, help="Minimum file size, e.g. 500M.")
    sc_largest.add_argument("-e", "--ext", action="append", help="Filter by file extension (repeatable).")
    sc_largest.add_argument("-g", "--glob", action="append", help="Filter by glob pattern (repeatable).")
    sc_largest.add_argument("-f", "--format", choices=("json", "table", "md"), default="table", help="Output format.")
    sc_largest.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    sc_caches = scan_sub.add_parser("caches", help="Detect common caches.")
    sc_caches.add_argument("-p", "--path", default=None, help="Home path to scan (defaults to ~).")
    sc_caches.add_argument("-f", "--format", choices=("json", "table"), default="table", help="Output format.")
    sc_caches.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    sc_cont = scan_sub.add_parser("containers", help="Show container usage.")
    sc_cont.add_argument("-P", "--provider", default="auto", choices=("auto", "docker", "podman"), help="Provider.")
    sc_cont.add_argument("-l", "--ls", action="store_true", help="List running and all containers and images.")
    sc_cont.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    sc_space = scan_sub.add_parser("space", help="Show remaining space on all drives.")
    sc_space.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    # disk clean
    clean_p = disk_sub.add_parser("clean", help="Clean artifacts: largest, caches, containers.")
    clean_sub = clean_p.add_subparsers(dest="clean_cmd", required=True)

    cl_largest = clean_sub.add_parser("largest", help="Delete largest files (dry-run by default).")
    cl_largest.add_argument("-p", "--path", default=None, help="Scan root path.")
    cl_largest.add_argument("-n", "--top", type=int, default=50, help="Number of files to target.")
    cl_largest.add_argument("-m", "--min-size", default=None, help="Minimum file size, e.g. 500M.")
    cl_largest.add_argument("-e", "--ext", action="append", help="Only delete files with these extensions.")
    cl_largest.add_argument("-g", "--glob", action="append", help="Only delete files matching globs.")
    cl_largest.add_argument("-d", "--dry-run", action="store_true", help="Preview actions only (default).")
    cl_largest.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation.")
    cl_largest.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    cl_caches = clean_sub.add_parser("caches", help="Clean common caches/artifacts.")
    cl_caches.add_argument("-w", "--what", nargs="+", default=["python", "node", "build"], help="Categories: python conda node apt journals build git all")
    cl_caches.add_argument("-d", "--dry-run", action="store_true", help="Preview actions only.")
    cl_caches.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation.")
    cl_caches.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    cl_cont = clean_sub.add_parser("containers", help="Prune Docker/Podman stores.")
    cl_cont.add_argument("-P", "--provider", default="auto", choices=("auto", "docker", "podman"), help="Provider.")
    cl_cont.add_argument("-d", "--dry-run", action="store_true", help="Preview actions only.")
    cl_cont.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation.")
    cl_cont.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    # wsl-reclaim and report keep as-is under disk
    d_wsl = disk_sub.add_parser("wsl-reclaim", help="Reclaim WSL disk space (moved to 'wsl').")
    d_wsl.add_argument("-d", "--dry-run", action="store_true", help="Preview actions only.")
    d_wsl.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation.")
    d_wsl.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    d_report = disk_sub.add_parser("report", help="Emit JSON and Markdown disk report.")
    d_report.add_argument("-p", "--path", default=None, help="Scan root path.")
    d_report.add_argument("-n", "--top", type=int, default=50, help="Top N for largest files and heaviest dirs.")
    d_report.add_argument("-m", "--min-size", default=None, help="Minimum file size, e.g. 500M.")
    d_report.add_argument("-f", "--format", choices=("json", "md"), default="md", help="Output format.")
    d_report.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")

    # --- wsl command ---
    _add_wsl_commands(subparsers)

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO)

    if args.command == "ls":
        from . import lister
        return lister.run_lister(args)
    elif args.command == "replace":
        from . import replacer
        return replacer.run_replacer(args)
    elif args.command == "disk":
        sysu = SystemUtils()
        dc = args.disk_cmd

        if dc == "scan":
            sc = args.scan_cmd
            if sc is None:
                # Full scan across largest, caches, containers
                info = diskspace.run_full_scan(
                    sysu,
                    path=getattr(args, "path", None),
                    top_n=getattr(args, "top", 50),
                    min_size=getattr(args, "min_size", None),
                    exts=getattr(args, "ext", None),
                    globs=getattr(args, "glob", None),
                    provider="auto",
                    list_containers=True,
                )
                # Human-readable summary with subsections + overall total
                lg = info["largest"]; ch = info["caches"]; ct = info["containers"]; ov = info["overall"]
                print("== Largest Files ==")
                for it in lg["items"][:min(10, lg["count"])]:
                    print(f"{it['size_human']:>10}  {it['path']}")
                if lg["count"] > 10:
                    print(f"... and {lg['count']-10} more")
                print(f"Total: {lg['total_human']} across {lg['count']} files\n")

                print("== Caches ==")
                for k, v in sorted(ch["per_category_human"].items()):
                    if v != "0 B":
                        print(f"{k:12}: {v}  ({len(ch['detected'].get(k, []))} paths)")
                print(f"Total: {ch['total_human']}\n")

                print("== Containers ==")
                if ct.get("running"):
                    print("Running:")
                    for line in ct["running"][:10]:
                        print(f"  {line}")
                    if len(ct["running"]) > 10:
                        print("  ...")
                if ct.get("all"):
                    print("All:")
                    for line in ct["all"][:10]:
                        print(f"  {line}")
                    if len(ct["all"]) > 10:
                        print("  ...")
                print(f"Estimated store size: {ct['store_human']}\n")

                print(f"== Overall Total ==\n{ov['total_human']}")
                return 0
            if sc == "largest":
                items = diskspace.scan_largest_files(sysu, args.path, args.top, args.min_size, exts=getattr(args, "ext", None), globs=getattr(args, "glob", None))
                total = diskspace.summarize_total_size(items)
                if args.format == "json":
                    print(_json.dumps({
                        "items": [{"path": i.path, "size_bytes": i.size_bytes} for i in items],
                        "total_bytes": total,
                        "total_human": diskspace.format_bytes_binary(total),
                        "count": len(items),
                    }, indent=2))
                elif args.format == "md":
                    for i in items:
                        print(f"- {diskspace.format_bytes_binary(i.size_bytes)}  {i.path}")
                    print(f"\nTotal: {diskspace.format_bytes_binary(total)} across {len(items)} files")
                else:
                    for i in items:
                        print(f"{diskspace.format_bytes_binary(i.size_bytes):>10}  {i.path}")
                    print(f"Total: {diskspace.format_bytes_binary(total)} across {len(items)} files")
                return 0

            if sc == "caches":
                found = diskspace.detect_common_caches(sysu, args.path)
                if args.format == "json":
                    print(_json.dumps(found, indent=2))
                else:
                    for k in sorted(found.keys()):
                        vals = found[k]
                        print(f"{k}: {len(vals)}")
                        for v in vals[:10]:
                            print(f"  - {v}")
                        if len(vals) > 10:
                            print("  - ...")
                return 0

            if sc == "containers":
                info = diskspace.containers_scan(sysu, args.provider, list_items=args.ls)
                if args.ls:
                    if info.get("running"):
                        print("Running:")
                        for line in info["running"]:
                            print(f"  {line}")
                    if info.get("all"):
                        print("All:")
                        for line in info["all"]:
                            print(f"  {line}")
                    if info.get("images"):
                        print("Images:")
                        for line in info["images"]:
                            print(f"  {line}")
                if info.get("system_df"):
                    print("\nSystem usage:\n" + info["system_df"])
                return 0

            if sc == "space":
                print(diskspace.space_summary(sysu))
                return 0

        if dc == "clean":
            cl = args.clean_cmd
            if cl == "largest":
                dry = True if getattr(args, "dry_run", False) else True
                if not args.yes:
                    print("About to clean largest files (may be dry-run). Filters applied.")
                    resp = input("Proceed? [y/N] ")
                    if resp.strip().lower() not in ("y", "yes"):
                        print("Aborted.")
                        return 0
                actions, count, total = diskspace.clean_largest(
                    sysu, args.path, args.top, args.min_size,
                    exts=getattr(args, "ext", None), globs=getattr(args, "glob", None), dry_run=dry,
                )
                for line in actions:
                    print(line)
                label = "Would delete" if dry else "Deleted"
                print(f"{label} {count} files totaling {diskspace.format_bytes_binary(total)}")
                return 0

            if cl == "caches":
                if not args.yes:
                    resp = input("About to clean caches: %s. Proceed? [y/N] " % (", ".join(args.what)))
                    if resp.strip().lower() not in ("y", "yes"):
                        print("Aborted.")
                        return 0
                actions = diskspace.clean_caches(sysu, args.what, dry_run=args.dry_run)
                for line in actions:
                    print(line)
                return 0

            if cl == "containers":
                if not args.yes:
                    resp = input(f"About to prune {args.provider} containers. Proceed? [y/N] ")
                    if resp.strip().lower() not in ("y", "yes"):
                        print("Aborted.")
                        return 0
                actions = diskspace.containers_maint(sysu, args.provider, dry_run=args.dry_run)
                for line in actions:
                    print(line)
                return 0

        if dc == "wsl-reclaim":
            if not args.yes:
                resp = input("This will attempt WSL fstrim/compaction steps. Proceed? [y/N] ")
                if resp.strip().lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0
            print("[Warning] Use 'fsu wsl compact' going forward. Running legacy path.")
            actions = wsltool.compact(sysu, dry_run=args.dry_run)
            for line in actions:
                print(line)
            return 0

        if dc == "report":
            files = diskspace.scan_largest_files(sysu, args.path, args.top, args.min_size)
            dirs = diskspace.scan_heaviest_dirs(sysu, args.path, args.top)
            caches = diskspace.detect_common_caches(sysu, args.path)
            data, md = diskspace.build_report(files, dirs, caches)
            if args.format == "json":
                print(_json.dumps(data, indent=2))
            else:
                print(md)
            return 0

    elif args.command == "wsl":
        sysu = SystemUtils()
        if args.wsl_cmd == "compact":
            if not args.yes:
                resp = input("This will compact WSL disks if supported. Proceed? [y/N] ")
                if resp.strip().lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0
            actions = wsltool.compact(sysu, guard_gb=args.guard_gb, dry_run=args.dry_run, show_host_instructions=getattr(args, "show_host_help", False))
            for line in actions:
                print(line)
            return 0
        if args.wsl_cmd == "docker-fixups":
            if not args.yes:
                resp = input("This will attempt to recover Docker Desktop contexts. Proceed? [y/N] ")
                if resp.strip().lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 0
            actions = wsltool.docker_desktop_fixups(sysu, dry_run=args.dry_run)
            for line in actions:
                print(line)
            return 0
        return 0

    return 0

def _add_wsl_commands(subparsers):
    wsl_parser = subparsers.add_parser("wsl", help="WSL utilities (compaction, docker fixups)")
    wsl_sub = wsl_parser.add_subparsers(dest="wsl_cmd", required=True)

    wsl_compact = wsl_sub.add_parser("compact", help="Compact WSL VHDX (guarded).")
    wsl_compact.add_argument("-g", "--guard-gb", type=int, default=15, help="Minimum free GB required on host before compact.")
    wsl_compact.add_argument("-d", "--dry-run", action="store_true", help="Preview actions only.")
    wsl_compact.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation.")
    wsl_compact.add_argument("-H", "--show-host-help", action="store_true", help="When inside WSL, also print host PowerShell instructions.")

    wsl_dd = wsl_sub.add_parser("docker-fixups", help="Recover Docker Desktop contexts and restart components (Windows).")
    wsl_dd.add_argument("-d", "--dry-run", action="store_true", help="Preview actions only.")
    wsl_dd.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation.")

    return wsl_parser


if __name__ == "__main__":
    raise SystemExit(main())
