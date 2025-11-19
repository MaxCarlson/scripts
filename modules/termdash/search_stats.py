#!/usr/bin/env python3
"""
TermDash Search Statistics Component

Reusable component for tracking and displaying file search statistics.
Used by file_utils.lister and potentially other search-based tools.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from cross_platform.size_utils import format_bytes_binary


@dataclass
class SearchStats:
    """
    Statistics tracker for file/directory searching operations.

    Tracks:
    - Files/directories searched and found
    - Bytes searched and found
    - Search rate (files/second)
    - Match percentage
    - Elapsed time

    Example:
        >>> stats = SearchStats()
        >>> stats.files_searched = 1000
        >>> stats.files_found = 50
        >>> stats.bytes_searched = 1024 * 1024 * 100  # 100 MB
        >>> stats.bytes_found = 1024 * 1024 * 5  # 5 MB
        >>> print(stats.format_summary())
        Searched: 1,000 files (100.0 MB) | Found: 50 files (5.0 MB) | Match: 5.0% | Rate: 500 files/sec | Time: 2.0s
    """

    files_searched: int = 0
    files_found: int = 0
    dirs_searched: int = 0
    bytes_searched: int = 0
    bytes_found: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    def elapsed(self) -> float:
        """Return elapsed time in seconds."""
        end = self.end_time if self.end_time else time.time()
        return max(0.001, end - self.start_time)

    def files_per_second(self) -> float:
        """Calculate search rate in files per second."""
        return self.files_searched / self.elapsed()

    def dirs_per_second(self) -> float:
        """Calculate directory traversal rate."""
        return self.dirs_searched / self.elapsed()

    def bytes_per_second(self) -> float:
        """Calculate bytes scanned per second."""
        return self.bytes_searched / self.elapsed()

    def match_percentage(self) -> float:
        """Calculate percentage of files matching search criteria."""
        if self.files_searched == 0:
            return 0.0
        return (self.files_found / self.files_searched) * 100.0

    def format_summary(self, *, compact: bool = False) -> str:
        """
        Format statistics as human-readable string.

        Args:
            compact: If True, use abbreviated format for space-constrained displays

        Returns:
            Formatted statistics string
        """
        if compact:
            return (
                f"{self.files_found:,} files ({format_bytes_binary(self.bytes_found)}) | "
                f"{self.match_percentage():.1f}% | "
                f"{self.files_per_second():.0f}/s"
            )

        return (
            f"Searched: {self.files_searched:,} files ({format_bytes_binary(self.bytes_searched)}) | "
            f"Found: {self.files_found:,} files ({format_bytes_binary(self.bytes_found)}) | "
            f"Match: {self.match_percentage():.1f}% | "
            f"Rate: {self.files_per_second():.0f} files/sec | "
            f"Time: {self.elapsed():.1f}s"
        )

    def format_progress(self) -> str:
        """
        Format as progress message (for real-time updates during scan).

        Returns:
            Progress string suitable for terminal output
        """
        return (
            f"Scanning... {self.files_searched:,} files searched, "
            f"{self.files_found:,} found ({self.match_percentage():.1f}%), "
            f"{self.files_per_second():.0f} files/sec"
        )

    def format_footer(self) -> str:
        """
        Format as footer line for TUI displays.

        Returns:
            Footer string with key statistics
        """
        return (
            f"Found: {self.files_found:,} files ({format_bytes_binary(self.bytes_found)}) │ "
            f"Match: {self.match_percentage():.1f}% │ "
            f"Rate: {self.files_per_second():.0f} files/sec"
        )

    def increment_file(self, size_bytes: int = 0, *, matches: bool = False) -> None:
        """
        Increment file counters.

        Args:
            size_bytes: Size of the file in bytes
            matches: Whether the file matches the search criteria
        """
        self.files_searched += 1
        self.bytes_searched += size_bytes

        if matches:
            self.files_found += 1
            self.bytes_found += size_bytes

    def increment_dir(self) -> None:
        """Increment directory counter."""
        self.dirs_searched += 1

    def finish(self) -> None:
        """Mark the search as finished."""
        self.end_time = time.time()

    def reset(self) -> None:
        """Reset all counters to zero."""
        self.files_searched = 0
        self.files_found = 0
        self.dirs_searched = 0
        self.bytes_searched = 0
        self.bytes_found = 0
        self.start_time = time.time()
        self.end_time = None
