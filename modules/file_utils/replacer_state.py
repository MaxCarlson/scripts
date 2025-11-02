"""
State management for interactive replacer mode.

Provides in-memory file state tracking, diff generation, and state cloning.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class FileContent:
    """
    Represents the content and metadata for a single file.

    Tracks both original (on-disk) and current (modified) state.
    """
    path: Path
    original_lines: List[str]
    current_lines: List[str]
    modifications: List[str] = field(default_factory=list)  # History of what changed

    @property
    def is_modified(self) -> bool:
        """Check if file has been modified from original."""
        return self.original_lines != self.current_lines

    @property
    def diff_stats(self) -> Tuple[int, int]:
        """
        Calculate diff statistics.

        Returns:
            Tuple of (additions, deletions)
        """
        if not self.is_modified:
            return (0, 0)

        additions = 0
        deletions = 0

        # Generate unified diff to count changes
        diff = difflib.unified_diff(
            self.original_lines,
            self.current_lines,
            lineterm='',
        )

        for line in diff:
            if line.startswith('+') and not line.startswith('+++'):
                additions += 1
            elif line.startswith('-') and not line.startswith('---'):
                deletions += 1

        return (additions, deletions)

    def get_unified_diff(self, context_lines: int = 3) -> str:
        """
        Generate a unified diff string.

        Args:
            context_lines: Number of context lines to show

        Returns:
            Unified diff string
        """
        diff = difflib.unified_diff(
            self.original_lines,
            self.current_lines,
            fromfile=str(self.path),
            tofile=str(self.path),
            lineterm='',
            n=context_lines,
        )
        return '\n'.join(diff)

    def clone(self) -> FileContent:
        """Create a deep copy of this file content."""
        return FileContent(
            path=self.path,
            original_lines=self.original_lines.copy(),
            current_lines=self.current_lines.copy(),
            modifications=self.modifications.copy(),
        )


class FileState:
    """
    Manages the state of all files at a point in time.

    Provides in-memory file storage, diff generation, and state cloning.
    """

    def __init__(self):
        self.files: Dict[Path, FileContent] = {}
        self.modified: Set[Path] = set()

    def add_file(self, path: Path, content: Optional[FileContent] = None):
        """
        Add a file to this state.

        Args:
            path: Path to the file
            content: Optional FileContent (will read from disk if None)
        """
        if content:
            self.files[path] = content
            if content.is_modified:
                self.modified.add(path)
        else:
            # Read from disk
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                self.files[path] = FileContent(
                    path=path,
                    original_lines=lines.copy(),
                    current_lines=lines.copy(),
                )
            except Exception as e:
                raise IOError(f"Failed to read {path}: {e}")

    def get_file(self, path: Path) -> Optional[FileContent]:
        """
        Get file content.

        Args:
            path: Path to the file

        Returns:
            FileContent or None if not found
        """
        return self.files.get(path)

    def set_file_content(self, path: Path, lines: List[str], modification_note: str = ""):
        """
        Update file content.

        Args:
            path: Path to the file
            lines: New content lines
            modification_note: Optional note about what changed
        """
        if path not in self.files:
            # Auto-add if not present
            self.add_file(path)

        file_content = self.files[path]
        file_content.current_lines = lines.copy()
        if modification_note:
            file_content.modifications.append(modification_note)

        # Track as modified
        if file_content.is_modified:
            self.modified.add(path)
        elif path in self.modified:
            self.modified.remove(path)

    def get_diff(self, path: Path, context_lines: int = 3) -> str:
        """
        Generate diff for a specific file.

        Args:
            path: Path to the file
            context_lines: Number of context lines

        Returns:
            Unified diff string
        """
        file_content = self.files.get(path)
        if not file_content:
            return ""

        return file_content.get_unified_diff(context_lines)

    def get_all_diffs(self, context_lines: int = 3) -> Dict[Path, str]:
        """
        Generate diffs for all modified files.

        Args:
            context_lines: Number of context lines

        Returns:
            Dictionary mapping paths to their diffs
        """
        diffs = {}
        for path in self.modified:
            diffs[path] = self.get_diff(path, context_lines)
        return diffs

    def get_diff_stats(self, path: Path) -> Tuple[int, int]:
        """
        Get diff statistics for a file.

        Args:
            path: Path to the file

        Returns:
            Tuple of (additions, deletions)
        """
        file_content = self.files.get(path)
        if not file_content:
            return (0, 0)
        return file_content.diff_stats

    def clone(self) -> FileState:
        """
        Create a deep copy of this state.

        Returns:
            New FileState with cloned content
        """
        new_state = FileState()
        for path, file_content in self.files.items():
            new_state.files[path] = file_content.clone()
        new_state.modified = self.modified.copy()
        return new_state

    def write_to_disk(self) -> List[Path]:
        """
        Write all modified files to disk.

        Returns:
            List of paths that were successfully written
        """
        written = []
        for path in self.modified:
            file_content = self.files[path]
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(file_content.current_lines)
                written.append(path)
            except Exception as e:
                # Log error but continue with other files
                import sys
                sys.stderr.write(f"Failed to write {path}: {e}\n")
        return written

    def get_modified_files(self) -> List[Path]:
        """Get list of all modified file paths."""
        return sorted(self.modified)

    def has_modifications(self) -> bool:
        """Check if any files have been modified."""
        return len(self.modified) > 0

    def get_total_stats(self) -> Tuple[int, int]:
        """
        Get total diff statistics across all files.

        Returns:
            Tuple of (total_additions, total_deletions)
        """
        total_additions = 0
        total_deletions = 0

        for path in self.modified:
            additions, deletions = self.get_diff_stats(path)
            total_additions += additions
            total_deletions += deletions

        return (total_additions, total_deletions)

    def __repr__(self) -> str:
        """String representation of state."""
        return f"FileState(files={len(self.files)}, modified={len(self.modified)})"
