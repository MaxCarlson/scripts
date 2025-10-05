#!/usr/bin/env python3
"""
UI adapter: Renders a live dashboard for the compression process.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .events import Event


@dataclass
class WorkerView:
    name: str
    folder: str = ""
    relative_folder: str = ""
    progress: float = 0.0
    eta_s: Optional[float] = None
    speed_mib_s: float = 0.0
    img_done: int = 0
    img_total: int = 0
    log_lines: List[str] = field(default_factory=list)

    def line_text(self, width: int = 110) -> str:
        pct = int(max(0.0, min(1.0, self.progress)) * 100)
        eta = "--:--:--" if self.eta_s is None else _fmt_eta(self.eta_s)
        speed = f"{self.speed_mib_s:5.2f}MiB/s"
        c = f"{self.img_done}/{self.img_total}".rjust(7)
        left = f"[{self.name}] {pct:3d}% {speed} {c} ETA {eta} "
        right = (self.relative_folder or "").replace("\t", " ").replace("\n", " ")
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


def _fmt_ts(delta_s: float) -> str:
    m, s = divmod(delta_s, 60)
    ms = int((s - int(s)) * 1000)
    return f"[{int(m):02d}:{int(s):02d}:{ms:03d}]"


class Dashboard:
    """Minimal ANSI dashboard with stable refresh to avoid flicker."""

    def __init__(self, num_workers: int, root_path: Path, refresh_hz: float = 10.0) -> None:
        self._views: Dict[int, WorkerView] = {i: WorkerView(name=f"{i+1:02}") for i in range(num_workers)}
        self._running = False
        self._refresh = 1.0 / max(1e-3, refresh_hz)
        self._lock = threading.RLock()
        self._show_log = True
        self._active_log_id = 0
        self._stop_requested = False
        self._start_time = time.time()
        self._root_path = root_path
        self._root_path_logged = False

    def _log(self, view: WorkerView, message: str):
        delta_s = time.time() - self._start_time
        ts = _fmt_ts(delta_s)
        view.append_log(f"{ts} {message}")

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

            if not self._root_path_logged:
                v.append_log(f"Root path: {self._root_path}")
                self._root_path_logged = True

            if ev.type == "WORKER_ONLINE":
                self._log(v, "Worker Start")
            elif ev.type == "SHUTDOWN":
                self._log(v, "Worker Shutdown")
            elif ev.type == "FOLDER_START":
                full_path = ev.payload.get("folder", "")
                relative_path = os.path.relpath(full_path, self._root_path)
                if not relative_path.startswith("."):
                    relative_path = f"./{relative_path}"
                v.folder = full_path
                v.relative_folder = relative_path
                v.img_total = ev.payload.get("img_total", 0)
                v.img_done = 0
                v.progress = 0.0
                self._log(v, "START")
                v.append_log("Folder Name:")
                v.append_log("******************************************")
                v.append_log(v.relative_folder)
                v.append_log("******************************************")
            elif ev.type == "FOLDER_PROGRESS":
                v.img_done = ev.payload.get("img_done", v.img_done)
                v.progress = min(1.0, v.img_done / max(1, v.img_total))
                v.speed_mib_s = ev.payload.get("speed_mib_s", v.speed_mib_s)
                v.eta_s = ev.payload.get("eta_s", v.eta_s)
                self._log(v, f"PROCESSING {v.img_done}/{v.img_total} files analyzed")
            elif ev.type == "FOLDER_STATS":
                self._log(v, f"STATS {ev.payload.get('stats_str', '')}")
            elif ev.type == "FOLDER_FINISH":
                v.progress = 1.0
                v.img_done = v.img_total
                v.append_log("******************************************")
                v.append_log(v.relative_folder)
                v.append_log("******************************************")
                self._log(v, "FINISH")
                
                elapsed = ev.payload.get("elapsed_s")
                if elapsed is not None:
                    files_per_s = ev.payload.get("files_per_s", 0.0)
                    mib_per_s = ev.payload.get("mib_per_s", 0.0)
                    time_str = f"TIME Elapsed: {elapsed:.2f}s, Speed: {files_per_s:.1f} files/s, {mib_per_s:.2f} MiB/s"
                    self._log(v, time_str)

            elif ev.type == "FOLDER_ERROR":
                self._log(v, f"ERROR: {ev.payload.get('message', '')}")
            elif ev.type == "LOG":
                self._log(v, str(ev.payload.get("text", "")))

    def _render_loop(self) -> None:
        try:
            while self._running:
                with self._lock:
                    lines = []
                    title = "IMG Shrink | v=toggle log • 0-9=worker log • q=quit"
                    lines.append(title)
                    lines.append("-" * max(20, len(title)))
                    for wid in sorted(self._views.keys()):
                        lines.append(self._views[wid].line_text(120))
                    lines.append("-" * 120)
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