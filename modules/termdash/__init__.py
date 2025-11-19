"""
TermDash: A robust, thread-safe library for creating persistent, multi-line,
in-place terminal dashboards with a co-existing scrolling log region.
"""
from .dashboard import TermDash
from .components import Line, Stat, AggregatedLine
from .utils import format_bytes, fmt_hms, bytes_to_mib, clip_ellipsis

# New: progress bar, simple board, cmake-like printer
from .progress import ProgressBar
from .simpleboard import SimpleBoard
from .seemake import SeemakePrinter

# Search statistics component (reusable across modules)
from .search_stats import SearchStats

__all__ = [
    "TermDash",
    "Line",
    "Stat",
    "AggregatedLine",
    "ProgressBar",
    "SimpleBoard",
    "SeemakePrinter",
    "SearchStats",
    "format_bytes",
    "fmt_hms",
    "bytes_to_mib",
    "clip_ellipsis",
]
