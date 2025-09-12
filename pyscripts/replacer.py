#!/usr/bin/env python3
"""
A script to find and replace text in files, with a dry-run mode that
mimics ripgrep's output.
"""

import argparse
import os
import re
import sys
import glob
from pathlib import Path

# The 'rich' library is used for beautiful, colored output.
try:
    from rich.console import Console
    from rich.theme import Theme
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Error: The 'rich' library is required. Please install it with 'pip install rich'")
    sys.exit(1)

# A custom theme to control the output colors, similar to ripgrep.
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "path": "bold green",
    "line_num": "cyan",
    "match": "bold yellow on red",
    "summary_header": "bold blue",
})

console = Console(theme=custom_theme)

class Replacer:
    """
    Handles the logic for finding, validating, and replacing text across files.
    """
    def __init__(self, args):
        self.pattern = args.pattern
        self.replacement = args.replacement
        self.paths = args.path
        self.is_dry_run = not args.write
        self.is_verbose = args.verbose
        self.ignore_case = args.ignore_case
        self.exclusions = args.exclude if args.exclude else []

        # Exclude common version control and cache directories by default.
        self.default_exclusions = ['.git', '.svn', '.hg', '__pycache__']
        self.user_exclusions = list(self.exclusions) # Keep a copy for the summary
        self.exclusions.extend(self.default_exclusions)

        self.stats = {
            "files_scanned": 0,
            "files_matched": 0,
            "total_replacements": 0,
        }
        
        self.compiled_pattern = self._compile_pattern()
        self.expanded_exclusions = self._expand_globs(self.exclusions)

    def _compile_pattern(self):
        """Compiles the user's regex pattern with optional flags."""
        try:
            flags = re.IGNORECASE if self.ignore_case else 0
            return re.compile(self.pattern, flags)
        except re.error as e:
            console.print(f"Error: Invalid regular expression: '{self.pattern}'", style="danger")
            console.print(f"Details: {e}", style="danger")
            sys.exit(1)

    def _expand_globs(self, glob_patterns):
        """Expands a list of glob patterns into a set of absolute paths for matching."""
        expanded_paths = set()
        if not glob_patterns:
            return expanded_paths
        for pattern in glob_patterns:
            try:
                # Use recursive=True to handle '**' for nested directories.
                matches = glob.glob(pattern, recursive=True)
                for match in matches:
                    expanded_paths.add(Path(match).resolve())
            except Exception as e:
                console.print(f"Warning: Could not expand glob pattern '{pattern}': {e}", style="warning")
        return expanded_paths

    def _is_excluded(self, path_obj):
        """Checks if a file or directory path should be excluded from the search."""
        resolved_path = path_obj.resolve()
        
        # Check if the path itself or any of its parent directories match an exclusion pattern.
        if resolved_path in self.expanded_exclusions:
            return True
        for parent in resolved_path.parents:
            if parent in self.expanded_exclusions:
                return True
                
        # Also check parts of the path for default directory names like '.git'.
        for part in resolved_path.parts:
            if part in self.default_exclusions:
                return True

        return False

    def _gather_files(self):
        """Walks the target paths and yields files that are not excluded."""
        for path_str in self.paths:
            for item_path in glob.glob(path_str, recursive=True):
                path_obj = Path(item_path)

                if not path_obj.exists():
                    console.print(f"Warning: Path does not exist: {path_obj}", style="warning")
                    continue

                if self._is_excluded(path_obj):
                    continue

                if path_obj.is_dir():
                    for root, dirs, files in os.walk(path_obj, topdown=True):
                        root_path = Path(root)
                        # Filter out excluded directories in-place to prevent os.walk from traversing them.
                        dirs[:] = [d for d in dirs if not self._is_excluded(root_path / d)]
                        for file in files:
                            file_path = root_path / file
                            if not self._is_excluded(file_path):
                                self.stats["files_scanned"] += 1
                                yield file_path
                elif path_obj.is_file():
                    self.stats["files_scanned"] += 1
                    yield path_obj
    
    def run(self):
        """The main execution method that coordinates the find-and-replace operation."""
        if self.is_dry_run:
            console.print("--- Starting Dry Run (no files will be changed) ---", style="info")
        else:
            console.print("--- Starting Replacement (files WILL be changed) ---", style="warning")
        
        for file_path in self._gather_files():
            self._process_file(file_path)
            
        self._print_summary()

    def _process_file(self, file_path):
        """Reads a single file and performs the find/replace operation."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except (IOError, OSError) as e:
            console.print(f"Warning: Could not read file {file_path}: {e}", style="warning")
            return

        matches = list(self.compiled_pattern.finditer(content))
        if not matches:
            return

        self.stats["files_matched"] += 1
        num_replacements_in_file = len(matches)
        self.stats["total_replacements"] += num_replacements_in_file

        if self.is_dry_run:
            relative_path = os.path.relpath(file_path)
            verbose_info = f" ({num_replacements_in_file} replacements)" if self.is_verbose else ""
            console.print(f"\n{relative_path}{verbose_info}", style="path")

            lines = content.splitlines()
            lines_with_matches = {}
            for match in matches:
                line_num = content.count('\n', 0, match.start()) + 1
                if line_num not in lines_with_matches:
                    lines_with_matches[line_num] = []
                lines_with_matches[line_num].append(match)

            for line_num, line_matches in sorted(lines_with_matches.items()):
                if line_num > len(lines): continue
                
                line_content = lines[line_num - 1]
                display_text = Text()
                display_text.append(f"{line_num}:", style="line_num")
                display_text.append(" ")
                
                current_pos_in_line = 0
                line_start_pos_in_content = content.rfind('\n', 0, line_matches[0].start()) + 1

                for match in sorted(line_matches, key=lambda m: m.start()):
                    match_start_in_line = match.start() - line_start_pos_in_content
                    match_end_in_line = match.end() - line_start_pos_in_content
                    
                    display_text.append(line_content[current_pos_in_line:match_start_in_line])
                    display_text.append(line_content[match_start_in_line:match_end_in_line], style="match")
                    current_pos_in_line = match_end_in_line

                display_text.append(line_content[current_pos_in_line:])
                console.print(display_text)
        else:
            new_content = self.compiled_pattern.sub(self.replacement, content)
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            except (IOError, OSError) as e:
                console.print(f"Error: Could not write to file {file_path}: {e}", style="danger")
    
    def _print_summary(self):
        """Prints the final summary of the operation in a clean table."""
        console.print("\n--- Summary ---", style="summary_header")

        table = Table(show_header=False, box=None)
        table.add_column(style="info")
        table.add_column()
        
        op_type = "found" if self.is_dry_run else "made"
        file_change_type = "Files to be changed" if self.is_dry_run else "Files changed"

        table.add_row("Total replacements:", f"[bold white]{self.stats['total_replacements']}[/bold white] {op_type}")
        table.add_row(f"{file_change_type}:", f"[bold white]{self.stats['files_matched']}[/bold white]")
        table.add_row("Files scanned:", f"[bold white]{self.stats['files_scanned']}[/bold white]")

        console.print(table)
        
        if self.user_exclusions:
            console.print("\nUser-defined exclusion patterns:", style="summary_header")
            for pattern in self.user_exclusions:
                console.print(f"- {pattern}", style="info")
        
        if not self.is_dry_run and self.stats["total_replacements"] > 0:
            console.print("\n✅ All changes have been written to disk.", style="bold green")
        elif self.is_dry_run and self.stats["total_replacements"] > 0:
            console.print("\nTo apply these changes, re-run the command with the -w or --write flag.", style="warning")

def main():
    """Parses command-line arguments and runs the replacer."""
    parser = argparse.ArgumentParser(
        description="A script to find and replace text in files, using regex and honoring ignores.",
        epilog="By default, runs in a dry-run mode. Use -w or --write to apply changes.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument("pattern", help="The search pattern (regular expression).")
    parser.add_argument("replacement", help="The replacement string.")
    
    parser.add_argument(
        "-p", "--path", 
        nargs='+', 
        default=['.'],
        help="One or more files or directories to search in.\nSupports globs (e.g., 'src/**/*.py'). Defaults to the current directory."
    )
    parser.add_argument(
        "-w", "--write",
        action="store_true",
        help="Write changes to disk. Without this flag, the script runs in dry-run mode."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="In dry-run mode, show the number of replacements to be made next to each filename."
    )
    parser.add_argument(
        "-i", "--ignore-case",
        action="store_true",
        help="Perform a case-insensitive search."
    )
    parser.add_argument(
        "-x", "--exclude",
        nargs='+',
        help="One or more files, directories, or glob patterns to exclude from the search."
    )

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    replacer = Replacer(args)
    replacer.run()

if __name__ == "__main__":
    main()
