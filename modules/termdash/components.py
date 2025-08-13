#!/usr/bin/env python3
"""
Components for the TermDash module (Line, Stat, AggregatedLine).
"""

import time
from collections.abc import Callable

# ANSI escape sequences
RESET = "\033[0m"
DEFAULT_COLOR = "0;37"  # white


class Stat:
    """Represents a single, named piece of data within a Line."""
    def __init__(
        self,
        name,
        value,
        prefix="",
        format_string="{}",
        unit="",
        color="",
        warn_if_stale_s=0
    ):
        self.name = name
        self.initial_value = value
        self.value = value
        self.prefix = prefix
        self.format_string = format_string
        self.unit = unit
        # color_provider returns an ANSI code string; default to literal or callback
        self.color_provider = color if isinstance(color, Callable) else (lambda v, c=color: c)
        self.warn_if_stale_s = warn_if_stale_s
        self.last_updated = time.time()
        self.is_warning_active = False
        self._grace_period_until = 0
        # holds the last fully rendered "prefix+value+unit" text
        self._last_text = None

    def render(self, logger=None):
        if logger:
            logger.debug(
                f"DEBUG: Stat Name: {self.name}, Value: {self.value}, "
                f"Format String: {self.format_string}, Type of Value: {type(self.value)}"
            )

        # Decide which text to show:
        if self.value is None:
            # use last-known text if available, else show placeholder
            text = self._last_text or f"{self.prefix}--{self.unit}"
        else:
            # format the current value
            try:
                if isinstance(self.value, tuple):
                    formatted = self.format_string.format(*self.value)
                else:
                    formatted = self.format_string.format(self.value)
            except Exception as e:
                if logger:
                    logger.error(f"ERROR in Stat.render() for stat '{self.name}':")
                    logger.error(f"  Value: {self.value} (type: {type(self.value)})")
                    logger.error(f"  Format String: '{self.format_string}'")
                    logger.error(f"  Error: {e}")
                formatted = "FMT_ERR"
            text = f"{self.prefix}{formatted}{self.unit}"
            # remember for later
            self._last_text = text

        # Determine color code (fallback to DEFAULT_COLOR)
        color_code = self.color_provider(self.value) or DEFAULT_COLOR

        # Wrap everything in start/reset so no bleed
        rendered = f"\033[{color_code}m{text}{RESET}"

        if logger:
            logger.debug(f"Rendering stat '{self.name}': {repr(rendered)}")

        return rendered


class Line:
    """Represents one line in the dashboard, containing one or more Stat objects."""
    def __init__(self, name, stats=None, style='default'):
        self.name = name
        self._stats = {s.name: s for s in (stats or [])}
        self._stat_order = [s.name for s in (stats or [])]
        self.style = style

    def update_stat(self, name, value):
        """Updates a specific stat within this line."""
        if name in self._stats:
            stat = self._stats[name]
            stat.value = value
            stat.last_updated = time.time()
            stat.is_warning_active = False

    def reset_stat(self, name, grace_period_s=0):
        """Resets a stat to its initial value, with optional grace period."""
        if name in self._stats:
            stat = self._stats[name]
            stat.value = stat.initial_value
            stat.last_updated = time.time()
            stat.is_warning_active = False
            if grace_period_s > 0:
                stat._grace_period_until = time.time() + grace_period_s

    def render(self, width, logger=None):
        """Renders the entire line by rendering and joining its stats."""
        rendered = []
        for n in self._stat_order:
            if logger:
                logger.debug(f"DEBUG: Line '{self.name}' rendering Stat: {n}")
            rendered.append(self._stats[n].render(logger=logger))
        content = " ".join(rendered)
        if self.style == 'separator':
            return "-" * width
        if self.style == 'header':
            return f"\033[1;36m{content}{RESET}"
        return content


class AggregatedLine(Line):
    """
    A special Line that calculates its stats by aggregating from other lines.
    This aggregation is performed safely during the render call.
    """
    def __init__(self, name, source_lines, stats=None, style='default'):
        super().__init__(name, stats, style)
        self.source_lines = source_lines

    @staticmethod
    def _to_number(value):
        """Coerce value to a number for aggregation; non-numerics/None => 0."""
        try:
            if value is None:
                return 0
            if isinstance(value, (int, float)):
                return value
            # Try to parse strings that look like numbers
            return float(value)
        except Exception:
            return 0

    def render(self, width, logger=None):
        """
        Overrides the default render to first aggregate data from source lines
        and then render itself. Only numeric values are summed; others are ignored.
        """
        for stat_name in self._stats:
            aggregated_value = 0
            for source_line in self.source_lines.values():
                src_stat = source_line._stats.get(stat_name)
                if src_stat is not None:
                    aggregated_value += self._to_number(src_stat.value)
            self.update_stat(stat_name, aggregated_value)

        return super().render(width, logger)
