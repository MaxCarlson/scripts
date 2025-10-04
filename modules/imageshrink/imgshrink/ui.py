#!/usr/bin/env python3
"""
UI adapter: tries to use 'termdash' if importable; otherwise a simple ANSI dashboard.

Keys:
  - 'v' : toggle bottom log panel
  - '0'..'9' : switch active worker log view
  - 'q' : quit early (signals orchestrator)
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .events import Event


# ---------- Common model ----------

@dataclass
class WorkerView:
    name: str
    folder: str = ""
    progress: float = 0.0   # 0..1
    eta_s: Optional[float] = None
    speed_mib_s: float = 0.0
    done_bytes: int = 0
    total_bytes: int = 0
    current_status: str = ""
    log_lines: List[str] = field(default_factory=list)

    def line_text(self, width: int = 100) -> str:
        pct = int(max(0.0, min(1.0, self.progress)) * 100)
        eta = "--:--:--" if self.eta_s is None else _fmt_eta(self.eta_s)
        speed = f"{self.speed_mib_s:5.2f}MiB/s"
        left = f"[{self.name:02}] {pct:3d}% {speed} ETA {eta} "
        right = (self.folder or "").replace("\t", " ").replace("\n", " ")
        avail = max(8, width - len(left) - 1)
        if len(right) > avail:
            right = right[:avail - 1] + "…"
        return left + right

    def append_log(self, text: str, limit: int = 3000) -> None:
        self.log_lines.append(text)
        if len(self.log_lines) > limit:
            self.log_lines = self.log_lines[-limit:]


def _fmt_eta(sec: float) -> str:
    if sec is None:
        return "--:--:--"
    s = int(max(0, sec))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------- ANSI fallback dashboard ----------

class _AnsiDashboard:
    """
    Minimal ANSI dashboard; best-effort compatibility with the Termdash-like UX.
    """

    def __init__(self, num_workers: int, refresh_hz: float = 8.0) -> None:
        self._views: Dict[int, WorkerView] = {i: WorkerView(name=f"{i+1:02}") for i in range(num_workers)}
        self._running = False
        self._refresh = 1.0 / max(1e-3, refresh_hz)
        self._lock = threading.RLock()
        self._show_log = True
        self._active_log_id = 0
        self._stop_requested = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()
        self._kbd = threading.Thread(target=self._keyboard_loop, daemon=True)
        self._kbd.start()

    def stop(self) -> None:
        self._running = False
        self._stop_requested = True
        try:
            sys.stdout.write("\033[0m\n")
            sys.stdout.flush()
        except Exception:
            pass

    def apply(self, ev: Event) -> None:
        with self._lock:
            v = self._views.get(ev.worker_id)
            if not v:
                return
            if ev.type in ("WORKER_ONLINE",):
                v.current_status = "online"
            elif ev.type == "FOLDER_START":
                v.folder = ev.payload.get("folder", "")
                v.total_bytes = ev.payload.get("total_bytes", 0)
                v.done_bytes = 0
                v.progress = 0.0
                v.current_status = "processing"
                v.append_log(f"START {v.folder}")
            elif ev.type == "FOLDER_PROGRESS":
                v.done_bytes = ev.payload.get("done_bytes", v.done_bytes)
                tb = max(1, ev.payload.get("total_bytes", v.total_bytes))
                v.total_bytes = tb
                v.progress = min(1.0, v.done_bytes / tb)
                v.speed_mib_s = ev.payload.get("speed_mib_s", v.speed_mib_s)
                v.eta_s = ev.payload.get("eta_s", v.eta_s)
            elif ev.type == "FOLDER_FINISH":
                v.progress = 1.0
                v.done_bytes = v.total_bytes
                v.current_status = "done"
                v.append_log(f"FINISH {v.folder}")
            elif ev.type == "FOLDER_ERROR":
                v.current_status = f"error: {ev.payload.get('message','')}"
                v.append_log(f"ERROR {v.folder}: {ev.payload.get('message','')}")
            elif ev.type == "LOG":
                v.append_log(str(ev.payload.get("text", "")))

    def _render_loop(self) -> None:
        try:
            while self._running:
                with self._lock:
                    lines = []
                    title = "IMG Shrink | p=pause? n/a • v=toggle log • 0-9=switch worker log • q=quit"
                    lines.append(title)
                    lines.append("-" * max(20, len(title)))
                    for wid in sorted(self._views.keys()):
                        lines.append(self._views[wid].line_text(100))
                    lines.append("-" * 100)
                    if self._show_log:
                        active = self._views.get(self._active_log_id)
                        head = f"Program Log [{self._active_log_id+1:02}]"
                        lines.append(head)
                        if active:
                            lines.extend(active.log_lines[-20:])
                    content = "\n".join(lines)

                sys.stdout.write("\033[2J\033[H")
                sys.stdout.write(content)
                sys.stdout.write("\n")
                sys.stdout.flush()
                time.sleep(self._refresh)
        finally:
            pass

    def _keyboard_loop(self) -> None:
        try:
            if sys.platform.startswith("win"):
                import msvcrt
                while not self._stop_requested:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        if not ch:
                            continue
                        self._handle_key(ch.decode(errors="ignore"))
                    time.sleep(0.05)
            else:
                import termios, tty, select
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setcbreak(fd)
                    while not self._stop_requested:
                        r, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if r:
                            ch = sys.stdin.read(1)
                            self._handle_key(ch)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            return

    def _handle_key(self, ch: str) -> None:
        if ch == "q":
            self._stop_requested = True
            self._running = False
        elif ch == "v":
            self._show_log = not self._show_log
        elif ch.isdigit():
            idx = int(ch) - 1
            if idx in self._views:
                self._active_log_id = idx

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested


# ---------- Termdash adapter (optional) ----------

class _TermdashDashboard(_AnsiDashboard):
    """
    If `termdash` is available, render worker rows as Stat lines.
    Keyboard handling remains ours (so UX matches).
    """
    def __init__(self, num_workers: int, refresh_hz: float = 8.0):
        super().__init__(num_workers, refresh_hz)
        from termdash import TermDash, Line, Stat  # type: ignore
        self._td = TermDash(align_columns=True, enable_separators=True, separator_style="rule")
        self._Stat = Stat
        self._Line = Line
        # Build lines per worker
        for wid in range(num_workers):
            name = f"worker-{wid+1:02}"
            self._td.add_line(
                name,
                [
                    self._Stat("ID", f"{wid+1:02}", prefix="[", format_string="{}]", unit=""),
                    self._Stat("PROG", "0%", unit=""),
                    self._Stat("SPD", "0.00", unit="MiB/s"),
                    self._Stat("ETA", "--:--:--", unit=""),
                    self._Stat("FOLDER", "", no_expand=True, display_width=60),
                ],
            )
        self._title = self._Line("_title", [self._Stat("IMG Shrink", "", unit="", color="1;36")], style="header")
        self._td.add_line_obj(self._title)
        self._td.render()

    def _render_loop(self) -> None:
        # Update TermDash rows each tick, and print log section below via ANSI.
        try:
            while self._running:
                with self._lock:
                    for wid, v in self._views.items():
                        line = self._td.get_line(f"worker-{wid+1:02}")
                        if not line:
                            continue
                        pct = f"{int(v.progress*100):d}%"
                        eta = "--:--:--" if v.eta_s is None else _fmt_eta(v.eta_s)
                        values = [f"{wid+1:02}", pct, f"{v.speed_mib_s:0.2f}", eta, v.folder or ""]
                        line.update_values(values)
                    self._td.render()

                    # Below, show log panel with ANSI (keeps it simple)
                    sys.stdout.write("\n" + "-" * 100 + "\n")
                    if self._show_log:
                        active = self._views.get(self._active_log_id)
                        head = f"Program Log [{self._active_log_id+1:02}]"
                        sys.stdout.write(head + "\n")
                        if active:
                            sys.stdout.write("\n".join(active.log_lines[-20:]) + "\n")
                    sys.stdout.flush()
                time.sleep(self._refresh)
        finally:
            pass


# ---------- Public factory ----------

def make_dashboard(num_workers: int, refresh_hz: float = 8.0):
    try:
        import importlib
        importlib.import_module("termdash")
        return _TermdashDashboard(num_workers, refresh_hz)
    except Exception:
        return _AnsiDashboard(num_workers, refresh_hz)