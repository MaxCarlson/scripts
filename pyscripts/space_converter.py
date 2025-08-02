#!/usr/bin/env python3
import argparse
import sys
import subprocess
from pathlib import Path
from collections import defaultdict
import argcomplete

# --- Default Configuration ---
# File extensions to ignore by default.
DEFAULT_IGNORE_EXTS = {
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.o',
    '.a', '.lib', '.obj', '.class', '.jar',
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.db', '.sqlite3', '.db3',
    '.mp3', '.mp4', '.mkv', '.avi', '.mov',
    '.iso', '.img',
    '.lock', '.log'
}

def check_git_status(repo_path: Path) -> str:
    """Checks if a Git repository has unstaged changes using 'git status --porcelain'."""
    if not (repo_path / '.git').exists():
        return "not_a_repo"
    
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return "dirty" if result.stdout.strip() else "clean"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "error"

def analyze_and_convert_file(file_path: Path, to_spaces: int, stats: dict, args: argparse.Namespace):
    """
    Analyzes a file's indentation line-by-line and converts it if necessary.
    This handles files with mixed indentation.
    """
    if file_path.suffix.lower() in args.ignore_ext:
        if args.verbose:
            print(f"Ignoring by extension: {file_path}")
        stats['files_skipped_ext'] += 1
        return

    stats['files_processed'] += 1
    
    try:
        try:
            with file_path.open('r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with file_path.open('r', encoding=sys.getdefaultencoding(), errors='ignore') as f:
                lines = f.readlines()
            if args.verbose:
                print(f"Warning: Fell back to system encoding for {file_path}")

        new_lines = []
        file_was_changed = False
        loc_2_space_in_file = 0
        loc_4_space_in_file = 0

        for line in lines:
            if not line.strip() or not line.startswith(' '):
                new_lines.append(line)
                continue

            lstripped = line.lstrip(' ')
            leading_spaces = len(line) - len(lstripped)
            
            current_line_indent_base = 0
            indent_level = 0

            if leading_spaces % 4 == 0:
                current_line_indent_base = 4
                indent_level = leading_spaces // 4
                loc_4_space_in_file += 1
            elif leading_spaces % 2 == 0:
                current_line_indent_base = 2
                indent_level = leading_spaces // 2
                loc_2_space_in_file += 1
            else:
                new_lines.append(line)
                continue
            
            if current_line_indent_base == to_spaces:
                new_lines.append(line)
                continue

            new_indent = (' ' * to_spaces) * indent_level
            new_lines.append(new_indent + lstripped)
            file_was_changed = True

        stats['loc_2_space'] += loc_2_space_in_file
        stats['loc_4_space'] += loc_4_space_in_file

        if not file_was_changed:
            if args.verbose:
                print(f"Skipping (no convertible lines found): {file_path}")
            return
        
        if loc_2_space_in_file > loc_4_space_in_file:
            stats['files_2_space'] += 1
        elif loc_4_space_in_file > loc_2_space_in_file:
            stats['files_4_space'] += 1
        else:
            stats['files_mixed_indent'] += 1

        print(f"Found: {file_path} (Contains convertible lines, target: {to_spaces}-space)")

        if args.dry_run:
            stats['files_to_change'] += 1
            return

        with file_path.open('w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        stats['files_changed'] += 1

    except Exception as e:
        print(f"Error processing file {file_path}: {e}", file=sys.stderr)
        stats['files_error'] += 1

def process_path(path: Path, to_spaces: int, stats: dict, args: argparse.Namespace, current_depth: int, initial_paths: set):
    """Recursively processes a path, with safety checks for Git repositories."""
    if not path.exists():
        print(f"Error: Path does not exist: {path}", file=sys.stderr)
        return

    if path.is_file():
        analyze_and_convert_file(path, to_spaces, stats, args)
        return

    if path.is_dir():
        is_git_repo = (path / '.git').exists()
        if is_git_repo and path not in initial_paths:
            if args.ignore_git_repos:
                if args.verbose:
                    print(f"Ignoring Git repository (via flag): {path}")
                stats['git_repos_skipped'] += 1
                return
            
            git_status = check_git_status(path)
            if git_status == "dirty":
                print(f"\nWarning: Git repository at '{path}' has unstaged changes.", file=sys.stderr)
                choice = ""
                while choice not in ['s', 'a', 'c']:
                    choice = input("Choose an action: (s)kip this repo, (a)bort script, (c)ontinue anyway? ").lower()
                if choice == 's':
                    print(f"Skipping repository: {path}")
                    stats['git_repos_skipped'] += 1
                    return
                if choice == 'a':
                    print("\nAborting script by user choice.")
                    sys.exit(1)

            if path not in stats['warned_git_repos']:
                stats['warned_git_repos'].add(path)
                choice = input(f"Found Git repository at '{path}'. Process files inside? (y/n): ").lower()
                if choice != 'y':
                    print(f"Skipping repository: {path}")
                    stats['git_repos_skipped'] += 1
                    return

        if not args.recursive and path not in initial_paths:
            return
            
        if args.depth != -1 and current_depth >= args.depth:
            if args.verbose:
                print(f"Max depth reached, not recursing into: {path}")
            return

        for item in path.iterdir():
            process_path(item, to_spaces, stats, args, current_depth + 1, initial_paths)

def setup_arg_parser() -> argparse.ArgumentParser:
    """Sets up the argument parser."""
    parser = argparse.ArgumentParser(
        description="Recursively convert 2-space or 4-space indented files.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'paths',
        nargs='+',
        type=Path,
        help="One or more file or folder paths to process."
    )
    parser.add_argument(
        '-t', '--to-spaces',
        type=int,
        choices=[2, 4],
        required=True,
        help="The target number of spaces for indentation (2 or 4)."
    )
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help="Process folders recursively."
    )
    parser.add_argument(
        '-d', '--depth',
        type=int,
        default=-1,
        help="Maximum recursion depth. -1 for infinite. (Default: -1)"
    )
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help="Show which files would be changed without modifying them."
    )
    parser.add_argument(
        '-i', '--ignore-ext',
        nargs='+',
        default=DEFAULT_IGNORE_EXTS,
        help="A list of file extensions to ignore (e.g., .log .tmp .lock).\n"
             "Defaults to a list of common binary/compressed formats."
    )
    parser.add_argument(
        '-g', '--ignore-git-repos',
        action='store_true',
        help="Automatically skip processing any discovered Git repositories in subfolders."
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Enable verbose output, showing skipped files and other details."
    )
    return parser

def main():
    """Main entry point for the script."""
    parser = setup_arg_parser()
    
    # This is the magic line that enables tab completion.
    # It must be called after the parser is created and before parse_args().
    argcomplete.autocomplete(parser)
    
    args = parser.parse_args()

    args.ignore_ext = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in args.ignore_ext}
    stats = defaultdict(int)
    stats['warned_git_repos'] = set()
    initial_paths = set(p.resolve() for p in args.paths)

    if args.dry_run:
        print("--- DRY RUN MODE: No files will be modified. ---")

    for path in args.paths:
        process_path(path.resolve(), args.to_spaces, stats, args, 0, initial_paths)

    print("\n" + "="*30)
    print("      Conversion Summary")
    print("="*30)
    print(f"Files Processed: {stats['files_processed']}")
    print(f"Files with mostly 2-space: {stats['files_2_space']}")
    print(f"Files with mostly 4-space: {stats['files_4_space']}")
    print(f"Files with mixed/other: {stats['files_mixed_indent']}")
    print(f"  - Total 2-space LOC found: {stats['loc_2_space']}")
    print(f"  - Total 4-space LOC found: {stats['loc_4_space']}")
    print("-" * 30)
    print(f"Skipped (by extension): {stats['files_skipped_ext']}")
    print(f"Skipped (Git repos): {stats['git_repos_skipped']}")
    print(f"Errors: {stats['files_error']}")
    print("-" * 30)
    if args.dry_run:
        print(f"Files that would be changed: {stats['files_to_change']}")
    else:
        print(f"Files successfully changed: {stats['files_changed']}")
    print("="*30)

if __name__ == "__main__":
    main()
