"""
Mass find and replace utility based on ripgrep.

Supports various modes:
- Replace text with new text
- Delete entire lines containing matches
- Control replacement scope (first only, specific line, max per file)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Match:
    """Represents a single match found by ripgrep."""
    file_path: Path
    line_number: int
    line_content: str
    column: int = 0


@dataclass
class ReplacementResult:
    """Tracks the result of replacements in a single file."""
    file_path: Path
    matches_found: int = 0
    replacements_made: int = 0
    lines_deleted: int = 0
    original_lines: List[str] = field(default_factory=list)
    modified_lines: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class Statistics:
    """Statistics about matches across all files."""
    total_files: int = 0
    total_matches: int = 0
    total_replacements: int = 0
    total_deletions: int = 0
    matches_per_file: List[int] = field(default_factory=list)

    @property
    def min_matches(self) -> int:
        """Minimum matches in a single file."""
        return min(self.matches_per_file) if self.matches_per_file else 0

    @property
    def max_matches(self) -> int:
        """Maximum matches in a single file."""
        return max(self.matches_per_file) if self.matches_per_file else 0

    @property
    def avg_matches(self) -> float:
        """Average matches per file."""
        return sum(self.matches_per_file) / len(self.matches_per_file) if self.matches_per_file else 0.0

    @property
    def median_matches(self) -> float:
        """Median matches per file."""
        if not self.matches_per_file:
            return 0.0
        sorted_matches = sorted(self.matches_per_file)
        n = len(sorted_matches)
        if n % 2 == 0:
            return (sorted_matches[n // 2 - 1] + sorted_matches[n // 2]) / 2
        return sorted_matches[n // 2]

    def display(self):
        """Display statistics in a formatted way."""
        print(f"\n{'='*60}")
        print("MATCH STATISTICS")
        print(f"{'='*60}")
        print(f"Total files processed: {self.total_files}")
        print(f"Total matches found: {self.total_matches}")
        print(f"Total replacements made: {self.total_replacements}")
        print(f"Total deletions made: {self.total_deletions}")
        print(f"\nPer-file match statistics:")
        print(f"  Minimum: {self.min_matches}")
        print(f"  Maximum: {self.max_matches}")
        print(f"  Average: {self.avg_matches:.2f}")
        print(f"  Median:  {self.median_matches:.2f}")
        print(f"{'='*60}")


def find_matches_with_ripgrep(
    pattern: str,
    path: str = ".",
    ignore_case: bool = False,
    glob: Optional[str] = None,
    file_type: Optional[str] = None,
) -> List[Match]:
    """
    Use ripgrep to find all matches of the pattern.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in
        ignore_case: Case insensitive search
        glob: Glob pattern to filter files
        file_type: File type filter (e.g., 'py', 'js')

    Returns:
        List of Match objects
    """
    cmd = ["rg", "--line-number", "--column", "--no-heading", "--with-filename"]

    if ignore_case:
        cmd.append("--ignore-case")

    if glob:
        cmd.extend(["--glob", glob])

    if file_type:
        cmd.extend(["--type", file_type])

    cmd.extend([pattern, path])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        # ripgrep returns exit code 1 when no matches found (not an error)
        if result.returncode not in (0, 1):
            sys.stderr.write(f"ripgrep error: {result.stderr}\n")
            return []

        matches = []
        for line in result.stdout.splitlines():
            # Parse ripgrep output: file:line:column:content
            # Handle Windows paths with drive letters (C:\...)
            # Split and rejoin to handle the drive letter colon
            parts = line.split(":", 4)

            # Windows path: parts[0] = drive letter, parts[1] = rest of path
            # Unix path: parts[0] = full path
            if len(parts) >= 4:
                # Check if we have a Windows drive letter (single letter followed by backslash)
                if len(parts) >= 5 and len(parts[0]) == 1:
                    # Windows path: C:\path\file.txt:line:column:content
                    file_path = Path(f"{parts[0]}:{parts[1]}")
                    line_number = int(parts[2])
                    column = int(parts[3])
                    line_content = parts[4] if len(parts) > 4 else ""
                else:
                    # Unix path or relative path
                    file_path = Path(parts[0])
                    line_number = int(parts[1])
                    column = int(parts[2])
                    line_content = parts[3]

                matches.append(Match(
                    file_path=file_path,
                    line_number=line_number,
                    line_content=line_content,
                    column=column,
                ))

        return matches

    except FileNotFoundError:
        sys.stderr.write("Error: ripgrep (rg) not found. Please install ripgrep.\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Error running ripgrep: {e}\n")
        return []


def apply_replacements(
    file_path: Path,
    pattern: str,
    replacement: Optional[str],
    delete_line: bool,
    first_only: bool,
    specific_line: Optional[int],
    max_per_file: Optional[int],
    ignore_case: bool,
    blank_on_delete: bool = False,
) -> ReplacementResult:
    """
    Apply replacements to a single file.

    Args:
        file_path: Path to the file
        pattern: Regex pattern to search for
        replacement: Replacement text (None if deleting lines)
        delete_line: If True, delete entire line containing match
        first_only: Only replace first match
        specific_line: Only replace on this line number (1-indexed)
        max_per_file: Maximum replacements per file
        ignore_case: Case insensitive matching
        blank_on_delete: If True, leave blank line when deleting; if False, pull up line below (default)

    Returns:
        ReplacementResult object
    """
    result = ReplacementResult(file_path=file_path)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        result.error = f"Failed to read file: {e}"
        return result

    result.original_lines = lines.copy()
    modified_lines = []
    replacements_count = 0
    regex_flags = re.IGNORECASE if ignore_case else 0
    compiled_pattern = re.compile(pattern, regex_flags)

    for line_num, line in enumerate(lines, start=1):
        # Check if we should process this line
        if specific_line is not None and line_num != specific_line:
            modified_lines.append(line)
            continue

        # Check if we've hit the max replacements
        if max_per_file is not None and replacements_count >= max_per_file:
            modified_lines.append(line)
            continue

        # Check if line contains the pattern
        if compiled_pattern.search(line):
            result.matches_found += 1

            if delete_line:
                # Delete the entire line
                result.lines_deleted += 1
                replacements_count += 1
                # Either leave a blank line or don't append at all (pull up)
                if blank_on_delete:
                    modified_lines.append("\n")
                else:
                    # Don't append the line (effectively deleting it)
                    pass
                continue
            elif replacement is not None:
                # Replace the pattern
                if first_only and replacements_count > 0:
                    modified_lines.append(line)
                else:
                    # Replace all occurrences in this line (or just first if first_only on first match)
                    new_line = compiled_pattern.sub(replacement, line, count=1 if first_only else 0)
                    modified_lines.append(new_line)
                    result.replacements_made += 1
                    replacements_count += 1
            else:
                modified_lines.append(line)
        else:
            modified_lines.append(line)

    result.modified_lines = modified_lines
    return result


def write_file(file_path: Path, lines: List[str]) -> bool:
    """
    Write lines to a file.

    Args:
        file_path: Path to write to
        lines: Lines to write

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return True
    except Exception as e:
        sys.stderr.write(f"Error writing to {file_path}: {e}\n")
        return False


def show_diff(result: ReplacementResult, context_lines: int = 3):
    """
    Show a unified diff of the changes.

    Args:
        result: ReplacementResult object
        context_lines: Number of context lines to show
    """
    import difflib

    diff = difflib.unified_diff(
        result.original_lines,
        result.modified_lines,
        fromfile=str(result.file_path),
        tofile=str(result.file_path),
        lineterm='',
        n=context_lines,
    )

    for line in diff:
        if line.startswith('+'):
            print(f"\033[32m{line}\033[0m")  # Green for additions
        elif line.startswith('-'):
            print(f"\033[31m{line}\033[0m")  # Red for deletions
        elif line.startswith('@'):
            print(f"\033[36m{line}\033[0m")  # Cyan for location
        else:
            print(line)


def run_replacer(args: argparse.Namespace) -> int:
    """
    Main entry point for the replacer utility.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code
    """
    # Validate arguments
    analyze_mode = getattr(args, 'analyze', False)

    if not analyze_mode:
        if not args.delete_line and args.replacement is None:
            sys.stderr.write("Error: Either --replacement or --delete-line must be specified\n")
            return 1

        if args.delete_line and args.replacement is not None:
            sys.stderr.write("Error: Cannot specify both --replacement and --delete-line\n")
            return 1

    # Find matches using ripgrep
    if not args.quiet:
        print(f"Searching for pattern: {args.pattern}")

    matches = find_matches_with_ripgrep(
        pattern=args.pattern,
        path=args.path,
        ignore_case=args.ignore_case,
        glob=args.glob,
        file_type=args.type,
    )

    if not matches:
        if not args.quiet:
            print("No matches found.")
        return 0

    # Group matches by file
    files_to_process = {}
    for match in matches:
        if match.file_path not in files_to_process:
            files_to_process[match.file_path] = []
        files_to_process[match.file_path].append(match)

    if not args.quiet:
        print(f"Found {len(matches)} matches in {len(files_to_process)} files")

    # If analyze mode, just show statistics and exit
    if analyze_mode:
        stats = Statistics(
            total_files=len(files_to_process),
            total_matches=len(matches),
            matches_per_file=[len(m) for m in files_to_process.values()],
        )
        stats.display()

        # Show detailed per-file breakdown if verbose
        if args.verbose:
            print(f"\n{'='*60}")
            print("PER-FILE BREAKDOWN")
            print(f"{'='*60}")
            for file_path, file_matches in sorted(files_to_process.items(), key=lambda x: len(x[1]), reverse=True):
                print(f"{file_path}: {len(file_matches)} matches")
        return 0

    # Process each file
    total_replacements = 0
    total_deletions = 0
    failed_files = []
    stats = Statistics(total_files=len(files_to_process))
    results_by_file = {}  # Store results for dry-run mode

    for file_path, file_matches in files_to_process.items():
        if not args.dry_run and args.verbose:
            print(f"\nProcessing {file_path} ({len(file_matches)} matches)...")

        result = apply_replacements(
            file_path=file_path,
            pattern=args.pattern,
            replacement=args.replacement,
            delete_line=args.delete_line,
            first_only=args.first_only,
            specific_line=args.line_number,
            max_per_file=args.max_per_file,
            ignore_case=args.ignore_case,
            blank_on_delete=getattr(args, 'blank_on_delete', False),
        )

        if result.error:
            sys.stderr.write(f"Error processing {file_path}: {result.error}\n")
            failed_files.append(file_path)
            continue

        # Skip if no changes were made
        if result.replacements_made == 0 and result.lines_deleted == 0:
            if not args.dry_run and args.verbose:
                print(f"  No changes made (matches may have been filtered by options)")
            continue

        total_replacements += result.replacements_made
        total_deletions += result.lines_deleted

        # Update statistics
        stats.total_matches += result.matches_found
        stats.total_replacements += result.replacements_made
        stats.total_deletions += result.lines_deleted
        stats.matches_per_file.append(result.matches_found)

        if args.dry_run:
            # Store result for summary
            results_by_file[file_path] = result
        else:
            # Write the changes
            if write_file(file_path, result.modified_lines):
                if args.verbose:
                    if args.delete_line:
                        print(f"  [OK] Deleted {result.lines_deleted} lines")
                    else:
                        print(f"  [OK] Replaced {result.replacements_made} occurrences")
            else:
                failed_files.append(file_path)

    # Handle dry-run output
    if args.dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN - No changes will be made")
        print(f"{'='*60}")

        if args.verbose:
            # Show detailed diffs
            for idx, (file_path, result) in enumerate(results_by_file.items(), 1):
                print(f"\n[{idx}/{len(results_by_file)}] {file_path}", end="")
                if args.delete_line:
                    print(f" ({result.lines_deleted} lines to delete)")
                else:
                    print(f" ({result.replacements_made} replacements)")
                print(f"{'-'*60}")
                show_diff(result)
        else:
            # Show concise summary
            if args.delete_line:
                print(f"Would delete {total_deletions} lines across {len(results_by_file)} files:\n")
            else:
                print(f"Would make {total_replacements} replacements across {len(results_by_file)} files:\n")

            for file_path, result in sorted(results_by_file.items()):
                if args.delete_line:
                    print(f"  {str(file_path):<50} - {result.lines_deleted} lines")
                else:
                    print(f"  {str(file_path):<50} - {result.replacements_made} replacements")

            print(f"\n{'-'*60}")
            print(f"Files affected: {len(results_by_file)}")
            print(f"Total operations: {total_replacements + total_deletions}")
            print(f"{'='*60}\n")
            print("Run without --dry-run to apply changes")
            print("Run with --verbose to see detailed diffs")
            if not analyze_mode:
                print("Run with --interactive to review changes interactively")

        return 0  # Exit after dry-run

    # Print summary
    if not args.quiet:
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Files processed: {len(files_to_process) - len(failed_files)}/{len(files_to_process)}")

        if args.delete_line:
            print(f"Lines deleted: {total_deletions}")
        else:
            print(f"Replacements made: {total_replacements}")

        if failed_files:
            print(f"Failed files: {len(failed_files)}")
            for fp in failed_files:
                print(f"  - {fp}")

        if args.dry_run:
            print("\n(DRY RUN - no changes were made)")

    # Display detailed statistics if requested
    if getattr(args, 'show_stats', False):
        stats.display()

    return 1 if failed_files else 0
