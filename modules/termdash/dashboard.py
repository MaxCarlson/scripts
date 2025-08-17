#!/usr/bin/env python3
"""
TermDash dashboard — in-place renderer with column alignment, separators, and helpers.
"""

import sys
import os
import time
import threading
import logging
import signal
import re
from contextlib import contextmanager
from typing import Iterable, Optional

from .components import Line

# ANSI
CSI = "\x1b["
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"
CLEAR_LINE = f"{CSI}2K"
CLEAR_SCREEN = f"{CSI}2J"
MOVE_TO_TOP_LEFT = f"{CSI}1;1H"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_ANSI_PREFIX_RE = re.compile(r"^(?:\x1b\[[0-9;]*m)+")  # leading color/style codes

# Non-printing markers used by Stat(no_expand=True)
NOEXPAND_L = "\x1e"
NOEXPAND_R = "\x1f"


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


def _strip_markers(s: str) -> str:
    return (s or "").replace(NOEXPAND_L, "").replace(NOEXPAND_R, "")


class TermDash:
    """
    Thread-safe, in-place terminal dashboard.

    Options:
      align_columns: align columns split by `column_sep` across all lines.
      column_sep:    visual separator between columns (default '|').
      min_col_pad:   spaces placed on both sides of column_sep.
      max_col_width: int or None. If set, columns wider than this are truncated
                     (right-side ellipsis).
      enable_separators: when True, `add_separator()` inserts a horizontal rule.
      separator_style: preset name ('rule','dash','dot','tilde','wave','hash').
      separator_custom: custom pattern string (overrides preset).
      reserve_extra_rows: pre-reserve rows below the dashboard (avoid scroll flicker).
    """
    _SEP_PRESETS = {
        "rule": "─",
        "dash": "-",
        "dot": ".",
        "tilde": "~",
        "wave": "~-",
        "hash": "#",
    }

    def __init__(
        self,
        refresh_rate=0.1,
        log_file=None,
        status_line=True,
        debug_locks=False,
        debug_rendering=False,
        *,
        align_columns=True,
        column_sep="|",
        min_col_pad=2,
        max_col_width=None,
        enable_separators=False,
        separator_style: str = "rule",
        separator_custom: str | None = None,
        reserve_extra_rows: int = 6,
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
        self._reserve_extra_rows = max(0, int(reserve_extra_rows))
        self._effective_reserve_rows = self._reserve_extra_rows

        # separators
        self.enable_separators = bool(enable_separators)
        self._separator_pattern = (separator_custom if separator_custom
                                   else self._SEP_PRESETS.get(separator_style, "─"))

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

    # -----------------------------
    # Public API
    # -----------------------------
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

    def add_separator(self):
        """Insert a separator line if separators are enabled."""
        if not self.enable_separators:
            return
        with self._lock_context("add_separator"):
            idx = sum(1 for n in self._line_order if n.startswith("sep"))
            name = f"sep{idx+1}"
            self._lines[name] = Line(name, style="separator", sep_pattern=self._separator_pattern)
            self._line_order.append(name)

    def update_stat(self, line_name, stat_name, value):
        with self._lock_context("update_stat"):
            if line_name in self._lines:
                self._lines[line_name].update_stat(stat_name, value)

    def reset_stat(self, line_name, stat_name, grace_period_s=0):
        with self._lock_context("reset_stat"):
            if line_name in self._lines:
                self._lines[line_name].reset_stat(stat_name, grace_period_s)

    def read_stat(self, line_name, stat_name):
        """NEW: safe read of a stat’s current value (or None)."""
        with self._lock_context("read_stat"):
            ln = self._lines.get(line_name)
            if not ln:
                return None
            st = getattr(ln, "_stats", {}).get(stat_name)
            return None if st is None else st.value

    # Aggregation helpers (for script-level convenience)
    def sum_stats(self, stat_name: str, line_names: Optional[Iterable[str]] = None) -> float:
        with self._lock_context("sum_stats"):
            names = list(line_names) if line_names is not None else list(self._line_order)
            s = 0.0
            for nm in names:
                ln = self._lines.get(nm)
                if not ln: continue
                st = getattr(ln, "_stats", {}).get(stat_name)
                if not st: continue
                try:
                    s += float(st.value)
                except Exception:
                    pass
            return s

    def avg_stats(self, stat_name: str, line_names: Optional[Iterable[str]] = None) -> float:
        with self._lock_context("avg_stats"):
            names = list(line_names) if line_names is not None else list(self._line_order)
            vals = []
            for nm in names:
                ln = self._lines.get(nm)
                if not ln: continue
                st = getattr(ln, "_stats", {}).get(stat_name)
                if not st: continue
                try:
                    vals.append(float(st.value))
                except Exception:
                    pass
            return (sum(vals) / len(vals)) if vals else 0.0

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

    # -----------------------------
    # Rendering
    # -----------------------------
    def _setup_screen(self):
        """Auto-fit reserved rows instead of failing when terminal is snug."""
        try:
            cols, lines = os.get_terminal_size()
            # visible lines = number of dashboard lines (+status if enabled)
            visible = len(self._line_order) + (1 if self.has_status_line else 0)
            allowed = max(1, lines - 1)  # keep at least one free row for scroll region

            # shrink reserve if needed to fit
            self._effective_reserve_rows = max(0, min(self._reserve_extra_rows, allowed - visible))
            dashboard_height = visible + self._effective_reserve_rows

            # If still over (extremely snug), clamp further (no exception)
            if dashboard_height > lines:
                self._effective_reserve_rows = max(0, lines - visible)
                dashboard_height = visible + self._effective_reserve_rows

            sys.stdout.write(f"{CLEAR_SCREEN}{MOVE_TO_TOP_LEFT}")
            top_scroll = min(lines, dashboard_height + 1)
            # only set a custom scroll region when there is room below
            if top_scroll < lines:
                sys.stdout.write(f"{CSI}{top_scroll};{lines}r")
            sys.stdout.write(MOVE_TO_TOP_LEFT)
            sys.stdout.flush()
        except OSError:
            pass

    def _align_rendered_lines(self, rendered_lines: list[str], cols: int) -> list[str]:
        """Return new list with columns aligned and optionally truncated."""
        sep = self.column_sep
        pad = " " * self.min_col_pad
        joiner = f"{pad}{sep}{pad}"

        # 1. Prepare lines
        lines_data = []
        for s in rendered_lines:
            if s is None:
                lines_data.append(None)
                continue
            
            plain_for_check = _strip_ansi(s)
            if plain_for_check and len(set(plain_for_check.strip())) == 1:
                lines_data.append(None) # Separator line
                continue

            raw_parts = [p for p in s.split(sep)]
            plain_parts = [_strip_markers(_strip_ansi(p)) for p in raw_parts]
            lines_data.append(list(zip(raw_parts, plain_parts)))

        # 2. Calculate column widths
        num_cols = 0
        for line in lines_data:
            if line:
                num_cols = max(num_cols, len(line))
        
        max_widths = [0] * num_cols
        for line in lines_data:
            if line:
                for i, (raw, plain) in enumerate(line):
                    if NOEXPAND_L not in raw:
                        max_widths[i] = max(max_widths[i], len(plain))

        if self.max_col_width:
            max_widths = [min(w, self.max_col_width) for w in max_widths]

        # 3. Align and render
        final_lines = []
        for i, line_data in enumerate(lines_data):
            if line_data is None:
                final_lines.append(rendered_lines[i][:cols] if rendered_lines[i] else "")
                continue

            aligned_parts = []
            for j, (raw, plain) in enumerate(line_data):
                is_no_expand = NOEXPAND_L in raw
                
                if is_no_expand:
                    width = self.max_col_width if self.max_col_width is not None else 40
                else:
                    width = max_widths[j]

                print(f"DEBUG ALIGN: raw='{raw!r}', plain='{plain!r}', is_no_expand={is_no_expand}, width={width}, len(plain)={len(plain)}", file=sys.stderr) # ADD THIS LINE

                if len(plain) > width:
                    visible = plain[:width - 1] + "…"
                else:
                    visible = plain
                
                padded = visible.ljust(width)
                
                # Colorize
                m = _ANSI_PREFIX_RE.match(raw)
                prefix = m.group(0) if m else ""
                cell = f"{prefix}{padded}\x1b[0m" if prefix else padded
                aligned_parts.append(cell)

            final_lines.append(joiner.join(aligned_parts)[:cols])
            
        return final_lines

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

                # Render all lines to strings
                raw_lines = []
                for name in self._line_order:
                    line = self._lines[name]
                    raw = line.render(cols, logger=self.logger if self._debug_rendering else None)
                    raw_lines.append(raw)

                # Optionally align columns (ANSI removed for measurements)
                if self.align_columns:
                    final_lines = self._align_rendered_lines(raw_lines, cols)
                else:
                    final_lines = [s[:cols] for s in raw_lines]

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
