"""Expose the Kavita library when the repository's ``modules`` folder is on ``sys.path``.

The reusable package lives in the nested ``kavita`` directory. This project-root
shim prevents the outer ``modules/kavita`` directory from being imported as an
empty namespace package by sibling modules such as MangaDL.
"""

from .kavita import (
    Assignment,
    KavitaClient,
    KavitaConfig,
    KavitaError,
    PendingAssignmentStore,
    match_series_by_path,
    normalize_kavita_path,
    parse_path_maps,
)
from .kavita import __version__

__all__ = [
    "Assignment",
    "KavitaClient",
    "KavitaConfig",
    "KavitaError",
    "PendingAssignmentStore",
    "__version__",
    "match_series_by_path",
    "normalize_kavita_path",
    "parse_path_maps",
]
