"""
gsearch

Durable adaptive grid-search management for discrete parameter optimization.

The package is intentionally generic. It can drive yt-dlp parameter searches,
compiler flag searches, compression setting searches, model hyperparameter
searches, or any benchmark where configurations are discrete dictionaries and
results are recorded as numeric metrics.
"""

from __future__ import annotations

from gsearch.manager import AdaptiveGridOptimizer
from gsearch.manager import AdaptiveGridStore
from gsearch.manager import GridSpec
from gsearch.manager import Trial
from gsearch.manager import config_id
from gsearch.reporting import generate_report

__version__ = "0.1.1"

__all__ = [
    "__version__",
    "AdaptiveGridOptimizer",
    "AdaptiveGridStore",
    "GridSpec",
    "Trial",
    "config_id",
    "generate_report",
]

