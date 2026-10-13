"""Expose the Compresser library when the repository's ``modules`` folder is on ``sys.path``.

The reusable package lives in the nested ``compresser`` directory. This project-root
shim prevents the outer ``modules/compresser`` directory from being imported as an
empty namespace package by sibling modules such as MangaDL.
"""

from pathlib import Path
import sys

_implementation = Path(__file__).parent / "compresser"
__path__.append(str(_implementation))

from .compresser import (  # noqa: E402
    AnalysisCache,
    BatchResult,
    ComparisonRow,
    CompressionEngine,
    CompressionStrategy,
    ImageMetadata,
    ImageResult,
    ScanSummary,
    __version__,
    analyze_collection,
    compare_strategies,
    compress_collection,
    discover_available_codecs,
    inspect_image_file,
    scan_directory,
    select_sample,
)

# Both repository-path and editable imports must resolve to the SAME classes
# and modules. Otherwise a sibling's `compresser.engine` may coexist with the
# nested engine used by public exports, breaking patching and type identity.
_nested_prefix = __name__ + ".compresser."
for _name, _module in tuple(sys.modules.items()):
    if _name.startswith(_nested_prefix):
        sys.modules.setdefault(__name__ + "." + _name[len(_nested_prefix) :], _module)

__all__ = [
    "AnalysisCache",
    "BatchResult",
    "ComparisonRow",
    "CompressionEngine",
    "CompressionStrategy",
    "ImageMetadata",
    "ImageResult",
    "ScanSummary",
    "__version__",
    "analyze_collection",
    "compare_strategies",
    "compress_collection",
    "discover_available_codecs",
    "inspect_image_file",
    "scan_directory",
    "select_sample",
]
