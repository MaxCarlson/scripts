"""Repository-path compatibility shim for the nested URL file tools package.

The scripts repository adds ``modules/`` to ``sys.path``. Extend this package's
search path so editable installs and direct repository execution resolve the
implementation directory consistently.
"""

from pathlib import Path

_IMPLEMENTATION = Path(__file__).parent / "url_file_tools"
if str(_IMPLEMENTATION) not in __path__:
    __path__.append(str(_IMPLEMENTATION))

from .archive import ArchiveEvidence, ArchiveMatchResult, match_archive_urls  # noqa: E402
from .core import MergePlan, UrlFileError, build_merge_plan, normalize_mobile_url, registered_domain  # noqa: E402

__version__ = "1.0.0"

__all__ = [
    "ArchiveEvidence",
    "ArchiveMatchResult",
    "MergePlan",
    "UrlFileError",
    "build_merge_plan",
    "match_archive_urls",
    "normalize_mobile_url",
    "registered_domain",
]
