#!/usr/bin/env python3
"""
Filter Stack System for File Lister

Manages multiple filters/excludes applied sequentially with the ability to:
- Add/remove filters
- Toggle between include/exclude mode
- Enable/disable filters temporarily
- Reorder filters
- Apply filters sequentially (pipeline)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Callable, Any
import re


class FilterMode(Enum):
    """Filter application mode."""
    INCLUDE = "include"  # Keep matching items
    EXCLUDE = "exclude"  # Remove matching items


class FilterType(Enum):
    """Type of filter criterion."""
    EXTENSION = "ext"
    SIZE_RANGE = "size"
    NAME_GLOB = "name"
    NAME_REGEX = "regex"
    CUSTOM = "custom"


@dataclass
class FilterCriterion:
    """
    A single filter criterion that can be applied to entries.

    Supports:
    - Include/Exclude mode
    - Enable/Disable state
    - Multiple types of filters
    """
    filter_type: FilterType
    mode: FilterMode = FilterMode.INCLUDE
    enabled: bool = True
    description: str = ""

    # Filter-specific data
    extensions: Optional[List[str]] = None  # For EXTENSION type
    min_size: Optional[int] = None  # For SIZE_RANGE type
    max_size: Optional[int] = None  # For SIZE_RANGE type
    name_pattern: Optional[str] = None  # For NAME_GLOB type
    name_regex: Optional[re.Pattern] = None  # For NAME_REGEX type
    case_sensitive: bool = False

    # Custom filter function (for extensibility)
    custom_filter: Optional[Callable[[Any], bool]] = None

    def matches(self, entry: Any) -> bool:
        """Check if entry matches this filter criterion."""
        if self.filter_type == FilterType.EXTENSION:
            if not self.extensions or entry.is_dir:
                return True
            from cross_platform.fs_utils import matches_ext
            return any(matches_ext(entry.path, ext, case_sensitive=self.case_sensitive)
                      for ext in self.extensions)

        elif self.filter_type == FilterType.SIZE_RANGE:
            if entry.is_dir:
                return True
            if self.min_size is not None and entry.size < self.min_size:
                return False
            if self.max_size is not None and entry.size > self.max_size:
                return False
            return True

        elif self.filter_type == FilterType.NAME_GLOB:
            if not self.name_pattern:
                return True
            from fnmatch import fnmatch
            name = entry.name if self.case_sensitive else entry.name.lower()
            pattern = self.name_pattern if self.case_sensitive else self.name_pattern.lower()
            return fnmatch(name, pattern)

        elif self.filter_type == FilterType.NAME_REGEX:
            if not self.name_regex:
                return True
            return bool(self.name_regex.search(entry.name))

        elif self.filter_type == FilterType.CUSTOM:
            if self.custom_filter:
                return self.custom_filter(entry)
            return True

        return True

    def apply(self, entries: List[Any]) -> List[Any]:
        """
        Apply this filter to a list of entries.

        Returns:
            Filtered list based on mode (INCLUDE or EXCLUDE)
        """
        if not self.enabled:
            return entries

        if self.mode == FilterMode.INCLUDE:
            # Keep only matching items
            return [e for e in entries if self.matches(e)]
        else:  # EXCLUDE
            # Remove matching items
            return [e for e in entries if not self.matches(e)]

    def describe(self) -> str:
        """Return human-readable description."""
        if self.description:
            return self.description

        parts = []

        if self.filter_type == FilterType.EXTENSION:
            if self.extensions:
                if len(self.extensions) == 1:
                    parts.append(f"ext={self.extensions[0]}")
                else:
                    parts.append(f"ext={{{','.join(self.extensions)}}}")

        elif self.filter_type == FilterType.SIZE_RANGE:
            from cross_platform.size_utils import format_bytes_binary
            if self.min_size is not None:
                parts.append(f"size>={format_bytes_binary(self.min_size)}")
            if self.max_size is not None:
                parts.append(f"size<={format_bytes_binary(self.max_size)}")

        elif self.filter_type == FilterType.NAME_GLOB:
            if self.name_pattern:
                parts.append(f"name={self.name_pattern}")

        elif self.filter_type == FilterType.NAME_REGEX:
            if self.name_regex:
                parts.append(f"regex={self.name_regex.pattern}")

        elif self.filter_type == FilterType.CUSTOM:
            parts.append("custom")

        desc = " AND ".join(parts) if parts else "empty"

        # Add mode indicator
        if not self.enabled:
            desc = f"[DISABLED] {desc}"

        return desc

    def get_display_line(self, index: int, selected: bool = False) -> str:
        """Format for display in filter stack panel."""
        mode_symbol = "✓" if self.mode == FilterMode.INCLUDE else "✗"
        enabled_symbol = "●" if self.enabled else "○"

        cursor = "→" if selected else " "

        desc = self.describe()

        return f"{cursor} {index + 1}. {enabled_symbol} {mode_symbol} {desc}"


@dataclass
class FilterStack:
    """
    Manages a stack of filters applied sequentially.

    Filters are applied in order:
    1. Filter 1 (include/exclude)
    2. Filter 2 (applied to Filter 1 result)
    3. Filter 3 (applied to Filter 2 result)
    etc.
    """
    filters: List[FilterCriterion] = field(default_factory=list)
    selected_index: int = 0  # For UI navigation

    def add_filter(self, criterion: FilterCriterion) -> None:
        """Add a new filter to the end of the stack."""
        self.filters.append(criterion)

    def remove_filter(self, index: int) -> bool:
        """Remove filter at index. Returns True if successful."""
        if 0 <= index < len(self.filters):
            self.filters.pop(index)
            # Adjust selected index if needed
            if self.selected_index >= len(self.filters) and self.filters:
                self.selected_index = len(self.filters) - 1
            elif not self.filters:
                self.selected_index = 0
            return True
        return False

    def toggle_mode(self, index: int) -> bool:
        """Toggle filter between INCLUDE and EXCLUDE mode."""
        if 0 <= index < len(self.filters):
            f = self.filters[index]
            f.mode = FilterMode.EXCLUDE if f.mode == FilterMode.INCLUDE else FilterMode.INCLUDE
            return True
        return False

    def toggle_enabled(self, index: int) -> bool:
        """Toggle filter enabled state."""
        if 0 <= index < len(self.filters):
            self.filters[index].enabled = not self.filters[index].enabled
            return True
        return False

    def move_up(self, index: int) -> bool:
        """Move filter up in the stack (applied earlier)."""
        if 0 < index < len(self.filters):
            self.filters[index], self.filters[index - 1] = \
                self.filters[index - 1], self.filters[index]
            return True
        return False

    def move_down(self, index: int) -> bool:
        """Move filter down in the stack (applied later)."""
        if 0 <= index < len(self.filters) - 1:
            self.filters[index], self.filters[index + 1] = \
                self.filters[index + 1], self.filters[index]
            return True
        return False

    def clear(self) -> None:
        """Remove all filters."""
        self.filters.clear()
        self.selected_index = 0

    def apply(self, entries: List[Any]) -> List[Any]:
        """
        Apply all filters sequentially to the entry list.

        Returns:
            Filtered list after all filters have been applied
        """
        result = entries
        for f in self.filters:
            if f.enabled:
                result = f.apply(result)
        return result

    def describe(self) -> str:
        """Return human-readable description of the filter stack."""
        if not self.filters:
            return "No filters"

        enabled_filters = [f for f in self.filters if f.enabled]
        if not enabled_filters:
            return "All filters disabled"

        parts = []
        for f in enabled_filters:
            mode = "INCLUDE" if f.mode == FilterMode.INCLUDE else "EXCLUDE"
            parts.append(f"{mode}({f.describe()})")

        return " → ".join(parts)

    def get_display_lines(self) -> List[str]:
        """Get all filter lines for display in UI panel."""
        if not self.filters:
            return ["(No filters - press F to add)"]

        return [f.get_display_line(i, i == self.selected_index)
                for i, f in enumerate(self.filters)]

    def has_filters(self) -> bool:
        """Check if any enabled filters exist."""
        return any(f.enabled for f in self.filters)

    def count_enabled(self) -> int:
        """Count number of enabled filters."""
        return sum(1 for f in self.filters if f.enabled)
