#!/usr/bin/env python3
"""
CLI Script: diff.py
Description: Parses command-line arguments and uses the DirectoryDiff module
to compare two directories. All command-line options have a full name and a
one-letter abbreviation.
"""

import argparse
import json
from dir_diff import DirectoryDiff
from cross_platform.debug_utils import write_debug
from cross_platform.system_utils import SystemUtils

def parse_args():
    parser = argparse.ArgumentParser(description="Directory Diff Tool")
    parser.add_argument("--source", "-s", required=True, help="Source directory")
    parser.add_argument("--destination", "-d", required=True, help="Destination directory")
    parser.add_argument("--preset", "-p", default="basic", help="Preset configuration (e.g., basic, deep, sync-check)")
    parser.add_argument("--ignore", "-i", action="append", help="Ignore pattern (can be specified multiple times)")
    parser.add_argument("--dry-run", "-r", action="store_true", help="Dry run mode; simulate actions without making changes")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--output-format", "-o", choices=["plain", "json", "colored"], default="plain", help="Output format")
    parser.add_argument("--checksum", "-c", default="md5", help="Checksum algorithm (default: md5)")
    parser.add_argument("--case-sensitive", "-C", action="store_true", help="Enable case sensitive comparison")
    parser.add_argument("--follow-symlinks", "-l", action="store_true", help="Follow symbolic links")
    parser.add_argument("--threads", "-t", type=int, default=1, help="Number of threads to use (currently not parallelized)")
    parser.add_argument("--time-tolerance", "-T", type=float, default=0, help="Time tolerance (in seconds) for metadata comparison")
    parser.add_argument("--mode", "-m", choices=["diff", "sync", "copy", "delete"], default="diff", help="Operation mode")
    parser.add_argument("--interactive", "-I", action="store_true", help="Interactive mode for confirmation prompts")
    parser.add_argument("--compare-metadata", action="store_true", help="Enable metadata comparison")
    return parser.parse_args()

def main():
    args = parse_args()

    # Build options dictionary from CLI arguments.
    options = {
        "ignore_patterns": args.ignore if args.ignore else [],
        "dry_run": args.dry_run,
        "verbose": args.verbose,
        "output_format": args.output_format,
        "checksum": args.checksum,
        "case_sensitive": args.case_sensitive,
        "follow_symlinks": args.follow_symlinks,
        "threads": args.threads,
        "time_tolerance": args.time_tolerance,
        "mode": args.mode,
        "interactive": args.interactive,
        "compare_metadata": args.compare_metadata
    }
    
    # Log the options and directories.
    if args.verbose:
        write_debug("Verbose mode enabled.", channel="Debug")
    write_debug(f"Options: {options}", channel="Debug")
    write_debug(f"Source: {args.source}, Destination: {args.destination}", channel="Information")
    
    # Initialize and run the directory diff process.
    diff = DirectoryDiff(args.source, args.destination, options)
    report = diff.run()
    
    # Output the report in the selected format.
    if args.output_format == "json":
        output = {
            "source": args.source,
            "destination": args.destination,
            "diff": diff.diff_result
        }
        print(json.dumps(output, indent=2))
    elif args.output_format == "colored":
        # For colored output, a simple mapping is applied.
        colored_report = report.replace("=== ", "\033[95m=== ").replace("----", "\033[94m----") + "\033[0m"
        print(colored_report)
    else:
        print(report)

if __name__ == "__main__":
    main()
