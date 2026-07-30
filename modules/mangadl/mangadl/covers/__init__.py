from __future__ import annotations

from .cli import configure_parser, run_cli
from .constants import (
    COVER_APPLIED_NAME,
    COVER_PENDING_NAME,
    COVER_STEM,
    METADATA_DIR_NAME,
    SOURCE_MANIFEST_NAME,
)
from .files import identity_without_metadata, snapshot_top_level, tree_stats_without_metadata
from .kavita import KavitaClient, apply_kavita_cover, parse_path_maps
from .matching import collect_url_folder, discover_url_files, match_folder
from .models import CoverResult, FolderMatch, SeriesPageMetadata
from .scraping import fetch_series_metadata, pick_metadata, supports_cover_url
from .service import install_download_cover, process_url_folder
from .storage import write_cover_for_folder

_pick_metadata = pick_metadata

__all__ = [
    "COVER_APPLIED_NAME",
    "COVER_PENDING_NAME",
    "COVER_STEM",
    "METADATA_DIR_NAME",
    "SOURCE_MANIFEST_NAME",
    "CoverResult",
    "FolderMatch",
    "KavitaClient",
    "SeriesPageMetadata",
    "_pick_metadata",
    "apply_kavita_cover",
    "collect_url_folder",
    "configure_parser",
    "discover_url_files",
    "fetch_series_metadata",
    "identity_without_metadata",
    "install_download_cover",
    "match_folder",
    "parse_path_maps",
    "process_url_folder",
    "run_cli",
    "snapshot_top_level",
    "supports_cover_url",
    "tree_stats_without_metadata",
    "write_cover_for_folder",
]
