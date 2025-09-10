"""
TermDash: A robust, thread-safe library for creating persistent, multi-line,
in-place terminal dashboards with a co-existing scrolling log region.
"""
from .dashboard import TermDash
from .components import Line, Stat, AggregatedLine
from .utils import format_bytes, fmt_hms, bytes_to_mib, clip_ellipsis
from .progress import ProgressBar
from .simpleboard import SimpleBoard

__all__ = [
    "TermDash",
    "Line",
    "Stat",
    "AggregatedLine",
    "ProgressBar",
    "SimpleBoard",
    "format_bytes",
    "fmt_hms",
    "bytes_to_mib",
    "clip_ellipsis",
]
