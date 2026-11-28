"""Packaging-specific, headless-testable controller and optional curses frontend."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from typing import Dict, List, Optional

from zip_for_llms import (
    DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES,
    PRESETS, Exclusion, text_file_mode, zip_folder,
)

from .selection import Inventory, SelectionSnapshot


def format_size(size: int) -> str:
    value = float(size)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024


@dataclass
class TuiState:
    source: Path
    output_base: Path
    mode: str = "zip"
    preset: Optional[str] = None
    dry_run: bool = False
    exclude_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_DIRS))
    exclude_exts: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_EXTS))
    exclude_files: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_FILES))
    remove_patterns: List[str] = field(default_factory=list)
    keep_patterns: List[str] = field(default_factory=list)
    flatten: bool = False
    name_by_path: bool = False
    max_size: Optional[int] = None
    preferences: List[str] = field(default_factory=list)
    async_scan: bool = False
    screen: str = "settings"
    view_mode: int = 0
    depth: int = 2
    selected_index: int = 0
    scroll: int = 0
    sort_by_size: bool = False
    group_mode: int = 0
    group_index: int = 0
    member_index: int = 0
    rule_index: int = 0
    expanded: set[str] = field(default_factory=set)
    undo_stack: List[tuple[set[str], set[str], set[str], List[str], List[str]]] = field(default_factory=list)
    redo_stack: List[tuple[set[str], set[str], set[str], List[str], List[str]]] = field(default_factory=list)
    message: str = ""
    overwrite_confirmed: bool = False
    _inventory: Inventory = field(init=False, repr=False)
    snapshot: SelectionSnapshot = field(init=False)
    _executor: Optional[ThreadPoolExecutor] = field(init=False, default=None, repr=False)
    _future: Optional[Future] = field(init=False, default=None, repr=False)
    _cancel_event: Optional[Event] = field(init=False, default=None, repr=False)
    _request_id: int = field(init=False, default=0, repr=False)
    scan_pending: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._inventory = Inventory(self.source)
        if self.async_scan:
            self.snapshot = SelectionSnapshot(0, (), 0, 0, 0, 0, 0, 0, False)
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-package-scan")
        self.refresh()

    def exclusion(self) -> Exclusion:
        return Exclusion(self.exclude_dirs, self.exclude_exts, self.exclude_files,
                         self.remove_patterns, self.keep_patterns)

    def _save_rules(self) -> None:
        self.undo_stack.append((set(self.exclude_dirs), set(self.exclude_exts), set(self.exclude_files),
                                list(self.remove_patterns), list(self.keep_patterns)))
        self.redo_stack.clear()

    def active_rules(self):
        defaults = {"directory": DEFAULT_EXCLUDE_DIRS, "extension": DEFAULT_EXCLUDE_EXTS,
                    "filename": DEFAULT_EXCLUDE_FILES}
        current = {"directory": self.exclude_dirs, "extension": self.exclude_exts,
                   "filename": self.exclude_files, "remove": set(self.remove_patterns),
                   "keep": set(self.keep_patterns)}
        preset_values = PRESETS.get(self.preset, {}) if self.preset else {}
        rules = []
        for kind, values in current.items():
            for value in sorted(values, key=lambda item: (item.casefold(), item)):
                origins = []
                if kind in defaults and value in defaults[kind]:
                    origins.append("default")
                preset_key = {"directory": "dirs", "extension": "exts", "filename": "files", "remove": "patterns"}.get(kind)
                if preset_key and value in preset_values.get(preset_key, set()):
                    origins.append("preset")
                rules.append((kind, value, "+".join(origins) or "user"))
        return rules

    def add_rule(self, kind: str, value: str) -> None:
        if kind not in {"directory", "extension", "filename", "remove", "keep"} or not value:
            self.message = "Rule type or value is invalid"
            return
        self._save_rules()
        target = {"directory": self.exclude_dirs, "extension": self.exclude_exts,
                  "filename": self.exclude_files, "remove": self.remove_patterns,
                  "keep": self.keep_patterns}[kind]
        if isinstance(target, set):
            target.add(value)
        elif value not in target:
            target.append(value)
        self.refresh()
        self.message = f"Added {kind} rule: {value}"

    def remove_rule(self, kind: str, value: str) -> None:
        self._save_rules()
        target = {"directory": self.exclude_dirs, "extension": self.exclude_exts,
                  "filename": self.exclude_files, "remove": self.remove_patterns,
                  "keep": self.keep_patterns}[kind]
        if isinstance(target, set):
            target.discard(value)
        else:
            target[:] = [item for item in target if item != value]
        self.refresh()
        self.message = f"Removed {kind} rule: {value}"

    def refresh(self) -> None:
        if self.async_scan and self._executor:
            self._request_id += 1
            if self._cancel_event:
                self._cancel_event.set()
            if self._future:
                self._future.cancel()
            self._cancel_event = Event()
            exclusion = Exclusion(set(self.exclude_dirs), set(self.exclude_exts), set(self.exclude_files),
                                  list(self.remove_patterns), list(self.keep_patterns))
            self._future = self._executor.submit(self._inventory.snapshot, exclusion, self._cancel_event)
            self.scan_pending = True
            return
        self.snapshot = self._inventory.snapshot(self.exclusion())
        self.selected_index = min(self.selected_index, max(0, len(self.visible_entries()) - 1))
        self.group_index = min(self.group_index, max(0, len(self.groups()) - 1))
        self.member_index = 0

    def poll_worker(self) -> None:
        if not self._future or not self._future.done():
            return
        future = self._future
        self._future = None
        try:
            snapshot = future.result()
        except Exception as exc:
            self.message = f"Selection scan failed: {exc}"
            self.scan_pending = False
            return
        if not future.cancelled():
            self.snapshot = snapshot
            self.selected_index = min(self.selected_index, max(0, len(self.visible_entries()) - 1))
            self.group_index = min(self.group_index, max(0, len(self.groups()) - 1))
            self.member_index = 0
            self.scan_pending = False

    def close(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self.group_index = min(self.group_index, max(0, len(self.groups()) - 1))
        self.member_index = 0

    def visible_entries(self):
        entries = self.snapshot.entries
        if self.view_mode == 0:
            entries = tuple(e for e in entries if e.selected)
        elif self.view_mode == 2:
            entries = tuple(e for e in entries if not e.selected)
        result = []
        for entry in entries:
            depth = len(Path(entry.relative_path).parts) - 1
            if depth > self.depth and not any(
                entry.relative_path.startswith(parent + "/") for parent in self.expanded
            ):
                continue
            if any(entry.relative_path.startswith(parent + "/") and parent not in self.expanded
                   for parent in self._directory_parents(entry.relative_path)):
                continue
            result.append(entry)
        return result

    @staticmethod
    def _directory_parents(relative_path: str):
        parts = relative_path.split("/")[:-1]
        return ("/".join(parts[:index]) for index in range(1, len(parts) + 1))

    def groups(self):
        group_names = ["directory", "extension", "filename", "largest"]
        selected_kind = group_names[self.group_mode]
        entries = [e for e in self.snapshot.entries if e.selected]
        grouped: Dict[tuple[str, str], dict] = {}
        for entry in entries:
            if entry.is_directory:
                if selected_kind != "directory":
                    continue
                key = ("directory", Path(entry.relative_path).name)
                item = grouped.setdefault(key, {"count": 0, "bytes": 0, "paths": []})
                item["count"] += 1
                item["paths"].append(entry.relative_path)
            else:
                suffix = Path(entry.relative_path).suffix.lower() or "(no extension)"
                per_file = (("extension", suffix), ("filename", Path(entry.relative_path).name))
                if selected_kind == "largest":
                    per_file = (("largest", entry.relative_path),)
                else:
                    per_file = tuple((kind, value) for kind, value in per_file if kind == selected_kind)
                for kind, value in per_file:
                    item = grouped.setdefault((kind, value), {"count": 0, "bytes": 0, "paths": []})
                    item["count"] += 1
                    item["bytes"] += entry.size_bytes or 0
                    item["paths"].append(entry.relative_path)
        for (kind, value), item in grouped.items():
            if kind == "directory":
                matches = [path for path in item["paths"] if Path(path).name == value]
                topmost = [path for path in matches if not any(
                    path.startswith(parent + "/") for parent in matches if parent != path
                )]
                item["bytes"] = sum(
                    entry.size_bytes or 0 for entry in entries
                    if not entry.is_directory and any(entry.relative_path.startswith(path + "/") for path in topmost)
                )
        result = [{"kind": kind, "key": key, **value} for (kind, key), value in grouped.items()]
        result.sort(key=lambda g: (-(g["bytes"] if self.sort_by_size else g["count"]), g["kind"], g["key"].casefold(), g["key"]))
        return result

    def process_key(self, key: int) -> bool:
        """Apply one key; return False when the app should quit."""
        entries = self.visible_entries()
        current = entries[self.selected_index] if entries else None
        if self.screen == "tree":
            if key in (259, ord("k")):
                self.selected_index = max(0, self.selected_index - 1)
            elif key in (258, ord("j")):
                self.selected_index = min(max(0, len(entries) - 1), self.selected_index + 1)
            elif key in (ord("+"), ord("=")):
                self.depth += 1
            elif key == ord("-"):
                self.depth = max(0, self.depth - 1)
            elif key == ord("v"):
                self.view_mode = (self.view_mode + 1) % 3
                self.selected_index = 0
            elif key == ord("g"):
                self.screen, self.group_index = "groups", 0
            elif key == ord("f"):
                self.screen = "filters"
            elif key == ord("s"):
                self.screen = "settings"
            elif key == ord("r"):
                self._inventory = Inventory(self.source)
                self.refresh()
                self.message = "Filesystem refreshed"
            elif key == ord("x") and current:
                self._save_rules()
                if current.is_directory:
                    self.exclude_dirs.add(current.relative_path)
                else:
                    self.remove_patterns.append(current.relative_path)
                self.refresh()
                self.message = f"Excluded {current.relative_path}"
            elif key == ord("i") and current and not current.is_directory:
                self._save_rules()
                self.keep_patterns.append(Path(current.relative_path).name)
                self.refresh()
                self.message = f"Kept files named {Path(current.relative_path).name}"
            elif key in (10, 13):
                if current and current.is_directory:
                    if current.relative_path in self.expanded:
                        self.expanded.remove(current.relative_path)
                    else:
                        self.expanded.add(current.relative_path)
                else:
                    self.screen = "review"
            elif key == ord("q"):
                return False
        elif self.screen == "groups":
            groups = self.groups()
            if key in (259, ord("k")):
                self.group_index = max(0, self.group_index - 1)
            elif key in (258, ord("j")):
                self.group_index = min(max(0, len(groups) - 1), self.group_index + 1)
            elif key == ord("s"):
                self.sort_by_size = not self.sort_by_size
            elif key == 9:
                self.group_mode = (self.group_mode + 1) % 4
                self.group_index = 0
            elif key in (10, 13) and groups:
                self.screen, self.member_index = "group_detail", 0
            elif key == ord("x") and groups:
                group = groups[self.group_index]
                self._save_rules()
                if group["kind"] == "directory":
                    self.exclude_dirs.add(group["key"])
                elif group["kind"] == "extension" and not group["key"].startswith("("):
                    self.exclude_exts.add(group["key"])
                elif group["kind"] == "largest":
                    self.remove_patterns.append(group["key"])
                else:
                    self.exclude_files.add(group["key"])
                self.refresh()
            elif key in (27, ord("q")):
                self.screen = "tree"
        elif self.screen == "group_detail":
            groups = self.groups()
            members = groups[self.group_index]["paths"] if groups else []
            if key in (259, ord("k")):
                self.member_index = max(0, self.member_index - 1)
            elif key in (258, ord("j")):
                self.member_index = min(max(0, len(members) - 1), self.member_index + 1)
            elif key == ord("e") and members:
                self._save_rules()
                self.remove_patterns.append(members[self.member_index])
                self.refresh()
                self.message = f"Excluded exact path {members[self.member_index]}"
            elif key == ord("x") and groups:
                group = groups[self.group_index]
                self._save_rules()
                if group["kind"] == "directory":
                    self.exclude_dirs.add(group["key"])
                elif group["kind"] == "extension":
                    self.exclude_exts.add(group["key"])
                elif group["kind"] == "largest":
                    self.remove_patterns.append(group["key"])
                else:
                    self.exclude_files.add(group["key"])
                self.refresh()
                self.screen = "groups"
            elif key in (27, ord("q")):
                self.screen = "groups"
        elif self.screen == "filters":
            rules = self.active_rules()
            if key == 259:
                self.rule_index = max(0, self.rule_index - 1)
            elif key == 258:
                self.rule_index = min(max(0, len(rules) - 1), self.rule_index + 1)
            elif key in (ord("d"), 127, 8) and rules:
                kind, value, _ = rules[self.rule_index]
                self.remove_rule(kind, value)
                self.rule_index = min(self.rule_index, max(0, len(self.active_rules()) - 1))
            elif key in (ord("u"), 26) and self.undo_stack:
                self.redo_stack.append((set(self.exclude_dirs), set(self.exclude_exts), set(self.exclude_files),
                                        list(self.remove_patterns), list(self.keep_patterns)))
                self.exclude_dirs, self.exclude_exts, self.exclude_files, self.remove_patterns, self.keep_patterns = self.undo_stack.pop()
                self.refresh()
            elif key in (ord("y"), 25) and self.redo_stack:
                self.undo_stack.append((set(self.exclude_dirs), set(self.exclude_exts), set(self.exclude_files),
                                        list(self.remove_patterns), list(self.keep_patterns)))
                self.exclude_dirs, self.exclude_exts, self.exclude_files, self.remove_patterns, self.keep_patterns = self.redo_stack.pop()
                self.refresh()
            elif key in (27, ord("q")):
                self.screen = "tree"
        elif self.screen == "settings":
            if key == ord("m"):
                self.mode = {"zip": "text", "text": "both", "both": "zip"}[self.mode]
                self.overwrite_confirmed = False
            elif key == ord("d"):
                self.dry_run = not self.dry_run
            elif key == ord("f"):
                self.flatten = not self.flatten
            elif key == ord("n"):
                self.name_by_path = not self.name_by_path
            elif key in (10, 13):
                self.screen = "tree"
            elif key in (27, ord("q")):
                self.screen = "tree"
        elif self.screen == "review":
            if key in (ord("n"), 27):
                self.screen = "tree"
            elif key in (ord("y"), 10, 13):
                if self.dry_run:
                    self.message = "Dry-run: generation is disabled"
                elif self._outputs_exist() and not self.overwrite_confirmed:
                    self.overwrite_confirmed = True
                    self.message = "Output exists. Press Y again to overwrite."
                else:
                    if self.generate():
                        self.screen = "done"
        elif self.screen == "done":
            if key in (ord("q"), 27, 10, 13):
                return False
        return True

    def _outputs_exist(self) -> bool:
        return any(path.exists() for path in self._output_paths())

    def _output_paths(self) -> List[Path]:
        paths = []
        if self.mode in ("text", "both"):
            paths.append(self.output_base.with_suffix(".txt"))
        if self.mode in ("zip", "both"):
            paths.append(self.output_base.with_suffix(".zip"))
        return paths

    def projection_warnings(self) -> List[str]:
        warnings = []
        selected = [entry.relative_path for entry in self.snapshot.entries if not entry.is_directory and entry.selected]
        if self.flatten:
            names: Dict[str, List[str]] = {}
            for relative in selected:
                target = relative.replace("/", "_") if self.name_by_path else Path(relative).name
                names.setdefault(target.casefold(), []).append(relative)
            warnings.extend(f"flatten collision: {', '.join(paths)} -> {name}"
                            for name, paths in names.items() if len(paths) > 1)
            if self.mode in ("zip", "both") and "folder_structure.txt" in names:
                warnings.append("ZIP marker conflict: folder_structure.txt")
        for path in self._output_paths():
            try:
                path.resolve().relative_to(self.source.resolve())
            except ValueError:
                continue
            warnings.append(f"output is inside source: {path}")
        if not self.snapshot.complete:
            warnings.append("scan is incomplete")
        return warnings

    def post_trim_estimate(self) -> tuple[int, int]:
        files = [(entry.relative_path, entry.size_bytes or 0) for entry in self.snapshot.entries
                 if not entry.is_directory and entry.selected]
        remaining = sum(size for _, size in files)
        if self.max_size is None:
            return len(files), remaining
        target = self.max_size * 1024 * 1024
        preference_set = set(self.preferences)
        preferred = [item for item in files if Path(item[0]).suffix in preference_set]
        other = [item for item in files if Path(item[0]).suffix not in preference_set]
        def ordering(item):
            return -item[1], item[0].casefold(), item[0]
        for victim in sorted(preferred, key=ordering) + sorted(other, key=ordering):
            if remaining <= target:
                break
            files.remove(victim)
            remaining -= victim[1]
        return len(files), remaining

    def generate(self) -> bool:
        self.poll_worker()
        if self.scan_pending:
            self.message = "Selection update is still running; wait for it to finish before generating."
            return False
        warnings = self.projection_warnings()
        if any("flatten collision" in warning or "ZIP marker conflict" in warning or
               "scan is incomplete" in warning or "output is inside source" in warning
               for warning in warnings):
            self.message = "Resolve projection conflicts or scan errors before generating."
            return False
        current = Inventory(self.source).snapshot(self.exclusion())
        approved = [(e.relative_path, e.size_bytes) for e in self.snapshot.entries if not e.is_directory and e.selected]
        actual = [(e.relative_path, e.size_bytes) for e in current.entries if not e.is_directory and e.selected]
        if not current.complete or actual != approved:
            self.snapshot = current
            self.message = "Source changed or scan is incomplete; review the updated selection before generating."
            self.screen = "tree"
            return False
        text_path = self.output_base.with_suffix(".txt")
        zip_path = self.output_base.with_suffix(".zip")
        rules = self.exclusion()
        try:
            self.output_base.parent.mkdir(parents=True, exist_ok=True)
            if self.mode in ("text", "both"):
                text_file_mode(str(self.source), str(text_path), rules.exclude_dirs, rules.exclude_exts,
                               rules.exclude_files, rules.remove_patterns, rules.keep_patterns,
                               self.flatten, self.name_by_path, False)
            if self.mode in ("zip", "both"):
                zip_folder(str(self.source), str(zip_path), rules.exclude_dirs, rules.exclude_exts,
                           rules.exclude_files, rules.remove_patterns, rules.keep_patterns,
                           self.max_size, self.preferences, self.flatten, self.name_by_path, False)
        except OSError as exc:
            self.message = f"Packaging failed: {exc}"
            return False
        return True


def render_virtual_screen(state: TuiState, height: int = 24, width: int = 100) -> List[str]:
    """Render a clipped, headless screen representation for tests and accessibility."""
    lines = [f"LLM Packaging · {state.screen} · {state.source}"]
    if state.screen == "tree":
        entries = state.visible_entries()
        for index, entry in enumerate(entries):
            depth = len(Path(entry.relative_path).parts) - 1
            icon = "▾" if entry.is_directory and entry.relative_path in state.expanded else "▸" if entry.is_directory else "·"
            mark = "✓" if entry.selected else "×"
            size = f" {entry.size_bytes:,} B" if entry.size_bytes is not None and not entry.is_directory else ""
            lines.append(f"{'  ' * depth}{mark} {icon} {entry.relative_path}{size}")
        stale = " · scanning (snapshot may be stale)" if state.scan_pending else ""
        lines.append(f"Selected {state.snapshot.selected_files} files · {state.snapshot.selected_directories} dirs · {format_size(state.snapshot.selected_bytes)} · {state.snapshot.errors} errors{stale}")
    elif state.screen == "groups":
        lines.append(f"Grouping: {['directory', 'extension', 'filename', 'largest'][state.group_mode]} · sort by {'size' if state.sort_by_size else 'count'}")
        lines.extend(f"{g['count']:>5} {g['bytes']:>12,} B {g['kind']}: {g['key']}" for g in state.groups())
    elif state.screen == "group_detail":
        groups = state.groups()
        if groups:
            group = groups[state.group_index]
            lines.append(f"{group['kind']}: {group['key']} · {group['count']} entries · {format_size(group['bytes'])}")
            lines.append("↑/↓ member · E exclude exact path · X exclude group · Esc back")
            lines.extend(f"{'▶' if index == state.member_index else ' '} {path}"
                         for index, path in enumerate(group["paths"]))
    elif state.screen == "filters":
        lines.append("↑/↓ select · D remove · U undo · Y redo · A add · Esc back")
        lines.extend(f"{'▶' if index == state.rule_index else ' '} {kind}: {value} [{origin}]"
                     for index, (kind, value, origin) in enumerate(state.active_rules()))
    elif state.screen == "settings":
        lines.extend([f"Source: {state.source}", f"Output base: {state.output_base}",
                      f"Mode: {state.mode}", f"Preset: {state.preset or '(none)'}",
                      f"Flatten: {state.flatten}", f"Name by path: {state.name_by_path}",
                      f"Dry run: {state.dry_run}", "M mode · F flatten · N names · D dry-run",
                      "P edit source · O edit output · Enter begin"])
    elif state.screen == "review":
        lines.extend([f"Mode: {state.mode}", f"Text: {state.output_base.with_suffix('.txt')}",
                      f"ZIP: {state.output_base.with_suffix('.zip')}",
                      f"Selected: {state.snapshot.selected_files} files, {format_size(state.snapshot.selected_bytes)}",
                      f"Output exists: {'yes (overwrite confirmation required)' if state._outputs_exist() else 'no'}",
                      "Press Y to generate, N to return" if not state.dry_run else "Dry-run: generation disabled"])
        lines.append(f"ZIP pre-compression estimate: {state.post_trim_estimate()[0]} files, {format_size(state.post_trim_estimate()[1])}")
        lines.append("Consolidated text readability: pending until generation")
        lines.extend("Warning: " + warning for warning in state.projection_warnings())
    else:
        lines.extend(["Generation complete", str(state.output_base)])
    if state.message:
        lines.append(state.message)
    if state.screen == "tree" and len(lines) > height:
        status = lines[-1]
        rows = lines[1:-1]
        max_rows = max(1, height - 2)
        start = max(0, min(state.selected_index - max_rows + 1, len(rows) - max_rows))
        lines = [lines[0], *rows[start:start + max_rows], status]
    return [line[:max(1, width - 1)] for line in lines[:max(1, height)]]


def launch_tui(state: TuiState) -> int:
    """Run curses frontend; dependency/terminal failures are explicit and never package."""
    try:
        import curses
    except ImportError:
        extra = " Install it with 'python -m pip install windows-curses'." if sys.platform == "win32" else ""
        print(f"Unable to start packaging TUI: curses is unavailable.{extra}", file=sys.stderr)
        return 2
    try:
        globals()["_curses"] = curses
        curses.wrapper(_run_curses, state)
    except Exception as exc:
        state.close()
        print(f"Unable to start packaging TUI: {exc}", file=sys.stderr)
        return 2
    return 0


def _run_curses(screen, state: TuiState) -> None:
    curses = globals()["_curses"]
    screen.keypad(True)
    curses.curs_set(0)
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        state.poll_worker()
        display_lines = render_virtual_screen(state, height - 1, width)
        status_line = display_lines.pop() if state.screen == "tree" and display_lines else None
        for row, line in enumerate(display_lines):
            try:
                screen.addnstr(row, 0, line, max(1, width - 1))
            except curses.error:
                pass
        if status_line is not None and height > 1:
            clipped = status_line[-max(1, width - 1):]
            try:
                screen.addnstr(height - 2, max(0, width - len(clipped)), clipped, max(1, width - 1))
            except curses.error:
                pass
        footer = "↑/↓ move  +/- depth  v view  f rules  g groups  s settings  x exclude  i keep  Enter review  q quit"
        try:
            screen.addnstr(height - 1, 0, footer, max(1, width - 1), curses.A_REVERSE)
            screen.refresh()
        except curses.error:
            pass
        screen.timeout(100)
        key = screen.getch()
        if key == -1:
            continue
        if state.screen == "filters" and key == ord("a"):
            prompt_row = max(0, height - 2)
            try:
                screen.addnstr(prompt_row, 0, "kind:value (directory, extension, filename, remove, keep): ", max(1, width - 1))
                curses.echo()
                raw = screen.getstr(prompt_row, min(width - 1, 58)).decode("utf-8")
                kind, separator, value = raw.partition(":")
                if separator:
                    state.add_rule(kind.strip(), value.strip())
            except (UnicodeDecodeError, OSError, curses.error) as exc:
                state.message = f"Rule not accepted: {exc}"
            finally:
                curses.noecho()
            continue
        if state.screen == "settings" and key in (ord("p"), ord("o")):
            screen.addstr(max(0, height - 2), 0, "Source path: " if key == ord("p") else "Output base: ")
            curses.echo()
            try:
                raw = screen.getstr(max(0, height - 2), min(width - 1, 13 if key == ord("p") else 13))
                value = Path(raw.decode("utf-8")).expanduser()
                if key == ord("p"):
                    value = value.resolve()
                    if value.is_dir():
                        state.source = value
                        state._inventory = Inventory(value)
                        state.refresh()
                        state.message = "Source updated"
                    else:
                        state.message = "Source must be an existing directory"
                else:
                    state.output_base = value
                    state.overwrite_confirmed = False
            except (UnicodeDecodeError, OSError) as exc:
                state.message = f"Path not accepted: {exc}"
            finally:
                curses.noecho()
            continue
        if not state.process_key(key):
            state.close()
            return

