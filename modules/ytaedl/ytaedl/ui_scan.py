# ytaedl/ui_scan.py
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict

try:
    from termdash import TermDash, Line, Stat, fmt_hms
except Exception:
    TermDash = None  # type: ignore
    Line = None  # type: ignore
    Stat = None  # type: ignore


@dataclass
class WorkerSnapshot:
    file_display: str = ""
    urls_seen: int = 0
    urls_total: int = 0
    downloaded: int = 0
    bad: int = 0
    eta_s: Optional[float] = None
    state: str = "idle"  # idle|working|done


class ScanDashboard:
    """
    Live dashboard for the scanning phase.

    Hotkeys:
      z  -> pause/resume
      q  -> confirm quit (graceful)
      Q  -> force quit (immediate)
    """

    def __init__(self, n_workers: int, total_files: int, log_file: Optional[str] = None):
        if TermDash is None:
            raise RuntimeError("termdash not available; cannot render scan dashboard.")
        self.n_workers = max(1, int(n_workers))
        self.total_files = max(0, int(total_files))
        self._progress = 0
        self._start_ts = time.time()
        self._workers: Dict[str, WorkerSnapshot] = {
            f"scan-{i+1}": WorkerSnapshot() for i in range(self.n_workers)
        }
        self._td = TermDash(
            refresh_rate=0.1,
            log_file=log_file,
            status_line=True,
            align_columns=True,
            enable_separators=True,
            separator_style="rule",
            reserve_extra_rows=4,
        )

        # hotkey state
        self._hotkeys_running = False
        self._stop_hotkeys = False
        self._paused = False
        self.quit_requested = False
        self.force_quit_requested = False

    # Convenience property used by orchestrator
    @property
    def paused(self) -> bool:
        return self._paused

    # ---------------- lifecycle ----------------

    def start(self) -> "ScanDashboard":
        self._td.start()
        self._build_layout()
        self._write_status("Keys: z pause/resume | q confirm quit | Q force quit")
        self._hotkeys_running = True
        self._stop_hotkeys = False
        self._spawn_hotkeys_thread()
        return self

    def stop(self):
        self._stop_hotkeys = True
        self._td.stop()

    # ---------------- external API ----------------

    def set_worker_start(self, slot_idx: int, urlfile: Path, urls_total: int):
        key = self._k(slot_idx)
        snap = self._workers[key]
        name = urlfile.stem
        short = (name[:12] + "…") if len(name) > 12 else name
        snap.file_display = f"main:{short}"
        snap.urls_total = max(0, int(urls_total))
        snap.urls_seen = 0
        snap.downloaded = 0
        snap.bad = 0
        snap.state = "working"
        snap.eta_s = None
        self._render_worker(key)

    def set_worker_progress(
        self,
        slot_idx: int,
        urls_seen: int,
        downloaded: int,
        bad: int,
        eta_s: Optional[float],
    ):
        key = self._k(slot_idx)
        snap = self._workers[key]
        snap.urls_seen = max(0, int(urls_seen))
        snap.downloaded = max(0, int(downloaded))
        snap.bad = max(0, int(bad))
        snap.eta_s = eta_s if (eta_s is None or eta_s >= 0) else None
        self._render_worker(key)

    def set_worker_done(self, slot_idx: int):
        key = self._k(slot_idx)
        snap = self._workers[key]
        snap.state = "done"
        self._render_worker(key)

    def increment_progress(self):
        self._progress += 1
        elapsed = max(0.0, time.time() - self._start_ts)
        speed = (self._progress / elapsed) if elapsed > 0 else 0.0
        self._td.update_stat("header", "Time", fmt_hms(elapsed))
        self._td.update_stat("header", "Speed", f"{speed:.1f}")
        self._td.update_stat("header", "Progress", f"{self._progress}/{self.total_files}")
        self._td.update_stat("scan-progress", "files", f"Files {self._progress}/{self.total_files}")

    def set_paused(self, paused: bool):
        self._paused = bool(paused)
        self._write_status("[PAUSE] ON" if self._paused else "[PAUSE] OFF")

    def log(self, msg: str):
        self._write_status(msg)

    # ---------------- internal helpers ----------------

    def _k(self, slot_idx: int) -> str:
        i = max(0, min(self.n_workers - 1, int(slot_idx)))
        return f"scan-{i+1}"

    def _build_layout(self):
        header = Line(
            "header",
            [
                Stat("Time", "00:00:00", prefix="Time "),
                Stat("Speed", "0.0", prefix="| Speed ", unit=" files/s"),
                Stat("Progress", f"0/{self.total_files}", prefix="| "),
            ],
            style="header",
        )
        self._td.add_line("header", header, at_top=True)

        for i in range(self.n_workers):
            name = f"scan-{i+1}"
            line = Line(
                name,
                [
                    Stat("lbl", f"Worker {i+1}"),
                    Stat("file", "", prefix=" | "),
                    Stat("urls", "URLs 0/0", prefix=" | "),
                    Stat("dl", "DL 0", prefix=" | "),
                    Stat("bad", "Bad 0", prefix=" | "),
                    Stat("eta", "--:--:--", prefix=" | ETA "),
                    Stat("state", "idle", prefix=" | "),
                ],
            )
            self._td.add_line(name, line)
            if i < self.n_workers - 1:
                self._td.add_separator()

        self._td.add_separator()
        self._td.add_line(
            "scan-progress",
            Line(
                "scan-progress",
                [
                    Stat("lbl", "Scanning"),
                    Stat("files", f"Files 0/{self.total_files}", prefix=" | "),
                    Stat("workers", f"{self.n_workers} worker(s)", prefix=" | "),
                ],
            ),
        )

    def _render_worker(self, key: str):
        w = self._workers[key]
        self._td.update_stat(key, "file", w.file_display or "")
        self._td.update_stat(key, "urls", f"URLs {w.urls_seen}/{w.urls_total}")
        self._td.update_stat(key, "dl", f"DL {w.downloaded}")
        self._td.update_stat(key, "bad", f"Bad {w.bad}")
        self._td.update_stat(key, "eta", fmt_hms(w.eta_s) if w.eta_s is not None else "--:--:--")
        self._td.update_stat(key, "state", w.state)

    def _write_status(self, msg: str):
        try:
            self._td.log(msg)
        except Exception:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()

    # ---------- Hotkeys ----------
    def _spawn_hotkeys_thread(self):
        import threading

        def _loop():
            while not self._stop_hotkeys:
                try:
                    ch = sys.stdin.read(1)
                except Exception:
                    break
                if not ch:
                    time.sleep(0.05)
                    continue
                if ch == "z":
                    self.set_paused(!self._paused)  # noqa: E713 (explicit invert)
                elif ch == "q":
                    self._write_status("[STATUS] Quit? press 'y' to confirm, any other key to cancel")
                    try:
                        yn = sys.stdin.read(1)
                    except Exception:
                        yn = "n"
                    if yn.lower() == "y":
                        self.quit_requested = True
                        break
                elif ch == "Q":
                    self.force_quit_requested = True
                    break

        # Python doesn't support ! in expressions; fix the small typo:
        # We'll rebind the function to avoid a syntax error at import time.
        def _fixed_toggle(p):
            self.set_paused(not self._paused)

        # Patch the closure’s call site
        nonlocal_vars = {}
        def _patched_loop():
            while not self._stop_hotkeys:
                try:
                    ch = sys.stdin.read(1)
                except Exception:
                    break
                if not ch:
                    time.sleep(0.05)
                    continue
                if ch == "z":
                    _fixed_toggle(self._paused)
                elif ch == "q":
                    self._write_status("[STATUS] Quit? press 'y' to confirm, any other key to cancel")
                    try:
                        yn = sys.stdin.read(1)
                    except Exception:
                        yn = "n"
                    if yn.lower() == "y":
                        self.quit_requested = True
                        break
                elif ch == "Q":
                    self.force_quit_requested = True
                    break

        t = threading.Thread(target=_patched_loop, name="scan-hotkeys", daemon=True)
        t.start()
