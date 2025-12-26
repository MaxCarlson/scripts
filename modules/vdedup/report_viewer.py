from __future__ import annotations

import os
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from termdash.interactive_list import (
    DETAIL_FOOTER_DEFAULT,
    DetailEntry,
    DetailViewData,
    InteractiveList,
    render_items_to_text,
)

from .report_models import DuplicateGroup, FileStats, load_report_groups
from cross_platform.system_utils import SystemUtils

LOGGER = logging.getLogger(__name__)

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
        f"{'DELTA':>{delta_w}}"
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


def _describe_file(stats: FileStats) -> List[str]:
    lines = [
        f"Path : {stats.path}",
        f"Size : {_fmt_bytes(stats.size)} ({stats.size:,} bytes)",
    ]
    if stats.duration is not None:
        lines.append(f"Duration : {stats.duration:.2f}s")
    if stats.width and stats.height:
        lines.append(f"Resolution : {stats.width}x{stats.height}")
    if stats.video_bitrate is not None:
        lines.append(f"Video bitrate : {stats.video_bitrate:,} bps")
    if stats.overall_bitrate is not None:
        lines.append(f"Overall bitrate : {stats.overall_bitrate:,} bps")
    return lines


def _candidate_open_commands(path: Path, sys_utils: SystemUtils) -> List[List[str]]:
    target = str(path)
    if sys_utils.is_darwin():
        return [["open", target], ["xdg-open", target]]
    if sys_utils.is_termux():
        return [["termux-open", target], ["xdg-open", target]]
    if sys_utils.is_wsl2():
        return [["wslview", target], ["xdg-open", target]]
    # Linux/BSD fallback
    return [["xdg-open", target]]


def _open_media(path: Path) -> bool:
    """
    Launch the given path in the platform's default handler (video player, file explorer).
    Returns True on success, False if no opener succeeded.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        LOGGER.warning("Cannot open %s (file missing)", resolved)
        return False

    sys_utils = SystemUtils()

    if sys_utils.is_windows():
        try:
            os.startfile(str(resolved))  # type: ignore[attr-defined]
            return True
        except Exception as exc:  # pragma: no cover - OS specific
            LOGGER.error("Failed to open %s via ShellExecute: %s", resolved, exc)
            return False

    for cmd in _candidate_open_commands(resolved, sys_utils):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            continue
        except Exception as exc:
            LOGGER.error("Failed to open %s via %s: %s", resolved, cmd[0], exc)
            return False

    LOGGER.error("No opener available for %s", resolved)
    return False


def _build_detail_view_for_group(group: DuplicateGroup) -> DetailViewData:
    suffix_map = _unique_suffixes([group.keep.path] + [loser.path for loser in group.losers])

    entries: List[DetailEntry] = []
    summary_body = [
        f"Method     : {group.method}",
        f"Duplicates : {group.duplicate_count}",
        f"Reclaim    : {_fmt_bytes(group.reclaimable_bytes)}",
    ]
    entries.append(DetailEntry(summary=f"Group {group.group_id}", body=summary_body, focusable=False, expanded=True))

    keep_display = DuplicateListManager._display_name_for(group.keep.path, suffix_map.get(group.keep.path, ""))
    entries.append(
        DetailEntry(
            summary=f"K {keep_display}",
            body=_describe_file(group.keep),
            focusable=True,
            expanded=True,
        )
    )

    for loser in group.losers:
        display = DuplicateListManager._display_name_for(loser.path, suffix_map.get(loser.path, ""))
        body = _describe_file(loser)
        body.append(f"Delta vs keep : {_fmt_signed_bytes(loser.size - group.keep.size)}")
        entries.append(
            DetailEntry(
                summary=f"L {display}",
                body=body,
                focusable=True,
                expanded=False,
            )
        )

    title = f"Group {group.group_id} ({group.method})"
    return DetailViewData(title=title, entries=entries, footer=DETAIL_FOOTER_DEFAULT)


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

    @staticmethod
    def _display_name_for(path: Path, suffix: str) -> str:
        base = path.name
        suffix_norm = (suffix or "").replace("\\", "/")
        if suffix_norm.endswith(base):
            suffix_norm = suffix_norm[: -len(base)].rstrip("/ ")
        if suffix_norm:
            return f"{base} | {suffix_norm}"
        return base

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
            # Determine minimal suffixes per path for display
            paths = [keep.path] + [loser.path for loser in group.losers]
            suffix_map = _unique_suffixes(paths)
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
                display_name=self._display_name_for(keep.path, suffix_map.get(keep.path, "")),
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
                            display_name=self._display_name_for(loser.path, suffix_map.get(loser.path, "")),
                        )
                    )
        return rows

    @property
    def groups(self) -> List[DuplicateGroup]:
        return self._groups

    def reorder(self, key_func: Callable[[DuplicateGroup], object], descending: bool) -> None:
        self._groups.sort(key=key_func, reverse=descending)

    def get_group(self, group_id: str) -> Optional[DuplicateGroup]:
        for group in self._groups:
            if group.group_id == group_id:
                return group
        return None


def _formatter(row: DuplicateListRow, sort_field: str, width: int, *_args) -> str:
    name_width, dup_w, reclaim_w, size_w, delta_w = _compute_layout(width)
    indent = "  " * row.depth
    role = "K" if row.is_keep else "L"
    display = row.display_name or row.path.name
    name_cell = f"{indent}{role} {display}".rstrip()
    if len(name_cell) > name_width:
        if name_width > 3:
            name_cell = name_cell[: name_width - 3] + "..."
        else:
            name_cell = name_cell[:name_width]
    else:
        name_cell = name_cell.ljust(name_width)

    dup_cell = f"{row.duplicate_count:>{dup_w}}" if row.is_keep else " " * dup_w
    reclaim_cell = f"{_fmt_bytes(row.reclaimable_bytes):>{reclaim_w}}" if row.is_keep else " " * reclaim_w
    size_cell = f"{_fmt_bytes(row.size):>{size_w}}"
    delta_cell = " " * delta_w if row.is_keep else f"{_fmt_signed_bytes(row.size_delta):>{delta_w}}"

    return (
        f"{name_cell}"
        f"{'':<{COLUMN_SPACING}}"
        f"{dup_cell}"
        f"{'':<{COLUMN_SPACING}}"
        f"{reclaim_cell}"
        f"{'':<{COLUMN_SPACING}}"
        f"{size_cell}"
        f"{'':<{COLUMN_SPACING}}"
        f"{delta_cell}"
    )


def _filter(row: DuplicateListRow, pattern: str) -> bool:
    pattern_lower = pattern.lower()
    return pattern_lower in str(row.path).lower()



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

GROUP_SORTERS: Dict[str, Callable[[DuplicateGroup], object]] = {
    "space": lambda group: group.reclaimable_bytes,
    "duplicates": lambda group: group.duplicate_count,
    "path": lambda group: str(group.keep.path).lower(),
    "method": lambda group: group.method.lower(),
    "size": lambda group: group.keep.size,
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
    if manager.groups:
        manager.reorder(GROUP_SORTERS["space"], True)

    def detail_formatter(row: DuplicateListRow) -> DetailViewData:
        group = manager.get_group(row.group_id)
        if not group:
            return DetailViewData(
                title=f"Group {row.group_id}",
                entries=[
                    DetailEntry(summary="No group data available", body=[], focusable=False, expanded=True)
                ],
                footer=DETAIL_FOOTER_DEFAULT,
            )
        return _build_detail_view_for_group(group)

    header_line = _column_header(_term_width())
    list_view = InteractiveList(
        items=manager.visible_rows(),
        sorters=SORTERS,
        formatter=_formatter,
        filter_func=_filter,
        initial_sort="space",
        header="Duplicate Groups",
        sort_keys_mapping=SORT_KEYS_MAPPING,
        footer_lines=[
            "Enter: toggle | i: detail | E: expand all | C: collapse all | f/x: filter/exclude | o: open file",
            "Sort: 1=space 2=dups 3=method 4=path 5=size | Ctrl+Q: quit",
        ],
        detail_formatter=detail_formatter,
        size_extractor=_size_extractor,
        name_color_getter=_name_color,
        dirs_first=False,
        columns_line=header_line,
    )

    def handler(key: int, row: DuplicateListRow) -> Tuple[bool, bool]:
        handled = False
        if key in (10, 13):  # Enter toggles expansion
            handled = True
            manager.toggle(row.group_id)
            if list_view.state.detail_view:
                list_view._exit_detail_view()
            _refresh_items(list_view, manager, reset_selection=False)
        elif key == 27:  # Escape collapses current group
            handled = True
            manager.collapse(row.group_id)
            if list_view.state.detail_view:
                list_view._exit_detail_view()
            _refresh_items(list_view, manager, reset_selection=False)
        elif key in (ord("E"), ord("e")):
            handled = True
            manager.expand_all()
            if list_view.state.detail_view:
                list_view._exit_detail_view()
            _refresh_items(list_view, manager, reset_selection=False)
        elif key in (ord("C"), ord("c")):
            handled = True
            manager.collapse_all()
            if list_view.state.detail_view:
                list_view._exit_detail_view()
            _refresh_items(list_view, manager, reset_selection=True)
        elif key in (ord("O"), ord("o")):
            handled = True
            _open_media(row.path)
        return handled, handled

    list_view.custom_action_handler = handler

    def handle_sort_change(field: str, descending: bool) -> None:
        key_func = GROUP_SORTERS.get(field)
        if not key_func:
            return
        manager.reorder(key_func, descending)
        if list_view.state.detail_view:
            list_view._exit_detail_view()
        _refresh_items(list_view, manager, reset_selection=True)

    list_view.sort_change_handler = handle_sort_change

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
        if manager.groups:
            manager.reorder(GROUP_SORTERS["space"], True)
        manager.expand_all()
        rows = manager.visible_rows()

        lines.append(f"Report: {rp}")
        lines.append(_column_header(width))
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
