#!/usr/bin/env python3
"""
The main Dashboard class for the TermDash module.
"""

import sys
import os
import time
import threading
import logging
import signal
from contextlib import contextmanager

from .components import Line, Stat

# ANSI escape codes
CSI = "\x1b["
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"
CLEAR_LINE = f"{CSI}2K"
CLEAR_SCREEN = f"{CSI}2J"
MOVE_TO_TOP_LEFT = f"{CSI}1;1H"


class TermDash:
    """
    A thread-safe, in-place terminal dashboard with a scrolling log region.
    Manages the entire screen, redrawing on a schedule and handling terminal resizes.
    """
    def __init__(
        self,
        refresh_rate=0.1,
        log_file=None,
        status_line=True,
        debug_locks=False,
        debug_rendering=False
    ):
        self._lock = threading.RLock()
        self._render_thread = None
        self._running = False
        self._refresh_rate = refresh_rate
        self._resize_pending = threading.Event()
        self.has_status_line = status_line
        self._debug_locks = debug_locks
        self._debug_rendering = debug_rendering

        self._lines = {}
        self._line_order = []

        self.logger = None
        if log_file:
            self.logger = logging.getLogger('TermDashLogger')
            log_level = logging.DEBUG if (self._debug_locks or self._debug_rendering) else logging.INFO
            self.logger.setLevel(log_level)
            if not self.logger.handlers:
                fh = logging.FileHandler(log_file, mode='w')
                formatter = logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
                fh.setFormatter(formatter)
                self.logger.addHandler(fh)

    @contextmanager
    def _lock_context(self, name: str):
        """Context manager for the RLock with optional verbose logging."""
        if self._debug_locks and self.logger:
            self.logger.debug(f"LOCK: Waiting for '{name}'")
        self._lock.acquire()
        try:
            if self._debug_locks and self.logger:
                self.logger.debug(f"LOCK: Acquired '{name}'")
            yield
        finally:
            if self._debug_locks and self.logger:
                self.logger.debug(f"LOCK: Releasing '{name}'")
            self._lock.release()

    def _handle_resize(self, signum, frame):
        self._resize_pending.set()

    def add_line(self, name, line_obj, at_top: bool = False):
        """
        Register a line for rendering.

        Parameters
        ----------
        name : str
            Unique name for the line.
        line_obj : Line
            The line instance to render.
        at_top : bool
            If True, insert this line at the very top of the dashboard.
            If False (default), append at the bottom (previous behavior).
        """
        with self._lock_context("add_line"):
            self._lines[name] = line_obj
            if name in self._line_order:
                # keep order stable if re-adding
                return
            if at_top:
                self._line_order.insert(0, name)
            else:
                self._line_order.append(name)

    def update_stat(self, line_name, stat_name, value):
        with self._lock_context("update_stat"):
            if line_name in self._lines:
                self._lines[line_name].update_stat(stat_name, value)

    def reset_stat(self, line_name, stat_name, grace_period_s=0):
        with self._lock_context("reset_stat"):
            if line_name in self._lines:
                self._lines[line_name].reset_stat(stat_name, grace_period_s)

    def update_text(self, line_name, text):
        with self._lock_context("update_text"):
            if line_name in self._lines and self._lines[line_name]._stat_order:
                stat_name = self._lines[line_name]._stat_order[0]
                self._lines[line_name].update_stat(stat_name, text)

    def log(self, message, level='info'):
        # Optional scrolling-log helper; not used by the main script during rendering.
        if self.logger:
            log_func = getattr(self.logger, level, self.logger.info)
            log_func(message)

        if level in ['info', 'warning', 'error']:
            with self._lock_context("log_screen"):
                try:
                    cols, lines = os.get_terminal_size()
                    # Save cursor, move to the very last line, print, and restore.
                    sys.stdout.write(f"{CSI}s{CSI}{lines};1H\r{CLEAR_LINE}{message}\n{CSI}u")
                    sys.stdout.flush()
                except OSError:
                    pass

    def _setup_screen(self):
        try:
            cols, lines = os.get_terminal_size()
            dashboard_height = len(self._line_order) + (1 if self.has_status_line else 0)
            # Require at least 1 free line below for safety (avoid zero-height scroll region).
            if dashboard_height >= max(1, lines - 1):
                self._running = False
                sys.stdout.write(SHOW_CURSOR)
                raise RuntimeError(
                    f"Dashboard too tall for terminal: height {dashboard_height}, terminal {lines}."
                )

            sys.stdout.write(f"{CLEAR_SCREEN}{MOVE_TO_TOP_LEFT}")
            # Set the scroll region to be below the dashboard area
            top_scroll = dashboard_height + 1
            if top_scroll < lines:
                sys.stdout.write(f"{CSI}{top_scroll};{lines}r")
            sys.stdout.write(MOVE_TO_TOP_LEFT)
            sys.stdout.flush()
        except OSError:
            pass

    def _render_loop(self):
        while self._running:
            if self._resize_pending.is_set():
                with self._lock_context("render_resize"):
                    self._setup_screen()
                    self._resize_pending.clear()

            with self._lock_context("render_loop"):
                try:
                    cols, _ = os.get_terminal_size()
                except OSError:
                    cols, _ = 80, 24

                output_buffer = []
                render_logger = self.logger if self._debug_rendering else None

                # Draw each main content line with explicit, absolute cursor positioning.
                for i, name in enumerate(self._line_order):
                    line_num = i + 1  # Terminal rows are 1-indexed
                    move_cursor = f"{CSI}{line_num};1H"
                    rendered_line = self._lines[name].render(cols, logger=render_logger)
                    output_buffer.append(f"{move_cursor}{CLEAR_LINE}{rendered_line[:cols]}")

                # Draw the status line with explicit, absolute cursor positioning.
                if self.has_status_line:
                    status_line_num = len(self._line_order) + 1
                    move_cursor = f"{CSI}{status_line_num};1H"

                    stale_stats_names = []
                    now = time.time()
                    for line in self._lines.values():
                        for stat in line._stats.values():
                            if stat.warn_if_stale_s > 0:
                                is_stale = (now - stat.last_updated) > stat.warn_if_stale_s
                                is_in_grace = now < stat._grace_period_until
                                if is_stale and not is_in_grace:
                                    stale_stats_names.append(f"{line.name}.{stat.name}")

                    status_text = ""
                    if stale_stats_names:
                        status_text = f"\033[0;33mWARNING: Stale data for {', '.join(stale_stats_names)}\033[0m"

                    output_buffer.append(f"{move_cursor}{CLEAR_LINE}{status_text[:cols]}")

                # Write the entire buffer in a single, atomic call to prevent flicker and scrolling.
                sys.stdout.write("".join(output_buffer))
                sys.stdout.flush()

            time.sleep(self._refresh_rate)

    def __enter__(self):
        sig = getattr(signal, "SIGWINCH", None)
        if sig is not None:
            try:
                self.original_sigwinch_handler = signal.getsignal(sig)
                signal.signal(sig, self._handle_resize)
            except Exception:
                self.original_sigwinch_handler = None
        else:
            self.original_sigwinch_handler = None

        sys.stdout.write(HIDE_CURSOR)
        self._setup_screen()

        self._running = True
        self._render_thread = threading.Thread(target=self._render_loop, daemon=True)
        self._render_thread.start()
        if self.logger:
            self.log("Dashboard started.", level='info')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._running = False
        if self._render_thread:
            self._render_thread.join(timeout=1)

        sig = getattr(signal, "SIGWINCH", None)
        if sig is not None and getattr(self, "original_sigwinch_handler", None) is not None:
            try:
                signal.signal(sig, self.original_sigwinch_handler)
            except Exception:
                pass

        try:
            _, lines = os.get_terminal_size()
            # Reset scroll region to be the entire terminal
            sys.stdout.write(f"{CSI}1;{lines}r")
            sys.stdout.write(f"{CSI}{lines};1H")
            sys.stdout.write(CLEAR_SCREEN)
            sys.stdout.write(MOVE_TO_TOP_LEFT)
            sys.stdout.write(SHOW_CURSOR)
            sys.stdout.flush()
        except OSError:
            pass

        if self.logger:
            if exc_type and exc_type is not KeyboardInterrupt:
                self.log(f"Dashboard exited with exception: {exc_val}", level='error')
            self.log("Dashboard stopped.", level='info')
