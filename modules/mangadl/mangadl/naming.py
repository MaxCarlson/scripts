from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

TITLE_LIMIT = 200
DIRECTORY_TEMPLATE = f"{{category}}-{{gallery_id}} - {{title[:{TITLE_LIMIT}]}}"
FILENAME_TEMPLATE = "{num:>03}.{extension}"


def gallery_directory_name(metadata: Mapping[str, Any], clean_segment: Callable[[str], str]) -> str:
    """Render the exact directory segment configured for normal downloads."""
    rendered = f"{metadata['category']}-{metadata['gallery_id']} - {str(metadata['title'])[:TITLE_LIMIT]}"
    return clean_segment(rendered)
