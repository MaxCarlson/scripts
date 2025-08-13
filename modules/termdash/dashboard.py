#!/usr/bin/env python3
"""
TermDash dashboard — in-place renderer with optional column alignment.
"""

import sys
import os
import time
import threading
import logging
import signal
import re
from contextlib import contextmanager

from .components import Line

# ANSI
CSI = "\x1b["
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"
CLEAR_LINE = f"{CSI}2K"
CLEAR_SCREEN = f"{CSI}2J"
MOVE_TO_TOP_LEFT = f"{CSI}1;1H"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


class TermDash:
    """
    Thread-safe, in-place terminal dashboard.

    New options:
      align_columns: if True, align columns split by `column_sep` across all lines.
      column_sep:    a string used as the visual separator between columns (default '|').
      min_col_pad:   spaces placed on both sides of column_sep.
      max_col_width: optional int. If set and a column exceeds it, it will be left-truncated
                     keeping the rightmost characters (with a leading '…').
    """
    def __init__(
        self,
        refresh_rate=0.1,
        log_file=None,
        status_line=True,
        debug_locks=False,
        debug_rendering=False,
        *,
        align_columns=False,
        column_sep="|",
        min_col_pad=2,
        max_col_width=None,
    ):
        self._lock = threading.RLock()
        self._render_thread = None
        self._running = False
        self._refresh_rate = refresh_rate
        self._resize_pending = threading.Event()
        self.has_status_line = status_line
        self._debug_locks = debug_locks
        self._debug_rendering = debug_rendering

        self.align_columns = bool(align_columns)
        self.column_sep = str(column_sep)
        self.min_col_pad = int(min_col_pad)
        self.max_col_width = int(max_col_width) if (max_col_width is not None and max_col_width > 0) else None

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
        """Add a line; if at_top=True, insert at the top."""
        with self._lock_context("add_line"):
            self._lines[name] = line_obj
            if name in self._line_order:
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

    def log(self, message, level='info'):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message)
        with self._lock_context("log_screen"):
            try:
                cols, lines = os.get_terminal_size()
                sys.stdout.write(f"{CSI}s{CSI}{lines};1H\r{CLEAR_LINE}{message}\n{CSI}u")
                sys.stdout.flush()
            except OSError:
                pass

    def _setup_screen(self):
        try:
            cols, lines = os.get_terminal_size()
            dashboard_height = len(self._line_order) + (1 if self.has_status_line else 0)
            if dashboard_height >= max(1, lines - 1):
                self._running = False
                sys.stdout.write(SHOW_CURSOR)
                raise RuntimeError(
                    f"Dashboard too tall for terminal: height {dashboard_height}, terminal {lines}."
                )
            sys.stdout.write(f"{CLEAR_SCREEN}{MOVE_TO_TOP_LEFT}")
            top_scroll = dashboard_height + 1
            if top_scroll < lines:
                sys.stdout.write(f"{CSI}{top_scroll};{lines}r")
            sys.stdout.write(MOVE_TO_TOP_LEFT)
            sys.stdout.flush()
        except OSError:
            pass

    # --- alignment helpers ---
    def _align_rendered_lines(self, rendered_lines: list[str], cols: int) -> list[str]:
        """Return new list with columns aligned and optionally truncated."""
        sep = self.column_sep
        pad = " " * self.min_col_pad
        joiner = f"{pad}{sep}{pad}"

        def strip_ansi(s: str) -> str:
            return _strip_ansi(s)

        # Split and collect max widths
        split_lines = []
        max_per_col = []
        for s in rendered_lines:
            if s is None:
                split_lines.append(None)
                continue
            plain = strip_ansi(s)
            # if it's a separator line (repeated single chars), pass through
            if plain and len(set(plain.strip())) == 1:
                split_lines.append(None)
                continue
            cols_parts = [p.strip() for p in plain.split(sep)]
            split_lines.append(cols_parts)
            if len(cols_parts) > len(max_per_col):
                max_per_col.extend([0] * (len(cols_parts) - len(max_per_col)))
            for i, part in enumerate(cols_parts):
                w = len(part)
                if self.max_col_width is not None:
                    w = min(w, self.max_col_width)
                if w > max_per_col[i]:
                    max_per_col[i] = w

        # Compose aligned
        aligned = []
        for original, parts in zip(rendered_lines, split_lines):
            if parts is None:
                aligned.append((original or "")[:cols])
                continue
            fixed_cols = []
            for i, text in enumerate(parts):
                width = max_per_col[i]
                # left-truncate so the RIGHT side (values) survive
                if len(text) > width:
                    fixed = "…" if width <= 1 else ("…" + text[-(width - 1):])
                else:
                    fixed = text.ljust(width)
                fixed_cols.append(fixed)
            aligned_line = joiner.join(fixed_cols)
            aligned.append(aligned_line[:cols])
        return aligned

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

                # First render all lines to strings
                raw_lines = []
                for name in self._line_order:
                    line = self._lines[name]
                    raw = line.render(cols, logger=self.logger if self._debug_rendering else None)
                    raw_lines.append(raw)

                # Optionally align columns
                final_lines = self._align_rendered_lines(raw_lines, cols) if self.align_columns \
                              else [s[:cols] for s in raw_lines]

                # Emit all lines at absolute positions
                out = []
                for i, text in enumerate(final_lines, start=1):
                    out.append(f"{CSI}{i};1H{CLEAR_LINE}{text}")
                if self.has_status_line:
                    status_line_num = len(final_lines) + 1
                    out.append(f"{CSI}{status_line_num};1H{CLEAR_LINE}")
                sys.stdout.write("".join(out))
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
