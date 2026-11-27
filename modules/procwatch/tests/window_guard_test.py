"""Unit tests for procwatch.guard.window_guard (NeutralizeEngine)."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import re

import pytest

from procwatch.config import ConfigValidationError, GuardConfig, GuardMode
from procwatch.guard.window_guard import (
    CHILDID_SELF,
    EVENT_OBJECT_CREATE,
    EVENT_OBJECT_DESTROY,
    EVENT_OBJECT_SHOW,
    LSFW_LOCK,
    LSFW_UNLOCK,
    OBJID_WINDOW,
    WS_EX_NOACTIVATE,
    NeutralizeEngine,
    RawWindowEvent,
)
from procwatch.models import ApiAttempt, WindowState


@dataclass
class FakeWindow:
    hwnd: int
    pid: int
    tid: int
    cls_name: str
    title: str
    visible: bool = False
    ex_style: int = 0x00040000  # WS_EX_APPWINDOW
    placement: tuple[int, int, int, int] = (100, 100, 900, 600)
    minimized: bool = False


class FakeWindowBackend:
    """In-memory Win32 WindowBackend for deterministic unit testing."""

    def __init__(self) -> None:
        self.windows: dict[int, FakeWindow] = {}
        self.fg_hwnd: int = 10
        self.lock_calls: list[int] = []
        self.focus_restored_to: list[int] = []
        self.windows[10] = FakeWindow(hwnd=10, pid=999, tid=999, cls_name="ApplicationFrameWindow", title="Editor", visible=True)

    def enum_windows(self) -> set[int]:
        return set(self.windows.keys())

    def get_foreground_window(self) -> int:
        return self.fg_hwnd

    def get_ancestor_root(self, hwnd: int) -> int:
        return hwnd

    def get_class_name(self, hwnd: int) -> str:
        return self.windows[hwnd].cls_name if hwnd in self.windows else ""

    def get_window_title(self, hwnd: int) -> str:
        return self.windows[hwnd].title if hwnd in self.windows else ""

    def get_window_thread_process_id(self, hwnd: int) -> tuple[int, int]:
        w = self.windows.get(hwnd)
        return (w.tid, w.pid) if w else (0, 0)

    def is_window(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def is_window_visible(self, hwnd: int) -> bool:
        return self.windows[hwnd].visible if hwnd in self.windows else False

    def get_ex_style(self, hwnd: int) -> int:
        return self.windows[hwnd].ex_style if hwnd in self.windows else 0

    def set_ex_style(self, hwnd: int, ex_style: int) -> ApiAttempt:
        if hwnd in self.windows:
            self.windows[hwnd].ex_style = ex_style
            return ApiAttempt(api="SetWindowLongW", success=True)
        return ApiAttempt(api="SetWindowLongW", success=False, error_code=1400)

    def get_window_placement(self, hwnd: int) -> tuple[int, int, int, int] | None:
        return self.windows[hwnd].placement if hwnd in self.windows else None

    def set_window_placement(self, hwnd: int, placement: tuple[int, int, int, int]) -> ApiAttempt:
        if hwnd in self.windows:
            self.windows[hwnd].placement = placement
            self.windows[hwnd].minimized = False
            return ApiAttempt(api="SetWindowPlacement", success=True)
        return ApiAttempt(api="SetWindowPlacement", success=False, error_code=1400)

    def set_window_pos_offscreen(self, hwnd: int, x: int, y: int) -> ApiAttempt:
        if hwnd in self.windows:
            self.windows[hwnd].placement = (x, y, x + 800, y + 500)
            return ApiAttempt(api="SetWindowPos", success=True)
        return ApiAttempt(api="SetWindowPos", success=False, error_code=1400)

    def show_window_min_noactive(self, hwnd: int) -> ApiAttempt:
        if hwnd in self.windows:
            self.windows[hwnd].minimized = True
            self.windows[hwnd].visible = False
            return ApiAttempt(api="ShowWindowAsync", success=True)
        return ApiAttempt(api="ShowWindowAsync", success=False, error_code=1400)

    def lock_set_foreground_window(self, lock_code: int) -> ApiAttempt:
        self.lock_calls.append(lock_code)
        return ApiAttempt(api=f"LockSetForegroundWindow({lock_code})", success=True)

    def restore_focus(self, target_hwnd: int) -> list[ApiAttempt]:
        self.fg_hwnd = target_hwnd
        self.focus_restored_to.append(target_hwnd)
        return [ApiAttempt(api="SetForegroundWindow", success=True)]


def test_observe_mode_never_modifies_windows() -> None:
    backend = FakeWindowBackend()
    q: queue.Queue[RawWindowEvent] = queue.Queue()
    engine = NeutralizeEngine(GuardConfig(mode=GuardMode.OBSERVE), backend=backend, event_queue=q, boot_id="b1")

    backend.windows[200] = FakeWindow(
        hwnd=200, pid=2000, tid=2001, cls_name="ConsoleWindowClass", title=r"C:\repo\.venv\Scripts\python.exe", visible=True
    )
    ev = engine.handle_win_event(EVENT_OBJECT_SHOW, 200, OBJID_WINDOW, CHILDID_SELF)
    assert ev is not None
    assert ev.state == WindowState.ALLOWED
    assert backend.windows[200].minimized is False
    assert backend.lock_calls == []


def test_smart_mode_empty_title_create_is_pending_then_interactive_allowed() -> None:
    backend = FakeWindowBackend()
    engine = NeutralizeEngine(GuardConfig(mode=GuardMode.SMART), backend=backend, boot_id="b1")

    # CREATE with empty title must NOT suppress
    backend.windows[300] = FakeWindow(hwnd=300, pid=3000, tid=3001, cls_name="CASCADIA_HOSTING_WINDOW_CLASS", title="")
    ev1 = engine.handle_win_event(EVENT_OBJECT_CREATE, 300)
    assert ev1 is not None
    assert ev1.state == WindowState.PENDING
    assert backend.windows[300].minimized is False

    # SHOW with interactive title -> ALLOWED
    backend.windows[300].title = "Windows PowerShell"
    backend.windows[300].visible = True
    ev2 = engine.handle_win_event(EVENT_OBJECT_SHOW, 300)
    assert ev2 is not None
    assert ev2.state == WindowState.ALLOWED
    assert backend.windows[300].minimized is False


@pytest.mark.parametrize(
    ("mode", "expected_state", "expected_minimized"),
    [
        (GuardMode.SMART, WindowState.ALLOWED, False),
        (GuardMode.ALL_CONSOLES, WindowState.SUPPRESSED, True),
    ],
)
def test_powershell_7_title_is_interactive_only_in_smart_mode(mode, expected_state, expected_minimized) -> None:
    backend = FakeWindowBackend()
    engine = NeutralizeEngine(GuardConfig(mode=mode), backend=backend, boot_id="b1")
    backend.windows[350] = FakeWindow(
        hwnd=350,
        pid=3500,
        tid=3501,
        cls_name="CASCADIA_HOSTING_WINDOW_CLASS",
        title="PowerShell 7",
        visible=True,
    )

    event = engine.handle_win_event(EVENT_OBJECT_SHOW, 350)

    assert event is not None
    assert event.state is expected_state
    assert backend.windows[350].minimized is expected_minimized


def test_smart_mode_suppresses_automation_title_and_restores_originals() -> None:
    backend = FakeWindowBackend()
    engine = NeutralizeEngine(GuardConfig(mode=GuardMode.SMART), backend=backend, boot_id="b1")

    orig_ex = 0x00040000
    orig_rect = (120, 140, 920, 640)
    backend.windows[400] = FakeWindow(
        hwnd=400,
        pid=4000,
        tid=4001,
        cls_name="ConsoleWindowClass",
        title=r"C:\src\scripts\.venv\Scripts\python.exe",
        ex_style=orig_ex,
        placement=orig_rect,
        visible=True,
    )
    ev = engine.handle_win_event(EVENT_OBJECT_CREATE, 400)
    assert ev is not None
    assert ev.state == WindowState.SUPPRESSED
    assert backend.windows[400].minimized is True
    assert backend.windows[400].ex_style & WS_EX_NOACTIVATE
    # Foreground lock must be balanced (LOCK then UNLOCK)
    assert backend.lock_calls == [LSFW_LOCK, LSFW_UNLOCK]

    # Repeated SHOW during suppress window must restore orig_ex and not overwrite saved originals
    engine.handle_win_event(EVENT_OBJECT_SHOW, 400)
    assert backend.windows[400].ex_style == orig_ex

    # Explicit restore_window restores placement as well
    engine.restore_window(400)
    assert backend.windows[400].placement == orig_rect
    assert backend.windows[400].ex_style == orig_ex
    assert backend.windows[400].minimized is False


def test_exclude_pattern_protects_matching_title() -> None:
    backend = FakeWindowBackend()
    cfg = GuardConfig(mode=GuardMode.ALL_CONSOLES, exclude_pattern=re.compile(r"MyProtectedShell"))
    engine = NeutralizeEngine(cfg, backend=backend, boot_id="b1")

    backend.windows[500] = FakeWindow(
        hwnd=500, pid=5000, tid=5001, cls_name="ConsoleWindowClass", title="MyProtectedShell", visible=True
    )
    ev = engine.handle_win_event(EVENT_OBJECT_SHOW, 500)
    assert ev is not None
    assert ev.state == WindowState.ALLOWED
    assert backend.windows[500].minimized is False


def test_hwnd_destroy_and_reuse_creates_fresh_instance() -> None:
    backend = FakeWindowBackend()
    engine = NeutralizeEngine(GuardConfig(mode=GuardMode.ALL_CONSOLES), backend=backend, boot_id="b1")

    backend.windows[600] = FakeWindow(hwnd=600, pid=6000, tid=6001, cls_name="ConsoleWindowClass", title="cmd.exe")
    ev1 = engine.handle_win_event(EVENT_OBJECT_CREATE, 600)
    assert ev1 is not None

    ev_destroy = engine.handle_win_event(EVENT_OBJECT_DESTROY, 600)
    assert ev_destroy is not None
    assert ev_destroy.state == WindowState.DESTROYED
    assert 600 not in engine.active_instances

    # Reused HWND 600 gets a new window_instance_id
    backend.windows[600] = FakeWindow(hwnd=600, pid=6002, tid=6003, cls_name="ConsoleWindowClass", title="cmd.exe")
    ev2 = engine.handle_win_event(EVENT_OBJECT_CREATE, 600)
    assert ev2 is not None
    assert ev2.window_instance_id != ev1.window_instance_id


def test_all_windows_requires_experimental_opt_in() -> None:
    with pytest.raises(ConfigValidationError):
        GuardConfig(mode=GuardMode.ALL_WINDOWS, allow_all_windows_experimental=False)


def test_restore_window_when_hwnd_already_destroyed_clears_state_with_diagnostic() -> None:
    backend = FakeWindowBackend()
    engine = NeutralizeEngine(GuardConfig(mode=GuardMode.ALL_CONSOLES), backend=backend, boot_id="b1")

    backend.windows[700] = FakeWindow(hwnd=700, pid=7000, tid=7001, cls_name="ConsoleWindowClass", title="cmd.exe")
    ev = engine.handle_win_event(EVENT_OBJECT_CREATE, 700)
    assert ev is not None
    assert engine.active_instances[700].modified_by_guard is True

    # Simulate OS destroying the window before DESTROY event was pumped
    del backend.windows[700]
    attempts = engine.restore_window(700)
    assert len(attempts) == 1
    assert attempts[0].api == "IsWindow"
    assert attempts[0].detail == "hwnd_already_destroyed"
    assert 700 not in engine.active_instances


def test_allowed_window_emits_updated_title_on_show() -> None:
    backend = FakeWindowBackend()
    engine = NeutralizeEngine(GuardConfig(mode=GuardMode.OBSERVE), backend=backend, boot_id="b1")

    backend.windows[800] = FakeWindow(hwnd=800, pid=8000, tid=8001, cls_name="CASCADIA_HOSTING_WINDOW_CLASS", title="")
    ev1 = engine.handle_win_event(EVENT_OBJECT_CREATE, 800)
    assert ev1 is not None
    assert ev1.state == WindowState.ALLOWED

    backend.windows[800].title = "PROCWATCH_SYNTH_POPUP_TEST"
    backend.windows[800].visible = True
    ev2 = engine.handle_win_event(EVENT_OBJECT_SHOW, 800)
    assert ev2 is not None
    assert ev2.title == "PROCWATCH_SYNTH_POPUP_TEST"
    assert ev2.visible is True
