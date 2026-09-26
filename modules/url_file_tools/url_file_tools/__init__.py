"""URL file normalization and merge tools."""

from .core import (
    MergePlan,
    UrlFileError,
    build_merge_plan,
    normalize_mobile_url,
    registered_domain,
)
from .archive import ArchiveEvidence, ArchiveMatchResult, match_archive_urls

__version__ = "1.0.0"

__all__ = [
    "MergePlan",
    "UrlFileError",
    "build_merge_plan",
    "normalize_mobile_url",
    "registered_domain",
    "ArchiveEvidence",
    "ArchiveMatchResult",
    "match_archive_urls",
]
