# termdash/dashboard.py
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
WIDTH_HINT_RE = re.compile(r"\[W(\d{1,4})\]")  # e.g., [W60]


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


def _strip_markers_and_hints(s: str) -> str:
    """Remove NOEXPAND markers and embedded [WNN] width hints."""
    if not s:
        return ""
    s = s.replace(NOEXPAND_L, "").replace(NOEXPAND_R, "")
    s = WIDTH_HINT_RE.sub("", s)
    return s


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
        clear_screen: bool = False,
        log_to_screen: bool = True,
        log_region_start_row: int = 0,
        log_region_end_row: int = 0,
    ):
        self._lock = threading.RLock()
        self._render_thread = None
        self._running = False
        self._refresh_rate = refresh_rate
        self._resize_pending = threading.Event()
        self.has_status_line = status_line
        self._debug_locks = debug_locks
        self._debug_rendering = debug_rendering
        self.clear_screen = clear_screen
        self.log_to_screen = log_to_screen
        self.log_region_start_row = log_region_start_row
        self.log_region_end_row = log_region_end_row
        self._log_line_no = 0

        self.align_columns = bool(align_columns)
        self.column_sep = str(column_sep)
        self.min_col_pad = int(min_col_pad)
        self.max_col_width = int(max_col_width) if (max_col_width is not None and max_col_width > 0) else None
        self._reserve_extra_rows = max(0, int(reserve_extra_rows))
        self._effective_reserve_rows = self._reserve_extra_rows
        self.warning_issued = False

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
        """Safe read of a stat’s current value (or None)."""
        with self._lock_context("read_stat"):
            ln = self._lines.get(line_name)
            if not ln:
                return None
            st = getattr(ln, "_stats", {}).get(stat_name)
            return None if st is None else st.value

    # Aggregation helpers
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
        if not self.log_to_screen:
            return
        with self._lock_context("log_screen"):
            try:
                cols, lines = os.get_terminal_size()
                # Save cursor position
                sys.stdout.write(f"{CSI}s")
                
                # Move cursor to the log region
                if self.log_region_start_row > 0 and self.log_region_end_row > self.log_region_start_row:
                    # Move to the bottom of the log region
                    sys.stdout.write(f"{CSI}{self.log_region_end_row};1H")
                    # Scroll up one line
                    sys.stdout.write(f"{CSI}L") # Insert one line
                    # Move to the newly inserted line
                    sys.stdout.write(f"{CSI}{self.log_region_end_row};1H")
                else:
                    # Move to the bottom of the screen
                    sys.stdout.write(f"{CSI}{lines};1H")
                    # Clear the current line
                    sys.stdout.write(CLEAR_LINE)

                sys.stdout.write(f"{message}")
                
                # Restore cursor position
                sys.stdout.write(f"{CSI}u")
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
            visible = len(self._line_order) + (1 if self.has_status_line else 0)
            allowed = max(1, lines - 1)

            self._effective_reserve_rows = max(0, min(self._reserve_extra_rows, allowed - visible))
            dashboard_height = visible + self._effective_reserve_rows

            if dashboard_height > lines:
                self._effective_reserve_rows = max(0, lines - visible)
                dashboard_height = visible + self._effective_reserve_rows

            if self.clear_screen:
                sys.stdout.write(f"{CLEAR_SCREEN}{MOVE_TO_TOP_LEFT}")
            else:
                # Set scrolling region
                if self.log_region_start_row > 0 and self.log_region_end_row > self.log_region_start_row:
                    sys.stdout.write(f"{CSI}{self.log_region_start_row};{self.log_region_end_row}r")
                sys.stdout.write(MOVE_TO_TOP_LEFT)

            top_scroll = min(lines, dashboard_height + 1)
            if top_scroll < lines:
                sys.stdout.write(f"{CSI}{top_scroll};{lines}r")
            sys.stdout.write(MOVE_TO_TOP_LEFT)
            sys.stdout.flush()
        except OSError:
            pass

    def _align_rendered_lines(self, rendered_lines: list[str], cols: int) -> list[str]:
        """
        Align columns split by self.column_sep across all lines.
        - Measurements ignore ANSI codes and NOEXPAND markers, and trim spaces.
        - NOEXPAND cells never contribute to global widths.
        - NOEXPAND width = min(width_hint or (max_col_width or 40), global_width_if_present)
        - Every line is padded to the global column count, so the vertical separators line up.
        - Cells longer than their width are hard-clipped with a single-character ellipsis.
        """
        sep = self.column_sep
        pad = " " * self.min_col_pad
        joiner = f"{pad}{sep}{pad}"

        # 1) Parse each line into columns
        lines_data: list[Optional[list[tuple[str, str]]]] = []
        for s in rendered_lines:
            if s is None:
                lines_data.append(None)
                continue

            # Separator (rule) line detection
            plain_for_check = _strip_ansi(s)
            if plain_for_check and len(set(plain_for_check.replace(" ", ""))) == 1:
                lines_data.append(None)
                continue

            raw_parts = s.split(sep)
            parts: list[tuple[str, str]] = []
            for p in raw_parts:
                plain = _strip_markers_and_hints(_strip_ansi(p)).strip()
                parts.append((p, plain))
            lines_data.append(parts)

        # 2) Compute global grid width for expandable columns
        num_cols = 0
        for line in lines_data:
            if line:
                num_cols = max(num_cols, len(line))

        max_widths = [0] * num_cols
        for line in lines_data:
            if not line:
                continue
            for i, (raw, plain) in enumerate(line):
                if NOEXPAND_L in raw:
                    continue
                max_widths[i] = max(max_widths[i], len(plain))

        if self.max_col_width:
            max_widths = [min(w, self.max_col_width) for w in max_widths]

        # 3) Render each line against the global grid
        final_lines: list[str] = []
        for idx, line_data in enumerate(lines_data):
            if line_data is None:
                final_lines.append((rendered_lines[idx] or "")[:cols])
                continue

            # pad missing columns so all lines have the same number of separators
            if len(line_data) < num_cols:
                line_data = line_data + [("", "")] * (num_cols - len(line_data))

            aligned_parts = []
            for j, (raw, plain) in enumerate(line_data):
                is_no_expand = (NOEXPAND_L in raw)

                # read width hint (if any)
                width_hint = None
                if is_no_expand:
                    m = WIDTH_HINT_RE.search(raw)
                    if m:
                        try:
                            width_hint = max(1, int(m.group(1)))
                        except Exception:
                            width_hint = None

                # global width for this column from expandable cells (may be 0)
                global_w = max_widths[j] if j < len(max_widths) else 0

                if is_no_expand:
                    base = width_hint if width_hint is not None else (self.max_col_width if self.max_col_width is not None else 40)
                    width = min(base, global_w) if global_w > 0 else base
                else:
                    width = global_w

                # Hard-clip w/ ellipsis if needed
                if width > 0 and len(plain) > width:
                    if not self.warning_issued:
                        self.log("WARNING: columns truncated. Consider increasing terminal width.", level='warning')
                        self.warning_issued = True
                    visible = plain[: max(1, width - 1)] + "…"
                else:
                    visible = plain
                padded = visible.ljust(max(width, 0))

                # Preserve leading ANSI prefix (color), reset at end
                mansi = _ANSI_PREFIX_RE.match(raw)
                ansi_prefix = mansi.group(0) if mansi else ""
                cell = f"{ansi_prefix}{padded}\x1b[0m" if ansi_prefix else padded
                aligned_parts.append(cell)

            line_text = joiner.join(aligned_parts)[:cols]
            if self._debug_rendering and self.logger:
                dbg_parts = [(p[1], 'noexp' if NOEXPAND_L in p[0] else 'exp') for p in line_data]
                self.logger.debug(f"ALIGN parts={dbg_parts}")
                self.logger.debug(f"ALIGN widths={max_widths} -> line='{_strip_ansi(line_text)}'")
            final_lines.append(line_text)

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

                # Optionally align columns
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

    # --- Context manager (existing) ---
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
            sys.stdout.write(f"{CSI}1;{lines}r") # Reset scrolling region
            sys.stdout.write(f"{CSI}{lines};1H")
            if self.clear_screen:
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

    # --- NEW convenience: start()/stop() without a with-block ---
    def start(self) -> "TermDash":
        """Begin rendering without using a context manager."""
        self.__enter__()
        return self

    def stop(self):
        """Stop rendering without using a context manager."""
        self.__exit__(None, None, None)
