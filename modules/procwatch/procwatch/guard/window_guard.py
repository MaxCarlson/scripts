"""Targeted WinEvent window guard preserving the NeutralizeEngine suppression strategy."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import os
import queue
import sys
import threading
import time
from typing import Any, Callable, Protocol

from procwatch.config import CONSOLE_WINDOW_CLASSES, GuardConfig, GuardMode
from procwatch.correlator.ancestry import get_boot_id
from procwatch.models import (
    ApiAttempt,
    CollectorStats,
    GuardDecision,
    WindowState,
    utc_now_iso,
)

# Win32 event & window constants
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
OBJID_WINDOW = 0
CHILDID_SELF = 0

SW_SHOWNORMAL = 1
SW_SHOWMINNOACTIVE = 7
GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

LSFW_LOCK = 1
LSFW_UNLOCK = 2
VK_LBUTTON = 0x01
QS_ALLINPUT = 0x04FF
PM_REMOVE = 0x0001
WM_QUIT = 0x0012


@dataclass(slots=True)
class RawWindowEvent:
    """Bounded primitive window event emitted from WinEvent hook to correlator queue."""

    window_instance_id: str
    hwnd: int
    owner_pid: int
    owner_tid: int
    window_class: str
    title: str
    win_event: int
    visible: bool
    is_foreground: bool
    foreground_hwnd: int
    state: WindowState
    timestamp_utc: str
    monotonic_ns: int
    callback_arrival_ns: int
    guard_decision: GuardDecision | None = None


@dataclass(slots=True)
class WindowInstance:
    """Per-HWND-lifetime state tracking originals and classification."""

    window_instance_id: str
    hwnd: int
    owner_pid: int
    owner_tid: int
    window_class: str
    first_seen_ns: int
    first_seen_utc: str
    initial_title: str
    current_title: str
    title_history: list[str] = field(default_factory=list)
    state: WindowState = WindowState.FIRST_SEEN
    original_ex_style: int | None = None
    original_placement: Any = None
    modified_by_guard: bool = False
    ex_style_restored: bool = False
    suppress_until_ns: int = 0
    became_visible: bool = False
    stole_foreground: bool = False
    restore_attempts: list[ApiAttempt] = field(default_factory=list)


class WindowBackend(Protocol):
    """Abstraction over Win32 window operations for testability and platform isolation."""

    def enum_windows(self) -> set[int]: ...
    def get_foreground_window(self) -> int: ...
    def get_ancestor_root(self, hwnd: int) -> int: ...
    def get_class_name(self, hwnd: int) -> str: ...
    def get_window_title(self, hwnd: int) -> str: ...
    def get_window_thread_process_id(self, hwnd: int) -> tuple[int, int]: ...
    def is_window(self, hwnd: int) -> bool: ...
    def is_window_visible(self, hwnd: int) -> bool: ...
    def get_ex_style(self, hwnd: int) -> int: ...
    def set_ex_style(self, hwnd: int, ex_style: int) -> ApiAttempt: ...
    def get_window_placement(self, hwnd: int) -> Any: ...
    def set_window_placement(self, hwnd: int, placement: Any) -> ApiAttempt: ...
    def set_window_pos_offscreen(self, hwnd: int, x: int, y: int) -> ApiAttempt: ...
    def show_window_min_noactive(self, hwnd: int) -> ApiAttempt: ...
    def lock_set_foreground_window(self, lock_code: int) -> ApiAttempt: ...
    def restore_focus(self, target_hwnd: int) -> list[ApiAttempt]: ...


if sys.platform == "win32":

    class _POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.UINT),
            ("flags", wintypes.UINT),
            ("showCmd", wintypes.UINT),
            ("ptMinPosition", _POINT),
            ("ptMaxPosition", _POINT),
            ("rcNormalPosition", _RECT),
        ]

    WinEventProcType = ctypes.WINFUNCTYPE(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        wintypes.LONG,
        wintypes.LONG,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    EnumWindowsProcType = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # 64-bit safe prototypes
    _user32.SetWinEventHook.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HMODULE,
        WinEventProcType,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _user32.SetWinEventHook.restype = wintypes.HANDLE
    _user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    _user32.UnhookWinEvent.restype = wintypes.BOOL
    _user32.EnumWindows.argtypes = [EnumWindowsProcType, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = wintypes.LONG
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    _user32.SetWindowLongW.restype = wintypes.LONG
    _user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    _user32.GetWindowPlacement.restype = wintypes.BOOL
    _user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    _user32.SetWindowPlacement.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindowAsync.restype = wintypes.BOOL
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.LockSetForegroundWindow.argtypes = [wintypes.UINT]
    _user32.LockSetForegroundWindow.restype = wintypes.BOOL
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.MsgWaitForMultipleObjects.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _user32.MsgWaitForMultipleObjects.restype = wintypes.DWORD
    _user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.PeekMessageW.restype = wintypes.BOOL
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.TranslateMessage.restype = wintypes.BOOL
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = wintypes.LPARAM
    _user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class Win32WindowBackend:
    """Real Windows 11 user32/kernel32 implementation of WindowBackend."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32WindowBackend requires Windows (win32).")

    def enum_windows(self) -> set[int]:
        handles: set[int] = set()

        def _collect(hwnd: int, _lparam: int) -> bool:
            handles.add(int(hwnd))
            return True

        _user32.EnumWindows(EnumWindowsProcType(_collect), 0)
        return handles

    def get_foreground_window(self) -> int:
        return int(_user32.GetForegroundWindow() or 0)

    def get_ancestor_root(self, hwnd: int) -> int:
        return int(_user32.GetAncestor(hwnd, GA_ROOT) or 0)

    def get_class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        length = _user32.GetClassNameW(hwnd, buf, 256)
        return buf.value if length > 0 else ""

    def get_window_title(self, hwnd: int) -> str:
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def get_window_thread_process_id(self, hwnd: int) -> tuple[int, int]:
        pid = wintypes.DWORD()
        tid = int(_user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
        return tid, int(pid.value)

    def is_window(self, hwnd: int) -> bool:
        return bool(_user32.IsWindow(hwnd))

    def is_window_visible(self, hwnd: int) -> bool:
        return bool(_user32.IsWindowVisible(hwnd))

    def get_ex_style(self, hwnd: int) -> int:
        return int(_user32.GetWindowLongW(hwnd, GWL_EXSTYLE))

    def set_ex_style(self, hwnd: int, ex_style: int) -> ApiAttempt:
        ctypes.set_last_error(0)
        prev = _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        err = ctypes.get_last_error()
        ok = prev != 0 or err == 0
        return ApiAttempt(api="SetWindowLongW", success=ok, error_code=err)

    def get_window_placement(self, hwnd: int) -> WINDOWPLACEMENT | None:
        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(WINDOWPLACEMENT)
        if _user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
            return wp
        return None

    def set_window_placement(self, hwnd: int, placement: Any) -> ApiAttempt:
        if placement is None:
            return ApiAttempt(api="SetWindowPlacement", success=False, detail="no_saved_placement")
        ctypes.set_last_error(0)
        ok = bool(_user32.SetWindowPlacement(hwnd, ctypes.byref(placement)))
        err = ctypes.get_last_error()
        return ApiAttempt(api="SetWindowPlacement", success=ok, error_code=err)

    def set_window_pos_offscreen(self, hwnd: int, x: int = -32000, y: int = -32000) -> ApiAttempt:
        ctypes.set_last_error(0)
        ok = bool(_user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE))
        err = ctypes.get_last_error()
        return ApiAttempt(api="SetWindowPos", success=ok, error_code=err)

    def show_window_min_noactive(self, hwnd: int) -> ApiAttempt:
        ctypes.set_last_error(0)
        ok = bool(_user32.ShowWindowAsync(hwnd, SW_SHOWMINNOACTIVE))
        err = ctypes.get_last_error()
        return ApiAttempt(api="ShowWindowAsync", success=ok, error_code=err)

    def lock_set_foreground_window(self, lock_code: int) -> ApiAttempt:
        ctypes.set_last_error(0)
        ok = bool(_user32.LockSetForegroundWindow(lock_code))
        err = ctypes.get_last_error()
        return ApiAttempt(
            api=f"LockSetForegroundWindow({lock_code})",
            success=ok,
            error_code=err,
        )

    def restore_focus(self, target_hwnd: int) -> list[ApiAttempt]:
        attempts: list[ApiAttempt] = []
        if not target_hwnd or not self.is_window(target_hwnd) or not self.is_window_visible(target_hwnd):
            return attempts
        if _user32.GetAsyncKeyState(VK_LBUTTON) < 0:
            attempts.append(ApiAttempt(api="GetAsyncKeyState(VK_LBUTTON)", success=False, detail="mouse_dragging"))
            return attempts

        fg_hwnd = self.get_foreground_window()
        if fg_hwnd == target_hwnd:
            return attempts

        cur_tid = int(_kernel32.GetCurrentThreadId())
        fg_tid, _ = self.get_window_thread_process_id(fg_hwnd) if fg_hwnd else (0, 0)
        target_tid, _ = self.get_window_thread_process_id(target_hwnd)

        attached_fg = False
        attached_target = False
        try:
            if fg_tid and fg_tid != cur_tid:
                attached_fg = bool(_user32.AttachThreadInput(cur_tid, fg_tid, True))
            if target_tid and target_tid != cur_tid and target_tid != fg_tid:
                attached_target = bool(_user32.AttachThreadInput(cur_tid, target_tid, True))
            ctypes.set_last_error(0)
            ok = bool(_user32.SetForegroundWindow(target_hwnd))
            err = ctypes.get_last_error()
            attempts.append(ApiAttempt(api="SetForegroundWindow", success=ok, error_code=err))
        finally:
            if attached_target:
                _user32.AttachThreadInput(cur_tid, target_tid, False)
            if attached_fg:
                _user32.AttachThreadInput(cur_tid, fg_tid, False)
        return attempts


class NeutralizeEngine:
    """Focused WinEvent hook engine with lifecycle-safe NeutralizeEngine suppression."""

    def __init__(
        self,
        config: GuardConfig | None = None,
        *,
        backend: WindowBackend | None = None,
        event_queue: queue.Queue[RawWindowEvent] | None = None,
        on_window_event: Callable[[RawWindowEvent], None] | None = None,
        stats: CollectorStats | None = None,
        boot_id: str | None = None,
    ) -> None:
        self.config = config or GuardConfig()
        self.backend: WindowBackend = backend if backend is not None else Win32WindowBackend()
        self.event_queue = event_queue
        self.on_window_event = on_window_event
        self.stats = stats or CollectorStats()
        self.boot_id = boot_id or get_boot_id()
        self.own_pid = os.getpid()

        self.baseline_hwnds: set[int] = self.backend.enum_windows()
        self.active_instances: dict[int, WindowInstance] = {}
        self.last_valid_fg: int = self.backend.get_foreground_window()
        self._lock = threading.RLock()
        self._instance_seq = 0
        self._fg_locked_by_us = False
        self._in_callback = False

        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._startup_error: BaseException | None = None
        self._callback_ref: Any = None

    def _classify_window(
        self,
        hwnd: int,
        cls_name: str,
        title: str,
        event: int,
    ) -> tuple[str, str, str]:
        """Return (decision, matched_rule, reason): decision in {'suppress', 'pending', 'allow', 'ignore'}."""
        if self.backend.get_ancestor_root(hwnd) != hwnd:
            return "ignore", "non_root_window", "not a top-level root window"

        if self.config.exclude_pattern and title and self.config.exclude_pattern.search(title):
            return "allow", "exclude_pattern", "title matched exclude_pattern"

        mode = self.config.mode
        if mode == GuardMode.ALL_WINDOWS:
            ex_style = self.backend.get_ex_style(hwnd)
            if ex_style & WS_EX_TOOLWINDOW:
                return "ignore", "tool_window", "WS_EX_TOOLWINDOW ignored in all-windows mode"
            return "suppress", "all_windows_experimental", "experimental all-windows mode"

        if cls_name not in CONSOLE_WINDOW_CLASSES:
            return "ignore", "non_console_class", f"class {cls_name!r} is not a console/terminal class"

        if mode == GuardMode.OBSERVE:
            return "allow", "observe_only", "observe mode never modifies windows"

        if mode == GuardMode.ALL_CONSOLES:
            return "suppress", "all_consoles", f"console class {cls_name} matched all-consoles"

        # SMART mode: never suppress solely because title is empty on CREATE!
        if not title:
            if event == EVENT_OBJECT_CREATE:
                return "pending", "smart_empty_title_create", "empty title at CREATE; awaiting SHOW/title"
            return "allow", "smart_empty_title_uncertain", "no positive automation evidence (empty title)"

        if self.config.interactive_pattern.search(title):
            return "allow", "smart_interactive_title", "title matched interactive terminal pattern"

        if self.config.title_pattern.search(title):
            return "suppress", "smart_automation_title", "title matched automation pattern"

        return "allow", "smart_fail_open", "no positive automation evidence"

    def _capture_originals_once(self, instance: WindowInstance) -> None:
        """Capture original extended style and placement once per HWND instance."""
        if instance.original_ex_style is None:
            instance.original_ex_style = self.backend.get_ex_style(instance.hwnd)
        if instance.original_placement is None:
            instance.original_placement = self.backend.get_window_placement(instance.hwnd)

    def _neutralize_window(self, instance: WindowInstance, *, restore_exstyle: bool) -> list[ApiAttempt]:
        """Execute the proven NeutralizeEngine suppression sequence with full instrumentation."""
        attempts: list[ApiAttempt] = []
        if self.config.mode == GuardMode.OBSERVE:
            return attempts

        hwnd = instance.hwnd
        self._capture_originals_once(instance)
        orig_ex = instance.original_ex_style or 0

        lock_attempt = self.backend.lock_set_foreground_window(LSFW_LOCK)
        attempts.append(lock_attempt)
        if lock_attempt.success:
            self._fg_locked_by_us = True

        try:
            if not (orig_ex & WS_EX_NOACTIVATE):
                attempts.append(self.backend.set_ex_style(hwnd, orig_ex | WS_EX_NOACTIVATE))

            attempts.append(self.backend.set_window_pos_offscreen(hwnd, -32000, -32000))
            attempts.append(self.backend.show_window_min_noactive(hwnd))
            instance.modified_by_guard = True

            if restore_exstyle and not (orig_ex & WS_EX_NOACTIVATE) and not instance.ex_style_restored:
                ex_restore = self.backend.set_ex_style(hwnd, orig_ex)
                attempts.append(ex_restore)
                if ex_restore.success:
                    instance.ex_style_restored = True

            if self.config.restore_focus and self.last_valid_fg and self.last_valid_fg != hwnd:
                attempts.extend(self.backend.restore_focus(self.last_valid_fg))
        finally:
            if self._fg_locked_by_us:
                unlock_attempt = self.backend.lock_set_foreground_window(LSFW_UNLOCK)
                attempts.append(unlock_attempt)
                if unlock_attempt.success:
                    self._fg_locked_by_us = False

        return attempts

    def restore_window(self, hwnd: int) -> list[ApiAttempt]:
        """Restore original extended style and placement for a guard-modified window."""
        attempts: list[ApiAttempt] = []
        with self._lock:
            instance = self.active_instances.get(hwnd)
            if instance is None or not instance.modified_by_guard:
                return attempts
            if not self.backend.is_window(hwnd):
                attempt = ApiAttempt(api="IsWindow", success=False, detail="hwnd_already_destroyed")
                attempts.append(attempt)
                instance.restore_attempts.extend(attempts)
                instance.modified_by_guard = False
                instance.state = WindowState.DESTROYED
                instance.suppress_until_ns = 0
                self.active_instances.pop(hwnd, None)
                return attempts

            all_ok = True
            if instance.original_ex_style is not None and not instance.ex_style_restored:
                res = self.backend.set_ex_style(hwnd, instance.original_ex_style)
                attempts.append(res)
                if res.success:
                    instance.ex_style_restored = True
                else:
                    all_ok = False

            if instance.original_placement is not None:
                res_place = self.backend.set_window_placement(hwnd, instance.original_placement)
                attempts.append(res_place)
                if not res_place.success:
                    all_ok = False

            instance.restore_attempts.extend(attempts)
            instance.suppress_until_ns = 0
            if all_ok:
                instance.modified_by_guard = False
                instance.state = WindowState.RESTORED
        return attempts

    def restore_all_modified(self) -> int:
        """Restore all active windows currently modified by the guard. Returns count attempted."""
        with self._lock:
            hwnds = [h for h, inst in self.active_instances.items() if inst.modified_by_guard]
        for hwnd in hwnds:
            self.restore_window(hwnd)
        if self._fg_locked_by_us:
            res = self.backend.lock_set_foreground_window(LSFW_UNLOCK)
            if res.success:
                self._fg_locked_by_us = False
        return len(hwnds)

    def handle_win_event(
        self,
        event: int,
        hwnd: int,
        id_object: int = OBJID_WINDOW,
        id_child: int = CHILDID_SELF,
        event_time_ms: int = 0,
    ) -> RawWindowEvent | None:
        """Process a single WinEvent synchronously and emit a bounded RawWindowEvent."""
        if not hwnd or id_object != OBJID_WINDOW or id_child != CHILDID_SELF:
            return None
        if self._in_callback:
            return None

        self._in_callback = True
        try:
            return self._process_event_inner(event, int(hwnd), event_time_ms)
        finally:
            self._in_callback = False

    def _process_event_inner(self, event: int, hwnd_int: int, _event_time_ms: int) -> RawWindowEvent | None:
        arrival_ns = time.monotonic_ns()
        now_utc = utc_now_iso()
        self.stats.win_events_received += 1

        if event == EVENT_OBJECT_DESTROY:
            with self._lock:
                inst = self.active_instances.pop(hwnd_int, None)
                self.baseline_hwnds.discard(hwnd_int)
            if inst is None:
                return None
            inst.state = WindowState.DESTROYED
            raw = RawWindowEvent(
                window_instance_id=inst.window_instance_id,
                hwnd=hwnd_int,
                owner_pid=inst.owner_pid,
                owner_tid=inst.owner_tid,
                window_class=inst.window_class,
                title=inst.current_title,
                win_event=event,
                visible=False,
                is_foreground=False,
                foreground_hwnd=self.backend.get_foreground_window(),
                state=WindowState.DESTROYED,
                timestamp_utc=now_utc,
                monotonic_ns=arrival_ns,
                callback_arrival_ns=arrival_ns,
            )
            self._emit_event(raw)
            return raw

        with self._lock:
            inst = self.active_instances.get(hwnd_int)

        # Existing window already in suppress window
        if inst is not None and inst.state == WindowState.SUPPRESSED:
            if arrival_ns < inst.suppress_until_ns:
                attempts = self._neutralize_window(inst, restore_exstyle=(event == EVENT_OBJECT_SHOW))
                if event == EVENT_OBJECT_SHOW:
                    inst.became_visible = True
                fg_hwnd = self.backend.get_foreground_window()
                if fg_hwnd == hwnd_int:
                    inst.stole_foreground = True
                return None
            inst.suppress_until_ns = 0
            return None

        # Pre-existing baseline or already-allowed window: track foreground only
        if inst is None and hwnd_int in self.baseline_hwnds:
            if event == EVENT_SYSTEM_FOREGROUND and self.backend.is_window_visible(hwnd_int):
                self.last_valid_fg = hwnd_int
            return None

        if inst is not None and inst.state in (WindowState.ALLOWED, WindowState.RESTORED):
            visible = self.backend.is_window_visible(hwnd_int)
            title = self.backend.get_window_title(hwnd_int)
            fg_hwnd = self.backend.get_foreground_window()
            is_fg = fg_hwnd == hwnd_int
            if event == EVENT_SYSTEM_FOREGROUND and visible:
                self.last_valid_fg = hwnd_int
            title_changed = bool(title and title != inst.current_title)
            became_vis_now = event == EVENT_OBJECT_SHOW and visible and not inst.became_visible
            if title_changed or became_vis_now:
                if title_changed:
                    inst.current_title = title
                    inst.title_history.append(title)
                if visible:
                    inst.became_visible = True
                if is_fg:
                    inst.stole_foreground = True
                raw = RawWindowEvent(
                    window_instance_id=inst.window_instance_id,
                    hwnd=hwnd_int,
                    owner_pid=inst.owner_pid,
                    owner_tid=inst.owner_tid,
                    window_class=inst.window_class,
                    title=inst.current_title,
                    win_event=event,
                    visible=visible,
                    is_foreground=is_fg,
                    foreground_hwnd=fg_hwnd,
                    state=inst.state,
                    timestamp_utc=now_utc,
                    monotonic_ns=arrival_ns,
                    callback_arrival_ns=arrival_ns,
                )
                self._emit_event(raw)
                return raw
            return None

        tid, pid = self.backend.get_window_thread_process_id(hwnd_int)
        if pid == self.own_pid:
            with self._lock:
                self.baseline_hwnds.add(hwnd_int)
            return None

        cls_name = self.backend.get_class_name(hwnd_int)
        title = self.backend.get_window_title(hwnd_int)
        visible = self.backend.is_window_visible(hwnd_int)
        fg_hwnd = self.backend.get_foreground_window()
        is_fg = fg_hwnd == hwnd_int

        if inst is None:
            with self._lock:
                self._instance_seq += 1
                seq = self._instance_seq
                inst = WindowInstance(
                    window_instance_id=f"{self.boot_id}:{hwnd_int}:{arrival_ns}:{seq}",
                    hwnd=hwnd_int,
                owner_pid=pid,
                owner_tid=tid,
                window_class=cls_name,
                first_seen_ns=arrival_ns,
                first_seen_utc=now_utc,
                initial_title=title,
                current_title=title,
                title_history=[title] if title else [],
                became_visible=visible,
                stole_foreground=is_fg,
            )
                with self._lock:
                    self.active_instances[hwnd_int] = inst
        else:
            if title and title != inst.current_title:
                inst.current_title = title
                inst.title_history.append(title)
            if visible:
                inst.became_visible = True
            if is_fg:
                inst.stole_foreground = True

        decision_kind, matched_rule, reason = self._classify_window(hwnd_int, cls_name, title, event)

        if decision_kind == "ignore":
            with self._lock:
                self.active_instances.pop(hwnd_int, None)
                self.baseline_hwnds.add(hwnd_int)
            if event == EVENT_SYSTEM_FOREGROUND and visible:
                self.last_valid_fg = hwnd_int
            return None

        if decision_kind == "pending":
            inst.state = WindowState.PENDING
            self.stats.guard_pending_count += 1
            raw = RawWindowEvent(
                window_instance_id=inst.window_instance_id,
                hwnd=hwnd_int,
                owner_pid=pid,
                owner_tid=tid,
                window_class=cls_name,
                title=title,
                win_event=event,
                visible=visible,
                is_foreground=is_fg,
                foreground_hwnd=fg_hwnd,
                state=WindowState.PENDING,
                timestamp_utc=now_utc,
                monotonic_ns=arrival_ns,
                callback_arrival_ns=arrival_ns,
            )
            self._emit_event(raw)
            return raw

        if decision_kind == "allow":
            inst.state = WindowState.ALLOWED
            self.stats.guard_allowed_count += 1
            if event == EVENT_SYSTEM_FOREGROUND and visible:
                self.last_valid_fg = hwnd_int
            guard_dec = GuardDecision(
                window_instance_id=inst.window_instance_id,
                hwnd=hwnd_int,
                mode=self.config.mode.value,
                matched_rule=matched_rule,
                reason=reason,
                intended_action="observe",
                observed_outcome="allowed",
                callback_latency_ms=(time.monotonic_ns() - arrival_ns) / 1_000_000.0,
            )
            raw = RawWindowEvent(
                window_instance_id=inst.window_instance_id,
                hwnd=hwnd_int,
                owner_pid=pid,
                owner_tid=tid,
                window_class=cls_name,
                title=title,
                win_event=event,
                visible=visible,
                is_foreground=is_fg,
                foreground_hwnd=fg_hwnd,
                state=WindowState.ALLOWED,
                timestamp_utc=now_utc,
                monotonic_ns=arrival_ns,
                callback_arrival_ns=arrival_ns,
                guard_decision=guard_dec,
            )
            self._emit_event(raw)
            return raw

        # decision_kind == "suppress"
        inst.state = WindowState.SUPPRESSED
        inst.suppress_until_ns = arrival_ns + int(self.config.suppress_window_seconds * 1_000_000_000)
        attempts = self._neutralize_window(inst, restore_exstyle=(event == EVENT_OBJECT_SHOW))
        action_done_ns = time.monotonic_ns()
        self.stats.guard_suppressed_count += 1
        if any(not a.success and a.api in ("SetWindowPos", "ShowWindowAsync") for a in attempts):
            self.stats.guard_errors += 1

        guard_dec = GuardDecision(
            window_instance_id=inst.window_instance_id,
            hwnd=hwnd_int,
            mode=self.config.mode.value,
            matched_rule=matched_rule,
            reason=reason,
            intended_action="minimize_noactivate",
            observed_outcome="suppressed" if not self.backend.is_window_visible(hwnd_int) else "minimized_attempted",
            attempted_apis=attempts,
            callback_latency_ms=(action_done_ns - arrival_ns) / 1_000_000.0,
            action_latency_ms=(action_done_ns - arrival_ns) / 1_000_000.0,
        )
        raw = RawWindowEvent(
            window_instance_id=inst.window_instance_id,
            hwnd=hwnd_int,
            owner_pid=pid,
            owner_tid=tid,
            window_class=cls_name,
            title=title,
            win_event=event,
            visible=visible,
            is_foreground=is_fg,
            foreground_hwnd=fg_hwnd,
            state=WindowState.SUPPRESSED,
            timestamp_utc=now_utc,
            monotonic_ns=arrival_ns,
            callback_arrival_ns=arrival_ns,
            guard_decision=guard_dec,
        )
        self._emit_event(raw)
        return raw

    def _emit_event(self, raw: RawWindowEvent) -> None:
        if self.event_queue is not None:
            try:
                self.event_queue.put_nowait(raw)
            except queue.Full:
                self.stats.win_events_dropped += 1
        if self.on_window_event is not None:
            self.on_window_event(raw)

    def _on_win_event_ctypes(
        self,
        _hook: int,
        event: int,
        hwnd: int,
        id_object: int,
        id_child: int,
        _event_thread: int,
        event_time: int,
    ) -> None:
        if not hwnd:
            return
        self.handle_win_event(int(event), int(hwnd), int(id_object), int(id_child), int(event_time))

    def run_blocking(self) -> None:
        """Run the WinEvent message loop on the current thread until stopped."""
        if sys.platform != "win32":
            raise RuntimeError("NeutralizeEngine.run_blocking requires Windows (win32).")

        self._thread_id = int(_kernel32.GetCurrentThreadId())
        self._callback_ref = WinEventProcType(self._on_win_event_ctypes)

        flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
        hook_fg = _user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            None,
            self._callback_ref,
            0,
            0,
            flags,
        )
        hook_obj = _user32.SetWinEventHook(
            EVENT_OBJECT_CREATE,
            EVENT_OBJECT_SHOW,
            None,
            self._callback_ref,
            0,
            0,
            flags,
        )
        if not hook_fg or not hook_obj:
            if hook_fg:
                _user32.UnhookWinEvent(hook_fg)
            if hook_obj:
                _user32.UnhookWinEvent(hook_obj)
            err = RuntimeError("Failed to register focused SetWinEventHook(s).")
            self._startup_error = err
            self._ready_event.set()
            raise err

        self._ready_event.set()
        msg = wintypes.MSG()
        try:
            while not self._stop_event.is_set():
                _user32.MsgWaitForMultipleObjects(0, None, False, 50, QS_ALLINPUT)
                while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    if msg.message == WM_QUIT:
                        return
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _user32.UnhookWinEvent(hook_fg)
            _user32.UnhookWinEvent(hook_obj)
            self.restore_all_modified()
            self._callback_ref = None

    def start_background(self, *, timeout: float = 2.0) -> None:
        """Start the WinEvent message loop in a background thread and wait until ready."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self.run_blocking, name="procwatch-win-guard", daemon=True)
        self._thread.start()
        if not self._ready_event.wait(timeout=timeout):
            raise TimeoutError("NeutralizeEngine background hook thread did not become ready in time.")
        if self._startup_error is not None:
            raise self._startup_error

    def stop(self, *, timeout: float = 2.0) -> None:
        """Idempotently stop the WinEvent message loop, unhook, and restore modified windows."""
        self._stop_event.set()
        if sys.platform == "win32" and self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self.restore_all_modified()
