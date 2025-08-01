"""
TermDash: A robust, thread-safe library for creating persistent, multi-line,
in-place terminal dashboards with a co-existing scrolling log region.
"""
from .dashboard import TermDash
from .components import Line, Stat
from .utils import format_bytes
