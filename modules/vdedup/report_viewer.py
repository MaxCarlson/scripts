from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from termdash.interactive_list import InteractiveList, render_items_to_text

from .report_models import DuplicateGroup, FileStats, load_report_groups

ANSI_RESET = "\033[0m"
ANSI_KEEP = "\033[92m"   # Bright green
ANSI_LOSE = "\033[91m"   # Bright red
ANSI_METHOD = "\033[96m"  # Cyan
ANSI_STATS = "\033[95m"   # Magenta

NAME_MIN_WIDTH = 30
DUP_WIDTH = 4
RECLAIM_WIDTH = 12
SIZE_WIDTH = 12
DELTA_WIDTH = 8
COLUMN_SPACING = 1


def _fmt_bytes(n: int) -> str:
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n/1024:.2f} KiB"
    if n < 1024**3:
        return f"{n/1024**2:.2f} MiB"
    return f"{n/1024**3:.2f} GiB"


def _fmt_signed_bytes(delta: int) -> str:
    prefix = "+" if delta >= 0 else "-"
    return f"{prefix}{_fmt_bytes(abs(delta))}"


def _term_width(default: int = 120) -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return default


def _compute_layout(width: int) -> Tuple[int, int, int, int, int]:
    meta_width = (
        DUP_WIDTH
        + RECLAIM_WIDTH
        + SIZE_WIDTH
        + DELTA_WIDTH
        + COLUMN_SPACING * 4
    )
    name_width = max(NAME_MIN_WIDTH, width - meta_width)
    return name_width, DUP_WIDTH, RECLAIM_WIDTH, SIZE_WIDTH, DELTA_WIDTH


def _column_header(width: int) -> str:
    name_width, dup_w, reclaim_w, size_w, delta_w = _compute_layout(width)
    return (
        f"{'NAME':<{name_width}}"
        f"{'':<{COLUMN_SPACING}}"
        f"{'DUP':>{dup_w}}"
        f"{'':<{COLUMN_SPACING}}"
        f"{'RECLAIM':>{reclaim_w}}"
        f"{'':<{COLUMN_SPACING}}"
        f"{'SIZE':>{size_w}}"
        f"{'':<{COLUMN_SPACING}}"
        f"{'Δ':>{delta_w}}"
    )


def _unique_suffixes(paths: Sequence[Path]) -> Dict[Path, str]:
    if not paths:
        return {}
    parts_map = {path: list(path.parts) for path in paths}
    max_depth = max(len(parts) for parts in parts_map.values())
    result: Dict[Path, str] = {}

    for depth in range(1, max_depth + 1):
        suffix_map: Dict[Tuple[str, ...], List[Path]] = {}
        for path, parts in parts_map.items():
            if path in result:
                continue
            suffix = tuple(parts[-depth:])
            suffix_map.setdefault(suffix, []).append(path)
        for suffix, entries in suffix_map.items():
            if len(entries) == 1:
                path = entries[0]
                result[path] = "/".join(suffix)
        if len(result) == len(paths):
            break

    for path in paths:
        if path not in result:
            result[path] = str(path)
    return result


@dataclass(slots=True)
class DuplicateListRow:
    group_id: str
    method: str
    path: Path
    depth: int
    is_keep: bool
    size: int
    size_delta: int
    duplicate_count: int
    reclaimable_bytes: int
    parent_path: Optional[str]
    keep_size: int
    expanded: bool = False
    display_name: str = ""

    def is_loser(self) -> bool:
        return not self.is_keep


class DuplicateListManager:
    def __init__(self, groups: Iterable[DuplicateGroup]):
        self._groups = list(groups)
        self._expanded: set[str] = set()

    def toggle(self, group_id: str) -> None:
        if group_id in self._expanded:
            self._expanded.discard(group_id)
        else:
            self._expanded.add(group_id)

    def collapse(self, group_id: str) -> None:
        self._expanded.discard(group_id)

    def expand_all(self) -> None:
        self._expanded = {g.group_id for g in self._groups}

    def collapse_all(self) -> None:
        self._expanded.clear()

    def is_expanded(self, group_id: str) -> bool:
        return group_id in self._expanded

    def visible_rows(self) -> List[DuplicateListRow]:
        rows: List[DuplicateListRow] = []
        for group in self._groups:
            keep = group.keep
            keep_row = DuplicateListRow(
                group_id=group.group_id,
                method=group.method,
                path=keep.path,
                depth=0,
                is_keep=True,
                size=keep.size,
                size_delta=0,
                duplicate_count=group.duplicate_count,
                reclaimable_bytes=group.reclaimable_bytes,
                parent_path=None,
                keep_size=keep.size,
                expanded=self.is_expanded(group.group_id),
            )
            rows.append(keep_row)

            if self.is_expanded(group.group_id):
                for loser in group.losers:
                    rows.append(
                        DuplicateListRow(
                            group_id=group.group_id,
                            method=group.method,
                            path=loser.path,
                            depth=1,
                            is_keep=False,
                            size=loser.size,
                            size_delta=loser.size - keep.size,
                            duplicate_count=group.duplicate_count,
                            reclaimable_bytes=group.reclaimable_bytes,
                            parent_path=group.group_id,
                            keep_size=keep.size,
                        )
                    )
        return rows

    @property
    def groups(self) -> List[DuplicateGroup]:
        return self._groups


def _formatter(row: DuplicateListRow, sort_field: str, width: int, *_args) -> str:
    indent = "  " * row.depth
    label = "KEEP" if row.is_keep else "LOSE"
    method = f"[{row.method}]"
    name_part = f"{indent}{label} {method} {row.path}"

    if row.is_keep:
        stats = f"dup:{row.duplicate_count} | reclaim:{_fmt_bytes(row.reclaimable_bytes)} | keep:{_fmt_bytes(row.size)}"
    else:
        stats = f"size:{_fmt_bytes(row.size)} | Δ:{_fmt_signed_bytes(row.size_delta)}"

    stats_len = len(stats) + 2
    name_width = max(20, width - stats_len)
    if len(name_part) > name_width:
        name_part = name_part[:name_width - 3] + "..."
    else:
        name_part = name_part.ljust(name_width)

    return f"{name_part}  {stats}"


def _filter(row: DuplicateListRow, pattern: str) -> bool:
    pattern_lower = pattern.lower()
    return pattern_lower in str(row.path).lower()


def _detail(row: DuplicateListRow) -> List[str]:
    lines = [
        f"Method      : {row.method}",
        f"Group ID    : {row.group_id}",
        f"Path        : {row.path}",
        f"Role        : {'KEEP' if row.is_keep else 'LOSE'}",
        f"Size        : {_fmt_bytes(row.size)} ({row.size:,} bytes)",
    ]
    if not row.is_keep:
        lines.append(f"Δ vs keep   : {_fmt_signed_bytes(row.size_delta)}")
        lines.append(f"Keep size   : {_fmt_bytes(row.keep_size)}")
    lines.extend(
        [
            f"Duplicates  : {row.duplicate_count}",
            f"Reclaimable : {_fmt_bytes(row.reclaimable_bytes)}",
        ]
    )
    return lines


def _name_color(row: DuplicateListRow) -> int:
    # InteractiveList reserves color pair 9+ for custom usage.
    if row.is_keep:
        return 9  # green
    return 10 if row.size_delta >= 0 else 12


def _size_extractor(row: DuplicateListRow) -> int:
    return row.size


SORTERS: Dict[str, Callable[[DuplicateListRow], object]] = {
    "space": lambda row: row.reclaimable_bytes,
    "duplicates": lambda row: row.duplicate_count,
    "path": lambda row: str(row.path).lower(),
    "method": lambda row: row.method.lower(),
    "size": lambda row: row.size,
}

SORT_KEYS_MAPPING: Dict[int, str] = {
    ord("1"): "space",
    ord("2"): "duplicates",
    ord("3"): "method",
    ord("4"): "path",
    ord("5"): "size",
}


def _refresh_items(list_view: InteractiveList, manager: DuplicateListManager, reset_selection: bool = False) -> None:
    list_view.state.items = manager.visible_rows()
    list_view._update_visible_items(reset_selection=reset_selection)


def launch_report_viewer(report_paths: Sequence[Path]) -> None:
    groups: List[DuplicateGroup] = []
    for rp in report_paths:
        groups.extend(load_report_groups(rp))
    manager = DuplicateListManager(groups)

    def handler(key: int, row: DuplicateListRow) -> Tuple[bool, bool]:
        handled = False
        if key in (10, 13):  # Enter
            handled = True
            manager.toggle(row.group_id)
            _refresh_items(list_view, manager, reset_selection=False)
        elif key == 27:  # Escape collapses current group
            handled = True
            manager.collapse(row.group_id)
            _refresh_items(list_view, manager, reset_selection=False)
        return handled, handled

    list_view = InteractiveList(
        items=manager.visible_rows(),
        sorters=SORTERS,
        formatter=_formatter,
        filter_func=_filter,
        initial_sort="space",
        header="Duplicate Groups",
        sort_keys_mapping=SORT_KEYS_MAPPING,
        footer_lines=[
            "Enter: expand/collapse group | Esc: collapse | f/x: filter/exclude | Ctrl+Q: quit",
            "Sort keys: 1=space 2=dups 3=method 4=path 5=size",
        ],
        detail_formatter=_detail,
        size_extractor=_size_extractor,
        name_color_getter=_name_color,
        custom_action_handler=handler,
        dirs_first=False,
    )

    # Attach for handler to access
    _refresh_items(list_view, manager, reset_selection=True)
    list_view.run()


def render_reports_to_text(report_paths: Sequence[Path], *, color: bool = True, width: Optional[int] = None) -> str:
    width = width or _term_width()
    lines: List[str] = []
    total_groups = 0
    total_losers = 0
    total_space = 0

    for rp in report_paths:
        rp = Path(rp)
        groups = load_report_groups(rp)
        manager = DuplicateListManager(groups)
        manager.expand_all()
        rows = manager.visible_rows()

        lines.append(f"Report: {rp}")
        rendered_rows = render_items_to_text(rows, _formatter, sort_field="", width=width, show_date=True, show_time=True)
        for row, rendered in zip(rows, rendered_rows):
            line = rendered
            if color:
                if row.is_keep:
                    line = f"{ANSI_KEEP}{line}{ANSI_RESET}"
                else:
                    line = f"{ANSI_LOSE}{line}{ANSI_RESET}"
            lines.append(line)

        group_count = len(groups)
        loser_count = sum(g.duplicate_count for g in groups)
        space_bytes = sum(g.reclaimable_bytes for g in groups)

        total_groups += group_count
        total_losers += loser_count
        total_space += space_bytes

        summary_header = f"{ANSI_METHOD if color else ''}Summary{ANSI_RESET if color else ''}:"
        stats_color = ANSI_STATS if color else ""
        reset = ANSI_RESET if color else ""
        lines.extend(
            [
                "",
                summary_header,
                f"  groups : {group_count}",
                f"  losers : {loser_count}",
                f"  reclaim: {stats_color}{_fmt_bytes(space_bytes)}{reset}",
                "",
            ]
        )

    overall_header = f"{ANSI_METHOD if color else ''}Overall totals{ANSI_RESET if color else ''}:"
    stats_color = ANSI_STATS if color else ""
    reset = ANSI_RESET if color else ""
    lines.extend(
        [
            overall_header,
            f"  groups : {total_groups}",
            f"  losers : {total_losers}",
            f"  reclaim: {stats_color}{_fmt_bytes(total_space)}{reset}",
        ]
    )

    return "\n".join(lines)


def load_groups_from_reports(paths: Sequence[Path]) -> List[DuplicateGroup]:
    groups: List[DuplicateGroup] = []
    for rp in paths:
        groups.extend(load_report_groups(Path(rp)))
    return groups
