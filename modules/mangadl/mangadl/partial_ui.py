from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

try:
    import curses
except Exception:  # pragma: no cover
    curses = None  # type: ignore[assignment]

from termdash.interactive_list import InteractiveList

from .partial_reconcile import state_url_candidates
from .partial_safety import PARTIAL_CONTROL_NAMES, _gallery_processes_for_path, _process_commands
from .ui import human_bytes


@dataclass(slots=True)
class PartialEntry:
    path: Path
    owner: Path
    name: str
    is_dir: bool
    size: int
    files: int
    created: datetime
    modified: datetime
    accessed: datetime
    depth: int
    parent_path: Path | None
    url: str | None
    backend: str | None
    archive: str | None
    ownership: str
    worker_pid: int | None
    active_pids: tuple[int, ...]
    expanded: bool = False


SORTERS: dict[str, Callable[[PartialEntry], object]] = {
    "created": lambda entry: entry.created.timestamp(),
    "modified": lambda entry: entry.modified.timestamp(),
    "accessed": lambda entry: entry.accessed.timestamp(),
    "size": lambda entry: entry.size,
    "name": lambda entry: entry.name.casefold(),
}
SORT_KEYS = {ord("c"): "created", ord("m"): "modified", ord("a"): "accessed", ord("s"): "size", ord("n"): "name"}


def _partial_sizes(partial_root: Path) -> dict[Path, tuple[int, int]]:
    totals: dict[Path, tuple[int, int]] = {}
    for owner in partial_root.iterdir():
        if not owner.is_dir() or owner.is_symlink():
            continue
        for root, directories, names in os.walk(owner, topdown=False, followlinks=False):
            current = Path(root)
            files = size = 0
            for name in names:
                if name in PARTIAL_CONTROL_NAMES:
                    continue
                try:
                    size += (current / name).lstat().st_size
                    files += 1
                except OSError:
                    continue
            for name in directories:
                child_files, child_size = totals.get(current / name, (0, 0))
                files += child_files
                size += child_size
            totals[current] = (files, size)
    return totals


def _owner_metadata(owner: Path, state_matches: dict[str, tuple[str, ...]]) -> dict[str, object]:
    path = owner / ".mangadl-partial.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {"ownership": "invalid metadata"}
        return {
            "url": str(payload.get("url") or "") or None,
            "backend": str(payload.get("backend") or "") or None,
            "archive": str(payload.get("archive") or "") or None,
            "worker_pid": int(payload["worker_pid"]) if payload.get("worker_pid") else None,
            "ownership": "tracked manifest",
        }
    candidates = state_matches.get(owner.name, ())
    if len(candidates) == 1:
        return {"url": candidates[0], "ownership": "legacy; URL recovered from state"}
    if candidates:
        return {"ownership": f"legacy; {len(candidates)} ambiguous URLs"}
    return {"ownership": "legacy; URL unknown"}


def build_partial_inventory(destination: Path, *, state_databases: tuple[Path, ...] = ()) -> tuple[Path, list[PartialEntry], dict[Path, tuple[int, int]]]:
    partial_root = destination.expanduser().resolve() / "_partial"
    if not partial_root.is_dir():
        raise ValueError(f"partial root does not exist: {partial_root}")
    state_matches = state_url_candidates(destination, state_databases)
    sizes = _partial_sizes(partial_root)
    process_commands = _process_commands()
    entries: list[PartialEntry] = []
    for owner in sorted(partial_root.iterdir(), key=lambda path: path.name.casefold()):
        if not owner.is_dir() or owner.is_symlink():
            continue
        try:
            stat = owner.stat()
        except OSError:
            continue
        metadata = _owner_metadata(owner, state_matches)
        files, size = sizes.get(owner, (0, 0))
        entries.append(PartialEntry(
            owner, owner, owner.name, True, size, files,
            datetime.fromtimestamp(stat.st_ctime), datetime.fromtimestamp(stat.st_mtime), datetime.fromtimestamp(stat.st_atime),
            0, None, metadata.get("url"), metadata.get("backend"), metadata.get("archive"), str(metadata["ownership"]),
            metadata.get("worker_pid"), _gallery_processes_for_path(owner, process_commands or ()),
        ))
    return partial_root, entries, sizes


class PartialTree:
    def __init__(self, entries: list[PartialEntry], sizes: dict[Path, tuple[int, int]]) -> None:
        self.entries, self.sizes, self.expanded = entries, sizes, set()

    def _load_children(self, entry: PartialEntry) -> None:
        if any(candidate.parent_path == entry.path for candidate in self.entries):
            return
        try:
            paths = tuple(entry.path.iterdir())
        except OSError:
            return
        for path in paths:
            if path.name in PARTIAL_CONTROL_NAMES:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            is_dir = path.is_dir() and not path.is_symlink()
            files, size = self.sizes.get(path, (1, stat.st_size))
            self.entries.append(PartialEntry(
                path, entry.owner, path.name, is_dir, size if is_dir else stat.st_size, files if is_dir else 1,
                datetime.fromtimestamp(stat.st_ctime), datetime.fromtimestamp(stat.st_mtime), datetime.fromtimestamp(stat.st_atime),
                entry.depth + 1, entry.path, entry.url, entry.backend, entry.archive, entry.ownership, entry.worker_pid, entry.active_pids,
            ))

    def toggle(self, entry: PartialEntry) -> None:
        if not entry.is_dir:
            return
        if entry.path in self.expanded:
            self.expanded.remove(entry.path)
            entry.expanded = False
        else:
            self._load_children(entry)
            self.expanded.add(entry.path)
            entry.expanded = True

    def visible(self, sort_field: str, descending: bool, dirs_first: bool = True) -> list[PartialEntry]:
        result: list[PartialEntry] = []
        def add(entry: PartialEntry) -> None:
            result.append(entry)
            if entry.path not in self.expanded:
                return
            children = [item for item in self.entries if item.parent_path == entry.path]
            children.sort(key=SORTERS[sort_field], reverse=descending)
            if dirs_first:
                children.sort(key=lambda item: not item.is_dir)
            for child in children:
                add(child)
        roots = [item for item in self.entries if item.depth == 0]
        roots.sort(key=SORTERS[sort_field], reverse=descending)
        for root in roots:
            add(root)
        return result


def format_partial_entry(entry: PartialEntry, sort_field: str, width: int, show_date: bool = True, show_time: bool = True, scroll_offset: int = 0) -> str:
    timestamp = getattr(entry, sort_field) if sort_field in {"created", "modified", "accessed"} else entry.modified
    date = timestamp.strftime("%Y-%m-%d %H:%M:%S") if show_date and show_time else timestamp.strftime("%Y-%m-%d") if show_date else ""
    label = ("  " * entry.depth) + f"{'▼' if entry.expanded else '▶' if entry.is_dir else ' '} {entry.name}"
    if entry.depth == 0:
        label += f"  [{entry.ownership}]"
        if entry.active_pids:
            label += f"  [ACTIVE PIDs {','.join(map(str, entry.active_pids))}]"
        if entry.url:
            label += f"  {entry.url}"
    if scroll_offset:
        label = label[scroll_offset:]
    suffix = f"{human_bytes(entry.size)} ({entry.files:,})"
    available = max(1, width - len(date) - len(suffix) - 4)
    if len(label) > available:
        label = label[: max(1, available - 1)] + "…"
    return f"{date:<19}  {label:<{available}}  {suffix}" if date else f"{label:<{available}}  {suffix}"


def partial_details(entry: PartialEntry) -> list[str]:
    return [
        f"Partial owner: {entry.owner.name}", f"Selected path: {entry.path}", f"Type: {'Directory' if entry.is_dir else 'File'}",
        f"Size: {human_bytes(entry.size)} ({entry.size:,} bytes; {entry.files:,} files)", f"Created: {entry.created:%Y-%m-%d %H:%M:%S}",
        f"Modified: {entry.modified:%Y-%m-%d %H:%M:%S}", f"Accessed: {entry.accessed:%Y-%m-%d %H:%M:%S}",
        f"Ownership: {entry.ownership}", f"URL: {entry.url or 'unknown'}", f"Backend: {entry.backend or 'unknown'}",
        f"Archive: {entry.archive or 'not recorded'}", f"Worker PID: {entry.worker_pid or 'none recorded'}",
        f"Active gallery-dl PIDs: {', '.join(map(str, entry.active_pids)) or 'none detected'}", "",
        "Only top-level partial owners can be selected for cleanup.",
    ]


class _SelectionComplete(Exception):
    def __init__(self, entries: list[PartialEntry]) -> None:
        self.entries = entries


class PartialInteractiveList(InteractiveList):
    def _toggle_selection(self, item: PartialEntry) -> None:
        if item.depth == 0 and item.is_dir:
            super()._toggle_selection(item)


def select_partial_owners(destination: Path, *, state_databases: tuple[Path, ...] = ()) -> list[Path]:
    if curses is None:
        raise RuntimeError("interactive partial cleanup requires curses/windows-curses")
    partial_root, entries, sizes = build_partial_inventory(destination, state_databases=state_databases)
    if not entries:
        raise ValueError(f"partial root contains no owner folders: {partial_root}")
    tree = PartialTree(entries, sizes)
    view: PartialInteractiveList
    def action(key: int, item: PartialEntry, state) -> tuple[bool, bool]:
        if key in (curses.KEY_ENTER, 10, 13):
            tree.toggle(item)
            state.items = tree.visible(state.sort_field, state.descending, state.dirs_first)
            return True, True
        if key in SORT_KEYS:
            field = SORT_KEYS[key]
            state.descending = not state.descending if state.sort_field == field else True
            state.sort_field = field
            state.items = tree.visible(field, state.descending, state.dirs_first)
            return True, True
        if key == ord("D"):
            selected = [entry for entry in view.get_selected_items() if entry.depth == 0]
            if selected:
                raise _SelectionComplete(selected)
            return True, False
        return False, False
    view = PartialInteractiveList(
        items=tree.visible("size", True), sorters=SORTERS, formatter=format_partial_entry,
        filter_func=lambda entry, pattern: pattern.casefold() in entry.name.casefold() or pattern.casefold() in (entry.url or "").casefold(),
        initial_sort="size", initial_order="desc", header=f"mangadl partial cleanup | {partial_root}", sort_keys_mapping=SORT_KEYS,
        footer_lines=["Space select owner | Enter expand/collapse | i details | D continue | Ctrl+Q cancel", "Sort c created / m modified / a accessed / s size / n name | f filter | arrows/jk move"],
        detail_formatter=partial_details, size_extractor=lambda entry: entry.size, enable_color_gradient=True,
        key_handler=action, dirs_first=True, multi_select=True, item_key_func=lambda entry: str(entry.path),
    )
    try:
        view.run()
    except _SelectionComplete as selected:
        return [entry.path for entry in selected.entries]
    except SystemExit as exc:
        if exc.code == 2:
            raise RuntimeError("interactive partial cleanup requires a usable terminal; provide --target for CLI mode") from exc
        raise
    return []
