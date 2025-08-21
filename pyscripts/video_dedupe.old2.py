../../scripts/modules/termdash/__init__.py
```
"""
TermDash: A robust, thread-safe library for creating persistent, multi-line,
in-place terminal dashboards with a co-existing scrolling log region.
"""
from .dashboard import TermDash
from .components import Line, Stat, AggregatedLine
from .utils import format_bytes, fmt_hms, bytes_to_mib, clip_ellipsis

__all__ = [
    "TermDash",
    "Line",
    "Stat",
    "AggregatedLine",
    "format_bytes",
    "fmt_hms",
    "bytes_to_mib",
    "clip_ellipsis",
]

```

../../scripts/modules/termdash/components.py
```
#!/usr/bin/env python3
"""
TermDash components: Stat, Line (supports custom separators), AggregatedLine.
"""

import time
from collections.abc import Callable

# ANSI
RESET = "\033[0m"
DEFAULT_COLOR = "0;37"  # white

# Non-printing markers to tag cells that should NOT expand columns
NOEXPAND_L = "\x1e"  # Record Separator
NOEXPAND_R = "\x1f"  # Unit Separator


class Stat:
    """A single named metric rendered inside a Line."""
    def __init__(
        self,
        name,
        value,
        prefix="",
        format_string="{}",
        unit="",
        color="",
        warn_if_stale_s=0,
        *,
        no_expand: bool = False,
        display_width: int | None = None,  # soft width hint for no_expand columns
    ):
        self.name = name
        self.initial_value = value
        self.value = value
        self.prefix = prefix
        self.format_string = format_string
        self.unit = unit
        # color can be a string ("0;32") or a callable(value)->str
        self.color_provider = color if isinstance(color, Callable) else (lambda v, c=color: c)
        self.warn_if_stale_s = warn_if_stale_s
        self.last_updated = time.time()
        self.is_warning_active = False
        self._grace_period_until = 0
        self._last_text = None  # last rendered plain text (for value=None fallback)
        self.no_expand = bool(no_expand)
        self.display_width = display_width if (isinstance(display_width, int) and display_width > 0) else None

    def render(self, logger=None) -> str:
        if self.value is None:
            text = self._last_text or f"{self.prefix}--{self.unit}"
        else:
            try:
                if isinstance(self.value, tuple):
                    formatted = self.format_string.format(*self.value)
                else:
                    formatted = self.format_string.format(self.value)
            except Exception as e:
                if logger:
                    logger.error(
                        f"Stat.render error for '{self.name}': {e} "
                        f"(value={self.value!r}, fmt={self.format_string!r})"
                    )
                formatted = "FMT_ERR"
            text = f"{self.prefix}{formatted}{self.unit}"
            self._last_text = text

        if self.no_expand:
            # Width hint stays invisible, the aligner reads it and strips it.
            hint = f"[W{self.display_width}]" if self.display_width else ""
            text = f"{NOEXPAND_L}{hint}{text}{NOEXPAND_R}"

        color_code = self.color_provider(self.value) or DEFAULT_COLOR
        return f"\033[{color_code}m{text}{RESET}"


class Line:
    """
    A renderable line composed of Stats.

    style:
      - 'default' : normal joined stats
      - 'header'  : bright/cyan
      - 'separator': prints a horizontal rule using sep_pattern (repeated to width)
    """
    def __init__(self, name, stats=None, style='default', sep_pattern: str = "-"):
        self.name = name
        self._stats = {s.name: s for s in (stats or [])}
        self._stat_order = [s.name for s in (stats or [])]
        self.style = style
        self.sep_pattern = sep_pattern or "-"

    def update_stat(self, name, value):
        if name in self._stats:
            st = self._stats[name]
            st.value = value
            st.last_updated = time.time()
            st.is_warning_active = False

    def reset_stat(self, name, grace_period_s=0):
        if name in self._stats:
            st = self._stats[name]
            st.value = st.initial_value
            st.last_updated = time.time()
            st.is_warning_active = False
            if grace_period_s > 0:
                st._grace_period_until = time.time() + grace_period_s

    def render(self, width: int, logger=None) -> str:
        if self.style == 'separator':
            pat = self.sep_pattern or "-"
            # repeat pattern across width; slice exact width
            return (pat * ((width // max(1, len(pat))) + 2))[:width]

        rendered = [self._stats[n].render(logger=logger) for n in self._stat_order]
        # Use a literal '|' between stats so the dashboard aligner sees columns.
        content = " | ".join(rendered)
        if self.style == 'header':
            return f"\033[1;36m{content}{RESET}"
        return content


class AggregatedLine(Line):
    """
    Aggregates numeric stats from a dict of source Line objects.
    Non-numeric values are treated as 0. Aggregation happens during render().
    """
    def __init__(self, name, source_lines, stats=None, style='default', sep_pattern: str = "-"):
        super().__init__(name, stats, style, sep_pattern=sep_pattern)
        self.source_lines = source_lines  # dict[str, Line]

    @staticmethod
    def _to_number(value):
        try:
            if value is None:
                return 0
            if isinstance(value, (int, float)):
                return value
            return float(value)
        except Exception:
            return 0

    def render(self, width, logger=None):
        # recompute each stat as sum of same stat from all source lines
        for stat_name, st in self._stats.items():
            agg = 0
            for src in self.source_lines.values():
                s = src._stats.get(stat_name)
                if s is not None:
                    agg += self._to_number(s.value)
            self.update_stat(stat_name, agg)
        return super().render(width, logger)

```

../../scripts/modules/termdash/dashboard.py
```
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
            visible = len(self._line_order) + (1 if self.has_status_line else 0)
            allowed = max(1, lines - 1)

            self._effective_reserve_rows = max(0, min(self._reserve_extra_rows, allowed - visible))
            dashboard_height = visible + self._effective_reserve_rows

            if dashboard_height > lines:
                self._effective_reserve_rows = max(0, lines - visible)
                dashboard_height = visible + self._effective_reserve_rows

            sys.stdout.write(f"{CLEAR_SCREEN}{MOVE_TO_TOP_LEFT}")
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

```

../../scripts/modules/termdash/utils.py
```
#!/usr/bin/env python3
"""
Utility functions for the TermDash module.
"""

def format_bytes(mib_val):
    """Formats a numeric value in MiB into a human-readable byte string."""
    if mib_val >= 1024:
        return f"{mib_val / 1024:.2f} GiB"
    if mib_val < (1/1024):
        return f"{mib_val * 1024 * 1024:.2f} B"
    if mib_val < 1:
        return f"{mib_val * 1024:.2f} KiB"
    return f"{mib_val:.2f} MiB"

# --- simple formatting / units / clipping ---

def fmt_hms(seconds):
    """Return HH:MM:SS (accepts float or int; None -> '--:--:--')."""
    if seconds is None:
        return "--:--:--"
    s = int(max(0, float(seconds)))
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def bytes_to_mib(n_bytes):
    """Convert bytes -> mebibytes (MiB) as float."""
    try:
        return float(n_bytes) / (1024.0 * 1024.0)
    except Exception:
        return 0.0

def clip_ellipsis(text: str, max_chars: int) -> str:
    """Hard-clip string to <= max_chars, adding a single-character ellipsis if clipped."""
    if max_chars <= 0:
        return text or ""
    s = str(text or "")
    return s if len(s) <= max_chars else s[:max_chars - 1] + "…"

```

../../scripts/modules/termdash/ytdlp_parser.py
```
#!/usr/bin/env python3
"""
Lightweight parser for yt-dlp console output.

Recognized events (returned as dicts; keys present depend on event):

- "meta" (our injected print):
    TDMETA\t<ID>\t<TITLE>
    keys: id, title

- "destination":
    [download] Destination: <full/path/or/title.ext>
    keys: path

- "already":
    [download] <file> has already been downloaded
    [download] File is already downloaded
    [download] ...already...downloaded...
    keys: path (may be "" if not given)

- "resume":
    [download] Resuming download at byte 16777216
    keys: from_byte (int)

- "progress":
    [download]  23.4% of 50.00MiB at 3.21MiB/s ETA 00:16
    [download]  23.4% of ~50.00MiB at 3.21MiB/s ETA 00:16
    keys: percent, total_bytes, downloaded_bytes, speed_Bps, eta_s

- "complete":
    [download] 100% of 1.23GiB in 00:45
    [download] 100%
    keys: none

- "extract" (one per URL before work starts on it):
    [SomethingSite] Extracting URL: https://example/...
    keys: url

- "error":
    ERROR: <message>
    keys: message
"""

from __future__ import annotations
import re
from typing import Dict, Optional

__all__ = [
    "parse_line",
    "parse_meta",
    "parse_destination",
    "parse_already",
    "parse_resume",
    "parse_progress",
    "parse_complete",
    "parse_extract",
    "parse_error",
    "hms_to_seconds",
    "human_to_bytes",
]

# ---------- helpers ----------
_UNIT = {
    "B": 1,
    "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
    "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4,
}

def human_to_bytes(num_str: str, unit_str: str) -> int:
    try:
        n = float((num_str or "").replace(",", ""))
    except Exception:
        return 0
    u = (unit_str or "").upper()
    return int(n * _UNIT.get(u, 1))

def hms_to_seconds(s: str) -> Optional[int]:
    if not s or s == "N/A":
        return None
    parts = s.split(":")
    try:
        parts = [int(p) for p in parts]
    except Exception:
        return None
    if len(parts) == 2:
        m, sec = parts
        return m * 60 + sec
    if len(parts) == 3:
        h, m, sec = parts
        return h * 3600 + m * 60 + sec
    return None

# ---------- regex ----------
_RE_META = re.compile(r'^TDMETA\t(?P<id>[^\t]+)\t(?P<title>.*)\s*$')
_RE_DEST = re.compile(r'^\\[download]\\s+Destination:\\s+(?P<path>.+?)\\s*$')
_RE_ALREADY_1 = re.compile(r'^\\[download]\\s+(?P<path>.+?)\\s+has already been downloaded\\s*$', re.IGNORECASE)
_RE_ALREADY_2 = re.compile(r'^\\[download]\\s+File is already downloaded\\s*$')
_RE_ALREADY_3 = re.compile(r'^\\[download].*already.*downloaded.*$')
_RE_RESUME = re.compile(r'^\\[download]\\s+Resuming download at byte\\s+(?P<byte>\\d+)\\s*$')
_RE_PROGRESS = re.compile(
    r'^\\[download]\\s+'
    r'(?P<pct>\\d{1,3}(?:\\.\\d+)?)%\\s+of\\s+~?(?P<total_num>[\\d\\.,]+)\\s*(?P<total_unit>[KMGT]?i?B)\\s+'
    r'(?:at\\s+(?P<spd_num>[\\d\\.,]+)\\s*(?P<spd_unit>[KMGT]?i?B)/s\\s+)?'
    r'(?:ETA\\s+(?P<eta>(?:\\d{1,2}:)?\\d{2}:\\d{2}|N/A))?\\s*$'
)
_RE_COMPLETE = re.compile(r'^\\[download]\\s+100%.*?(?:\\s+in\\s+(?P<in>(?:\\d{1,2}:)?\\d{2}:\\d{2}))?\\s*$')
_RE_EXTRACT = re.compile(r'^\\[[^\\]]+\]\\s+Extracting URL:\\s+(?P<url>\\S+)\\s*$')
_RE_ERROR = re.compile(r'^\\s*ERROR:\\s*(?P<msg>.+?)\\s*$')

# ---------- parsers ----------
def parse_meta(line: str) -> Optional[Dict]:
    m = _RE_META.match(line)
    if m:
        return {"event": "meta", "id": m.group("id"), "title": m.group("title")}
    return None

def parse_destination(line: str) -> Optional[Dict]:
    m = _RE_DEST.match(line)
    if m:
        return {"event": "destination", "path": m.group("path")}
    return None

def parse_already(line: str) -> Optional[Dict]:
    m = _RE_ALREADY_1.match(line)
    if m:
        return {"event": "already", "path": m.group("path")}
    if _RE_ALREADY_2.match(line):
        return {"event": "already", "path": ""}
    if _RE_ALREADY_3.match(line):
        return {"event": "already", "path": ""}
    return None

def parse_resume(line: str) -> Optional[Dict]:
    m = _RE_RESUME.match(line)
    if m:
        try:
            val = int(m.group("byte"))
        except Exception:
            val = 0
        return {"event": "resume", "from_byte": val}
    return None

def parse_progress(line: str) -> Optional[Dict]:
    m = _RE_PROGRESS.match(line)
    if not m:
        return None
    pct = float(m.group("pct"))
    total_bytes = human_to_bytes(m.group("total_num"), m.group("total_unit"))
    spd_num, spd_unit = m.group("spd_num"), m.group("spd_unit")
    speed_Bps = human_to_bytes(spd_num, spd_unit) if spd_num and spd_unit else 0.0
    eta = hms_to_seconds(m.group("eta")) if m.group("eta") else None
    downloaded_bytes = int(total_bytes * (pct / 100.0)) if total_bytes else None
    return {
        "event": "progress",
        "percent": pct,
        "total_bytes": total_bytes or None,
        "downloaded_bytes": downloaded_bytes,
        "speed_Bps": float(speed_Bps),
        "eta_s": eta if eta is not None else None,
    }

def parse_complete(line: str) -> Optional[Dict]:
    m = _RE_COMPLETE.match(line)
    if m:
        return {"event": "complete"}
    return None

def parse_extract(line: str) -> Optional[Dict]:
    m = _RE_EXTRACT.match(line)
    if m:
        return {"event": "extract", "url": m.group("url")}
    return None

def parse_error(line: str) -> Optional[Dict]:
    m = _RE_ERROR.match(line)
    if m:
        return {"event": "error", "message": m.group("msg")}
    return None

def parse_line(line: str) -> Optional[Dict]:
    # Order matters: meta → destination → already → resume → progress → complete → extract → error
    return (
        parse_meta(line)
        or parse_destination(line)
        or parse_already(line)
        or parse_resume(line)
        or parse_progress(line)
        or parse_complete(line)
        or parse_extract(line)
        or parse_error(line)
    )

```
