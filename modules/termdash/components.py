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
