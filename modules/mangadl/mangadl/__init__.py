"""Concurrent manga/gallery download manager."""

__version__ = "1.37.0"

from .library_index import (
    LibraryFolder,
    backfill_source_indexes,
    read_source_manifest,
    resolve_url_folders,
    scan_library,
    write_source_manifest,
)

__all__ = [
    "LibraryFolder",
    "backfill_source_indexes",
    "__version__",
    "read_source_manifest",
    "resolve_url_folders",
    "scan_library",
    "write_source_manifest",
]
