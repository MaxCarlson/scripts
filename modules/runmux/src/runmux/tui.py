"""Curses workspace for browsing and viewing Runmux-managed processes."""

from __future__ import annotations

import curses
import json
import re
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

from cli_tui.process_runner import OutputViewport

from runmux.client import ClientError, interact_run
from runmux.constants import TERMINAL_STATUSES
from runmux.ipc import IpcError
from runmux.log_follow import IncrementalLogReader, LogFollowWorker, PaneOutputCapture
from runmux.models import RunRecord
from runmux.store import RunStore
from runmux.tui_adapter import RunmuxTuiAdapter
from runmux.workspace_state import WorkspaceState, WorkspaceStateStore

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass
class RunmuxView:
    """One user-opened process output view."""

    record: RunRecord
    follower: LogFollowWorker
    viewport: OutputViewport


class RunBrowserWorker:
    """Refresh process discovery and transient status outside the curses loop."""

    def __init__(self, adapter: RunmuxTuiAdapter, *, interval: float = 1.0) -> None:
        self.adapter = adapter
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._records: list[RunRecord] = []
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="runmux-tui-browser", daemon=True)
        self._thread.start()

    def snapshot(self) -> tuple[list[RunRecord], str | None]:
        with self._lock:
            return list(self._records), self._error

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 2))

    def refresh_once(self) -> list[RunRecord]:
        records = self.adapter.list_runs()
        projected = [
            self.adapter.refresh_display_status(record)
            if record.status not in TERMINAL_STATUSES
            else record
            for record in records
        ]
        with self._lock:
            self._records = projected
            self._error = None
        return projected

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh_once()
            except Exception as error:
                with self._lock:
                    self._error = str(error)
            self._stop.wait(self.interval)


@dataclass(frozen=True)
class ActionResult:
    kind: str
    value: object | None = None
    error: str | None = None
    open_view: bool = False


class RunmuxActionWorker:
    """Run supervisor IPC and history filesystem work away from curses."""

    def __init__(self) -> None:
        self._requests: Queue[tuple[str, Callable[[], object], bool] | None] = Queue()
        self._results: Queue[ActionResult] = Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="runmux-tui-actions", daemon=True)
        self._thread.start()

    def submit(self, kind: str, action: Callable[[], object], *, open_view: bool = False) -> None:
        self.start()
        self._requests.put((kind, action, open_view))

    def poll(self) -> list[ActionResult]:
        results: list[ActionResult] = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except Empty:
                return results

    def stop(self) -> None:
        self._stop.set()
        self._requests.put(None)
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            request = self._requests.get()
            if request is None:
                return
            kind, action, open_view = request
            try:
                self._results.put(ActionResult(kind, action(), open_view=open_view))
            except Exception as error:
                self._results.put(ActionResult(kind, error=str(error), open_view=open_view))


class RunmuxTuiApp:
    """Compose Runmux process records with reusable cli_tui view primitives."""

    def __init__(
        self,
        adapter: RunmuxTuiAdapter,
        state_store: WorkspaceStateStore,
        *,
        refresh_interval: float = 1.0,
    ) -> None:
        self.adapter = adapter
        self.state_store = state_store
        self.browser = RunBrowserWorker(adapter, interval=refresh_interval)
        self.actions = RunmuxActionWorker()
        self.views: dict[str, RunmuxView] = {}
        self.captures: dict[str, PaneOutputCapture] = {}
        self.open_run_ids: list[str] = []
        self.active_run_id: str | None = None
        self.browser_records: list[RunRecord] = []
        self.selected_run_id: str | None = None
        self.search_query = ""
        self.focus = "browser"
        self.status_message = ""
        self._chooser_kind: str | None = None
        self._chooser_items: list[object] = []
        self._chooser_index = 0
        self._help_visible = False
        self.handoff_run_id: str | None = None
        self.handoff_state: WorkspaceState | None = None
        self._running = False
        self._closed = False

    @property
    def visible_runs(self) -> list[RunRecord]:
        query = self.search_query.casefold().strip()
        if not query:
            return list(self.browser_records)
        return [
            record
            for record in self.browser_records
            if query in " ".join((record.id, record.display_name, record.command_line, record.status)).casefold()
        ]

    def refresh_browser(self) -> list[RunRecord]:
        """Synchronously refresh the browser model, primarily for non-UI callers."""

        previous = self.selected_run_id
        records = self.browser.refresh_once()
        self.browser_records = records
        visible_ids = {record.id for record in self.visible_runs}
        if previous in visible_ids:
            self.selected_run_id = previous
        elif self.visible_runs:
            self.selected_run_id = self.visible_runs[0].id
        else:
            self.selected_run_id = None
        return records

    def poll_background(self) -> None:
        """Copy background browser results into UI-owned state."""

        records, error = self.browser.snapshot()
        if records:
            previous = self.selected_run_id
            self.browser_records = records
            by_id = {record.id: record for record in records}
            for run_id, view in self.views.items():
                if run_id in by_id:
                    view.record = by_id[run_id]
            visible_ids = {record.id for record in self.visible_runs}
            if previous not in visible_ids:
                self.selected_run_id = self.visible_runs[0].id if self.visible_runs else None
        if error:
            self.status_message = f"Browser refresh failed: {error}"
        for result in self.actions.poll():
            if result.error:
                self.status_message = f"{result.kind} failed: {result.error}"
            elif result.kind in {"history", "saved"}:
                self._chooser_kind = result.kind
                self._chooser_items = list(result.value or [])
                self._chooser_index = 0
                self.status_message = f"Choose a {result.kind} command; Esc closes"
            elif isinstance(result.value, RunRecord):
                self.status_message = f"{result.kind}: {result.value.id} ({result.value.status})"
                if result.open_view:
                    try:
                        self.open_view(result.value.id)
                    except Exception as action_error:
                        self.status_message = f"Process started, but view could not open: {action_error}"
            else:
                self.status_message = f"{result.kind} complete"

    def set_search(self, query: str) -> None:
        self.search_query = query
        visible_ids = {record.id for record in self.visible_runs}
        if self.selected_run_id not in visible_ids:
            self.selected_run_id = self.visible_runs[0].id if self.visible_runs else None

    def select(self, delta: int) -> None:
        records = self.visible_runs
        if not records:
            self.selected_run_id = None
            return
        current = next((index for index, record in enumerate(records) if record.id == self.selected_run_id), 0)
        self.selected_run_id = records[(current + delta) % len(records)].id

    def open_selected(self) -> str | None:
        if self.selected_run_id is None:
            return None
        self.open_view(self.selected_run_id)
        return self.selected_run_id

    def open_view(self, run_id: str, *, scroll_offset: int = 0) -> None:
        if run_id in self.views:
            self.activate_view(run_id)
            return
        record = self.adapter.get_run(run_id)
        if record.id != run_id:
            return
        reader = IncrementalLogReader(record.log_file)
        follower = LogFollowWorker(reader)
        view = RunmuxView(record=record, follower=follower, viewport=OutputViewport())
        view.viewport.scroll_offset = max(0, scroll_offset)
        self.views[run_id] = view
        self.open_run_ids.append(run_id)
        self.active_run_id = run_id
        self.focus = "output"
        follower.start()
        self.status_message = f"Opened {record.display_name} ({record.id})"

    def activate_view(self, run_id: str) -> None:
        if run_id in self.views:
            self.active_run_id = run_id
            self.focus = "output"

    def cycle_view(self, delta: int) -> None:
        if not self.open_run_ids:
            self.active_run_id = None
            return
        current = self.open_run_ids.index(self.active_run_id) if self.active_run_id in self.open_run_ids else 0
        self.activate_view(self.open_run_ids[(current + delta) % len(self.open_run_ids)])

    def close_view(self, run_id: str) -> None:
        capture = self.captures.pop(run_id, None)
        if capture is not None:
            capture.stop()
        view = self.views.pop(run_id, None)
        if view is None:
            return
        view.follower.stop()
        self.open_run_ids.remove(run_id)
        if self.active_run_id == run_id:
            self.active_run_id = self.open_run_ids[-1] if self.open_run_ids else None
        self.status_message = f"Closed view {run_id}; process continues"

    def close_all_views(self) -> None:
        for run_id in list(self.open_run_ids):
            self.close_view(run_id)

    def workspace_snapshot(self) -> WorkspaceState:
        return WorkspaceState(
            open_run_ids=list(self.open_run_ids),
            active_run_id=self.active_run_id,
            scroll_offsets={run_id: view.viewport.scroll_offset for run_id, view in self.views.items()},
        )

    def save_layout(self) -> None:
        self.state_store.save(self.workspace_snapshot())
        self.status_message = "Workspace layout saved"

    def capture_output(self, run_id: str, destination: Path, *, overwrite: bool = False) -> None:
        if run_id not in self.views:
            raise KeyError(f"No open output view for run {run_id}")
        target = Path(destination).expanduser()
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        previous = self.captures.pop(run_id, None)
        if previous is not None:
            previous.stop()
        capture = PaneOutputCapture(self.views[run_id].record.log_file, target)
        capture.start()
        self.captures[run_id] = capture
        self.status_message = f"Saving pane output to {target}"

    def request_launch(self, argv: list[str], *, cwd: Path, name: str | None = None) -> None:
        self.actions.submit("launch", lambda: self.adapter.launch(argv, cwd=cwd, name=name), open_view=True)

    def request_history(self) -> None:
        self.actions.submit("history", self.adapter.history_entries)

    def request_saved_commands(self) -> None:
        self.actions.submit("saved", self.adapter.saved_commands)

    def _launch_chooser_item(self, screen: curses.window) -> None:
        if not self._chooser_items or self._chooser_kind is None:
            return
        item = self._chooser_items[self._chooser_index]
        kind = self._chooser_kind
        self._chooser_kind = None
        self._chooser_items = []
        if kind == "saved":
            argv = getattr(item, "argv", None)
            cwd = getattr(item, "cwd", None)
        else:
            argv = item.get("argv") if isinstance(item, dict) else None
            cwd = item.get("cwd") if isinstance(item, dict) else None
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
            self.status_message = "Saved command has invalid argv metadata"
            return
        if not isinstance(cwd, str) or not Path(cwd).is_dir():
            self.status_message = f"Command working directory is unavailable: {cwd}"
            return
        if not self._confirm_launch(screen, argv, Path(cwd)):
            return
        if kind == "saved":
            self.actions.submit("saved launch", lambda: self.adapter.launch_saved(item), open_view=True)
            return
        self.request_launch(argv, cwd=Path(cwd))

    def restore_workspace(self, state: WorkspaceState | None = None) -> None:
        state = state or self.state_store.load()
        existing = {record.id for record in self.adapter.list_runs()}
        for run_id in state.open_run_ids:
            if run_id not in existing:
                continue
            try:
                self.open_view(run_id, scroll_offset=state.scroll_offsets.get(run_id, 0))
            except Exception as error:
                self.status_message = f"Could not restore {run_id}: {error}"
        if state.active_run_id in self.views:
            self.activate_view(state.active_run_id)

    def quit(self, *, save_layout: bool) -> None:
        if save_layout:
            self.save_layout()
        self._running = False
        self.close()

    def close(self) -> None:
        """Stop UI-owned threads only; never signal a managed process."""

        if self._closed:
            return
        self._closed = True
        self.browser.stop()
        self.actions.stop()
        self.close_all_views()

    def request_attach(self, run_id: str) -> bool:
        """Leave curses so the caller can attach through Runmux's input lock."""

        view = self.views.get(run_id)
        if view is None:
            self.status_message = f"Open a process view before attaching: {run_id}"
            return False
        if view.record.status in TERMINAL_STATUSES:
            self.status_message = f"Cannot attach to terminal process {run_id}"
            return False
        self.handoff_run_id = run_id
        self._running = False
        return True

    def run(self, *, initial_state: WorkspaceState | None = None) -> str | None:
        """Restore workspace and run the curses event loop."""

        self.restore_workspace(initial_state)
        self.browser.start()
        self.actions.start()
        try:
            curses.wrapper(self._main)
        finally:
            if self.handoff_run_id is not None:
                self.handoff_state = self.workspace_snapshot()
            self.close()
        return self.handoff_run_id

    def _main(self, screen: curses.window) -> None:
        self._running = True
        screen.keypad(True)
        screen.timeout(200)
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            pass
        while self._running:
            self.poll_background()
            self._render(screen)
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            self._handle_key(screen, key)

    def _handle_key(self, screen: curses.window, key: str | int) -> None:
        if self._help_visible:
            self._help_visible = False
            return
        if self._chooser_kind is not None:
            if key == "\x1b":
                self._chooser_kind = None
                self._chooser_items = []
            elif key in (curses.KEY_UP, "k") and self._chooser_items:
                self._chooser_index = (self._chooser_index - 1) % len(self._chooser_items)
            elif key in (curses.KEY_DOWN, "j") and self._chooser_items:
                self._chooser_index = (self._chooser_index + 1) % len(self._chooser_items)
            elif key in ("\n", "\r", curses.KEY_ENTER):
                self._launch_chooser_item(screen)
            return
        if key in ("q", "Q"):
            choice = self._ask_save_layout(screen)
            if choice is not None:
                self.quit(save_layout=choice)
        elif key in ("s", "S"):
            self.save_layout()
        elif key in ("/",):
            self.set_search(self._read_search(screen))
        elif key == "l":
            self._launch_manual(screen)
        elif key == "h":
            self.request_history()
        elif key == "c":
            self.request_saved_commands()
        elif key == "?":
            self._help_visible = True
        elif key == "e" and self.active_run_id in self.views:
            self._capture_output_dialog(screen)
        elif key == "v" and self.active_run_id in self.views:
            run_id = self.active_run_id
            self.actions.submit("save command", lambda: self.adapter.save_command(run_id))
        elif key == "i" and self.active_run_id is not None:
            self.request_attach(self.active_run_id)
        elif key == "\t":
            self.focus = "output" if self.focus == "browser" else "browser"
        elif key == curses.KEY_UP:
            if self.focus == "browser":
                self.select(-1)
            elif self.active_run_id in self.views:
                self.views[self.active_run_id].viewport.scroll_up()
        elif key == curses.KEY_DOWN:
            if self.focus == "browser":
                self.select(1)
            elif self.active_run_id in self.views:
                self.views[self.active_run_id].viewport.scroll_down()
        elif key in (curses.KEY_PPAGE,):
            if self.active_run_id in self.views:
                self.views[self.active_run_id].viewport.scroll_page_up(10)
        elif key in (curses.KEY_NPAGE,):
            if self.active_run_id in self.views:
                self.views[self.active_run_id].viewport.scroll_page_down(10)
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self.open_selected()
        elif key in ("[",):
            self.cycle_view(-1)
        elif key == "]":
            self.cycle_view(1)
        elif key in ("x", "X") and self.active_run_id is not None:
            self.close_view(self.active_run_id)
        elif key == "g" and self.active_run_id in self.views:
            self.views[self.active_run_id].viewport.scroll_to_end()
        elif key in ("p", "P") and self.active_run_id in self.views:
            self._request_pause_resume()
        elif key in ("k", "K") and self.active_run_id in self.views:
            if self._confirm(screen, "Kill this managed process? [y/n]"):
                run_id = self.active_run_id
                force = key == "K"
                if force and not self._confirm(screen, "Force kill this process? [y/n]"):
                    return
                self.actions.submit("kill", lambda: self.adapter.kill(run_id, force=force))
        elif key == "d" and self.active_run_id in self.views:
            run_id = self.active_run_id
            self.actions.submit("duplicate", lambda: self.adapter.duplicate(run_id), open_view=True)
        elif key == "r" and self.active_run_id in self.views:
            run_id = self.active_run_id
            if self.views[run_id].record.status in TERMINAL_STATUSES:
                self.actions.submit("restart", lambda: self.adapter.restart(run_id), open_view=True)
            else:
                self.status_message = "Restart requires a terminal process; use duplicate for a copy"
        elif key == "z" and self.active_run_id in self.views:
            run_id = self.active_run_id
            if self.views[run_id].record.status in TERMINAL_STATUSES:
                if self._confirm(screen, "Remove this terminal registry record? [y/n]"):
                    self.close_view(run_id)
                    self.actions.submit("remove", lambda: self.adapter.remove_terminal(run_id))
            else:
                self.status_message = "Only terminal process records can be removed"

    def _ask_save_layout(self, screen: curses.window) -> bool | None:
        height, width = screen.getmaxyx()
        message = "Save open process views and pane positions before quitting? [y/n, Esc cancels]"
        _safe_addstr(screen, max(0, height - 2), 0, message[: max(0, width - 1)], curses.A_REVERSE)
        screen.refresh()
        while True:
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key in ("y", "Y"):
                return True
            if key in ("n", "N"):
                return False
            if key == "\x1b":
                return None

    def _read_search(self, screen: curses.window) -> str:
        height, width = screen.getmaxyx()
        _safe_addstr(screen, max(0, height - 2), 0, "/"[: max(0, width - 1)], curses.A_REVERSE)
        screen.refresh()
        curses.echo()
        try:
            value = screen.getstr(max(0, height - 2), 1, max(1, width - 2))
        except curses.error:
            return self.search_query
        finally:
            curses.noecho()
        return value.decode("utf-8", errors="replace")

    def _launch_manual(self, screen: curses.window) -> None:
        raw_argv = self._read_line(screen, "argv as JSON array (example: [\"python\", \"-V\"]): ")
        if raw_argv is None:
            return
        try:
            argv = json.loads(raw_argv)
        except json.JSONDecodeError as error:
            self.status_message = f"Invalid JSON argv: {error.msg}"
            return
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
            self.status_message = "argv must be a non-empty JSON array of strings"
            return
        cwd_text = self._read_line(screen, f"working directory [{Path.cwd()}]: ")
        if cwd_text is None:
            return
        cwd = Path(cwd_text).expanduser() if cwd_text.strip() else Path.cwd()
        if not cwd.is_dir():
            self.status_message = f"Working directory does not exist: {cwd}"
            return
        if self._confirm_launch(screen, argv, cwd):
            self.request_launch(argv, cwd=cwd)

    def _confirm_launch(self, screen: curses.window, argv: list[str], cwd: Path) -> bool:
        preview = f"Start argv={json.dumps(argv, ensure_ascii=False)}\nfrom cwd={cwd}? [y/n]"
        return self._confirm(screen, preview)

    def _request_pause_resume(self) -> None:
        run_id = self.active_run_id
        if run_id is None:
            return
        record = self.views[run_id].record
        if record.status == "paused":
            self.actions.submit("resume", lambda: self.adapter.resume(run_id))
        elif record.status in {"pending", "running"}:
            self.actions.submit("pause", lambda: self.adapter.pause(run_id))
        else:
            self.status_message = "This process cannot be paused or resumed in its current state"

    def _capture_output_dialog(self, screen: curses.window) -> None:
        run_id = self.active_run_id
        if run_id is None:
            return
        path_text = self._read_popup_input(screen, "Save pane output", "Output file path:")
        if not path_text:
            return
        target = Path(path_text).expanduser()
        overwrite = target.exists()
        if overwrite and not self._confirm(screen, f"Overwrite {target}? [y/n]"):
            return
        try:
            self.capture_output(run_id, target, overwrite=overwrite)
        except (OSError, ValueError, KeyError) as error:
            self.status_message = f"Could not save pane output: {error}"

    def _confirm(self, screen: curses.window, prompt: str) -> bool:
        height, width = screen.getmaxyx()
        _safe_addstr(screen, max(0, height - 2), 0, prompt[: max(0, width - 1)], curses.A_REVERSE)
        screen.refresh()
        while True:
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key in ("y", "Y"):
                return True
            if key in ("n", "N", "\x1b"):
                return False

    def _read_popup_input(self, screen: curses.window, title: str, prompt: str) -> str | None:
        screen_height, screen_width = screen.getmaxyx()
        box_width = max(30, min(screen_width - 4, 88))
        box_height = 5
        top = max(1, (screen_height - box_height) // 2)
        left = max(1, (screen_width - box_width) // 2)
        try:
            popup = curses.newwin(box_height, box_width, top, left)
            popup.keypad(True)
            popup.box()
            _safe_addstr(popup, 0, 2, f" {title} "[: max(0, box_width - 4)], curses.A_BOLD)
            _safe_addstr(popup, 2, 2, prompt[: max(0, box_width - 4)])
            _safe_addstr(popup, 3, 2, "Enter path  |  Esc cancels"[: max(0, box_width - 4)], curses.A_DIM)
            popup.refresh()
            curses.echo()
            try:
                value = popup.getstr(2, min(box_width - 2, len(prompt) + 3), max(1, box_width - len(prompt) - 5))
            except curses.error:
                return None
            finally:
                curses.noecho()
            return value.decode("utf-8", errors="replace")
        except curses.error:
            return None

    def _read_line(self, screen: curses.window, prompt: str) -> str | None:
        height, width = screen.getmaxyx()
        row = max(0, height - 2)
        _safe_addstr(screen, row, 0, prompt[: max(0, width - 1)], curses.A_REVERSE)
        screen.refresh()
        curses.echo()
        try:
            value = screen.getstr(row, min(len(prompt), max(0, width - 2)), max(1, width - len(prompt) - 1))
        except curses.error:
            return None
        finally:
            curses.noecho()
        return value.decode("utf-8", errors="replace")

    def _render(self, screen: curses.window) -> None:
        self.poll_background()
        height, width = screen.getmaxyx()
        screen.erase()
        if height < 5 or width < 20:
            _safe_addstr(screen, 0, 0, "Terminal too small for runmux tui")
            screen.refresh()
            return
        left_width = max(24, min(38, width // 3))
        right_x = left_width + 1
        right_width = max(1, width - right_x - 1)
        _safe_addstr(
            screen,
            0,
            0,
            "Runmux workspace  Tab: focus  Enter: open  /: search  s: save  q: quit",
            curses.A_BOLD,
        )
        self._draw_tabs(screen, 1, right_x, right_width)
        self._draw_browser(screen, 2, left_width, height - 5)
        self._draw_output(screen, 2, right_x, right_width, height - 5)
        _safe_addstr(screen, height - 2, 0, self.status_message[: max(0, width - 1)])
        footer = "? help  ↑/↓ navigate  [ ] views  l launch  h history  c saved  e export  p pause  k kill  d duplicate"
        _safe_addstr(screen, height - 1, 0, footer[: max(0, width - 1)], curses.A_DIM)
        if self._chooser_kind is not None:
            self._draw_chooser(screen, height, width)
        if self._help_visible:
            self._draw_help(screen, height, width)
        screen.refresh()

    def _draw_browser(self, screen: curses.window, y: int, width: int, height: int) -> None:
        _safe_addstr(screen, y, 0, " PROCESS BROWSER " + ("─" * max(0, width - 18)), curses.A_BOLD)
        rows = self.visible_runs
        selected = self.selected_run_id
        current = next((index for index, record in enumerate(rows) if record.id == selected), 0)
        list_height = max(0, height - 4)
        start = max(0, current - max(0, list_height - 1))
        for index, record in enumerate(rows[start : start + list_height]):
            marker = ">" if record.id == selected else " "
            duration = format_duration(record.runtime_seconds)
            line = f"{marker} {record.numeric_id:>3} {record.status:<8} {record.display_name} {duration}"
            attr = curses.A_REVERSE if record.id == selected and self.focus == "browser" else curses.A_NORMAL
            _safe_addstr(screen, y + 1 + index, 0, line[: max(0, width - 1)], attr)
        if rows and selected is not None and height >= 4:
            selected_record = next((record for record in rows if record.id == selected), None)
            if selected_record is not None:
                detail_y = y + height - 3
                _safe_addstr(screen, detail_y, 0, selected_record.id[: max(0, width - 1)], curses.A_DIM)
                command = selected_record.command_line
                _safe_addstr(screen, detail_y + 1, 0, command[: max(0, width - 1)])

    def _draw_tabs(self, screen: curses.window, y: int, x: int, width: int) -> None:
        if not self.open_run_ids:
            _safe_addstr(screen, y, x, "No open process views", curses.A_DIM)
            return
        pieces = []
        for run_id in self.open_run_ids:
            record = self.views[run_id].record
            label = f" {record.display_name}#{record.numeric_id} "
            pieces.append(f"[{label}]" if run_id == self.active_run_id else label)
        _safe_addstr(screen, y, x, " ".join(pieces)[: max(0, width - 1)], curses.A_BOLD)

    def _draw_output(self, screen: curses.window, y: int, x: int, width: int, height: int) -> None:
        if self.active_run_id not in self.views:
            _safe_addstr(screen, y, x, "Select a process and press Enter to open its output.", curses.A_DIM)
            return
        view = self.views[self.active_run_id]
        record = view.record
        header = f"{record.status} | {record.id} | {record.command_line}"
        _safe_addstr(screen, y, x, header[: max(0, width - 1)], curses.A_BOLD)
        raw_lines = view.follower.snapshot()
        visible = view.viewport.get_visible_lines(raw_lines, height=max(0, height - 1), width=max(1, width - 1))
        for index, line in enumerate(visible):
            _draw_ansi_line(screen, y + 1 + index, x, line, width - 1)

    def _draw_chooser(self, screen: curses.window, height: int, width: int) -> None:
        box_width = max(20, min(width - 4, 88))
        box_height = max(5, min(height - 4, 14))
        top = max(1, (height - box_height) // 2)
        left = max(1, (width - box_width) // 2)
        try:
            window = curses.newwin(box_height, box_width, top, left)
            window.box()
            title = f" {self._chooser_kind} commands: Enter launches, Esc closes "
            _safe_addstr(window, 0, 1, title[: max(0, box_width - 2)], curses.A_BOLD)
            max_items = box_height - 2
            start = max(0, self._chooser_index - max_items + 1)
            for offset, item in enumerate(self._chooser_items[start : start + max_items]):
                index = start + offset
                label = _chooser_label(item)
                attr = curses.A_REVERSE if index == self._chooser_index else curses.A_NORMAL
                _safe_addstr(window, 1 + offset, 1, label[: max(0, box_width - 2)], attr)
            window.noutrefresh()
        except curses.error:
            pass

    def _draw_help(self, screen: curses.window, height: int, width: int) -> None:
        lines = [
            "Runmux process workspace",
            "↑/↓ browse processes or scroll output   Enter open selected process",
            "Tab switch browser/output focus         / search process IDs and commands",
            "[/] switch open views                  x close active view (process keeps running)",
            "l launch JSON argv   h command history   c saved commands   v save active command",
            "e export pane output to a file          i attach through Runmux input lock",
            "p pause/resume   d duplicate   r restart terminal run   z remove terminal record",
            "k confirm normal kill   K confirm force kill   s save layout   q quit and choose save",
            "Press any key to close this help",
        ]
        box_width = max(30, min(width - 4, max(len(line) for line in lines) + 4))
        box_height = min(height - 2, len(lines) + 2)
        top = max(1, (height - box_height) // 2)
        left = max(1, (width - box_width) // 2)
        try:
            window = curses.newwin(box_height, box_width, top, left)
            window.box()
            for index, line in enumerate(lines[: box_height - 2]):
                _safe_addstr(window, index + 1, 2, line[: max(0, box_width - 4)])
            window.refresh()
        except curses.error:
            pass


def run_tui(store: RunStore, *, history_path: Path, root_dir: Path | None = None) -> int:
    """Create and run the persistent process workspace for a RunStore."""

    state_store = WorkspaceStateStore(store.state_dir, root_dir or Path.cwd(), app_id="runmux")
    adapter = RunmuxTuiAdapter(store, history_path)
    resume_state: WorkspaceState | None = None
    status_message = ""
    while True:
        app = RunmuxTuiApp(adapter, state_store)
        app.status_message = status_message
        handoff_run_id = app.run(initial_state=resume_state)
        if handoff_run_id is None:
            return 0
        resume_state = app.handoff_state
        status_message = ""
        try:
            interact_run(store, run_id=handoff_run_id, tail_lines=None)
        except (ClientError, IpcError) as error:
            status_message = f"Attach ended: {error}"


def _draw_ansi_line(screen: curses.window, y: int, x: int, value: str, width: int) -> None:
    cursor = x
    current_fg = 7
    current_bg = 0
    bold = False
    position = 0
    for match in _SGR_RE.finditer(value):
        segment = _CSI_RE.sub("", value[position : match.start()]).replace("\r", "")
        cursor = _draw_segment(screen, y, x, cursor, width, segment, current_fg, current_bg, bold)
        codes = [int(code or "0") for code in match.group(1).split(";")]
        current_fg, current_bg, bold = _sgr_state(codes, current_fg, current_bg, bold)
        position = match.end()
    segment = _CSI_RE.sub("", value[position:]).replace("\r", "")
    _draw_segment(screen, y, x, cursor, width, segment, current_fg, current_bg, bold)


def _draw_segment(
    screen: curses.window,
    y: int,
    x: int,
    cursor: int,
    width: int,
    segment: str,
    fg: int,
    bg: int,
    bold: bool,
) -> int:
    if cursor - x >= width or not segment:
        return cursor
    attr = curses.A_BOLD if bold else curses.A_NORMAL
    if curses.has_colors():
        attr |= curses.color_pair(_color_pair(fg, bg))
    visible = segment[: max(0, width - (cursor - x))]
    _safe_addstr(screen, y, cursor, visible, attr)
    return cursor + len(visible)


def _sgr_state(codes: list[int], fg: int, bg: int, bold: bool) -> tuple[int, int, bool]:
    for code in codes:
        if code == 0:
            fg, bg, bold = 7, 0, False
        elif code == 1:
            bold = True
        elif code == 22:
            bold = False
        elif 30 <= code <= 37:
            fg = code - 30
        elif 90 <= code <= 97:
            fg = code - 90
            bold = True
        elif code == 39:
            fg = 7
        elif 40 <= code <= 47:
            bg = code - 40
        elif 100 <= code <= 107:
            bg = code - 100
        elif code == 49:
            bg = 0
    return fg, bg, bold


def _color_pair(fg: int, bg: int) -> int:
    pair = 1 + (fg % 8) * 8 + (bg % 8)
    try:
        if pair < curses.COLOR_PAIRS:
            curses.init_pair(pair, fg % 8, bg % 8)
            return pair
    except curses.error:
        pass
    return 0


def _safe_addstr(screen: curses.window, y: int, x: int, value: str, attr: int = curses.A_NORMAL) -> None:
    if not value:
        return
    with suppress(curses.error):
        screen.addnstr(y, x, value, len(value), attr)


def format_duration(seconds: float) -> str:
    duration = int(max(0.0, seconds))
    if duration >= 3600:
        return f"{duration // 3600}h{duration % 3600 // 60:02d}m"
    if duration >= 60:
        return f"{duration // 60}m{duration % 60:02d}s"
    return f"{duration}s"


def _chooser_label(item: object) -> str:
    if isinstance(item, dict):
        command_line = item.get("command_line", "")
        cwd = item.get("cwd", "")
        return f"{command_line}  [{cwd}]"
    command_line = getattr(item, "command_line", str(item))
    cwd = getattr(item, "cwd", "")
    return f"{command_line}  [{cwd}]"
