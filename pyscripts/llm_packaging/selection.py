"""Metadata-first selection inventory shared by the packaging TUI and preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Dict, Optional, Tuple

from zip_for_llms import Exclusion, _relpath


@dataclass(frozen=True)
class SelectionEntry:
    relative_path: str
    is_directory: bool
    selected: bool
    size_bytes: Optional[int]
    reason: Optional[str] = None
    error: Optional[str] = None
    text_status: str = "pending"


@dataclass(frozen=True)
class SelectionSnapshot:
    generation: int
    entries: Tuple[SelectionEntry, ...]
    selected_files: int
    selected_directories: int
    selected_bytes: int
    excluded_files: int
    pruned_directories: int
    errors: int
    complete: bool

    def by_path(self) -> Dict[str, SelectionEntry]:
        return {entry.relative_path: entry for entry in self.entries}


class Inventory:
    """Cache filesystem metadata while re-evaluating policy without reading file bodies."""

    def __init__(self, source: Path):
        self.source = source.resolve()
        self._files: Dict[str, tuple[int, Optional[str]]] = {}
        self._directories: set[str] = set()
        self._children: Dict[str, tuple[tuple[str, bool, int, Optional[str], bool], ...]] = {}
        self._scan_errors: Dict[str, str] = {}
        self._pruned: set[str] = set()
        self._generation = 0

    def snapshot(self, exclusion: Exclusion, cancel_event: Optional[Event] = None) -> SelectionSnapshot:
        self._scan(exclusion, cancel_event)
        entries = []
        selected_bytes = selected_files = excluded_files = errors = 0
        selected_dirs = 0

        for rel in sorted(self._directories, key=lambda value: (value.casefold(), value)):
            if self._under_pruned(rel):
                continue
            if rel in self._pruned:
                entries.append(SelectionEntry(rel, True, False, None, "excluded directory"))
            else:
                selected_dirs += 1
                entries.append(SelectionEntry(rel, True, True, 0))

        for rel, (size, err) in sorted(self._files.items(), key=lambda item: (item[0].casefold(), item[0])):
            if self._under_pruned(rel):
                continue
            excluded = exclusion.file_is_excluded(rel)
            if excluded:
                excluded_files += 1
            else:
                selected_files += 1
                if not err:
                    selected_bytes += size
                else:
                    errors += 1
            entries.append(SelectionEntry(
                rel, False, not excluded, size, exclusion.exclusion_reason(rel) if excluded else None,
                err, "pending",
            ))

        for rel, error in self._scan_errors.items():
            if not self._under_pruned(rel):
                errors += 1
                entries.append(SelectionEntry(rel, True, False, None, "scan error", error))

        self._generation += 1
        entries.sort(key=lambda entry: (entry.relative_path.casefold(), entry.relative_path, not entry.is_directory))
        return SelectionSnapshot(
            self._generation, tuple(entries), selected_files, selected_dirs, selected_bytes,
            excluded_files, len(self._pruned), errors, errors == 0 and not (cancel_event and cancel_event.is_set()),
        )

    def _under_pruned(self, relative_path: str) -> bool:
        parts = relative_path.split("/")
        return any("/".join(parts[:index]) in self._pruned for index in range(1, len(parts)))

    def _scan(self, exclusion: Exclusion, cancel_event: Optional[Event] = None) -> None:
        self._pruned.clear()
        stack = [self.source]
        while stack and not (cancel_event and cancel_event.is_set()):
            folder = stack.pop()
            parent_rel = _relpath(folder, self.source)
            if parent_rel in self._children:
                children = self._children[parent_rel]
            else:
                discovered = []
                try:
                    paths = sorted(folder.iterdir(), key=lambda p: (p.name.casefold(), p.name))
                except OSError as exc:
                    self._scan_errors[parent_rel] = str(exc)
                    self._children[parent_rel] = ()
                    continue
                for child in paths:
                    rel = _relpath(child, self.source)
                    try:
                        is_dir = child.is_dir()
                        is_symlink = child.is_symlink()
                        size = 0 if is_dir else child.stat().st_size
                        error = None
                    except OSError as exc:
                        is_dir, is_symlink, size, error = False, False, 0, str(exc)
                    discovered.append((child.name, is_dir, size, error, is_symlink))
                    if is_dir:
                        self._directories.add(rel)
                    else:
                        self._files[rel] = (size, error)
                children = tuple(discovered)
                self._children[parent_rel] = children
            dirs = []
            for name, is_dir, _, error, is_symlink in children:
                if cancel_event and cancel_event.is_set():
                    break
                rel = f"{parent_rel}/{name}" if parent_rel != "." else name
                if is_dir:
                    if exclusion.dir_is_excluded(rel):
                        self._pruned.add(rel)
                    elif is_symlink:
                        continue
                    else:
                        dirs.append(folder / name)
                else:
                    if error:
                        self._scan_errors[rel] = error
            stack.extend(reversed(dirs))

