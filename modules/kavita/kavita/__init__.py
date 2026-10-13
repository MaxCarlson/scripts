"""Reusable Kavita HTTP API client and safe series-assignment tools."""

__version__ = "0.1.0"

from .client import KavitaClient, KavitaConfig, KavitaError
from .matching import match_series_by_path, normalize_kavita_path, parse_path_maps
from .pending import Assignment, PendingAssignmentStore

__all__ = [
    "Assignment",
    "KavitaClient",
    "KavitaConfig",
    "KavitaError",
    "PendingAssignmentStore",
    "match_series_by_path",
    "normalize_kavita_path",
    "parse_path_maps",
]
