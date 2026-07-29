"""Repository-path compatibility shim for the RRBackup package.

The scripts repository may place ``modules`` on ``sys.path``. In that layout,
``modules/rrbackup`` is imported before the installable package directory at
``modules/rrbackup/rrbackup``. Extend this package path explicitly so installed
console entry points and repository-local imports resolve the same package.
"""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

_INNER_PACKAGE = Path(__file__).resolve().parent / "rrbackup"
if _INNER_PACKAGE.is_dir():
    inner_path = str(_INNER_PACKAGE)
    if inner_path not in __path__:
        __path__.append(inner_path)

from .version import __version__

__all__ = ["__version__"]
