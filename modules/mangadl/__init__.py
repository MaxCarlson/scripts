"""Repository-path compatibility shim for the nested mangadl package.

The scripts repository adds ``modules/`` to ``sys.path``. Extend this package's
search path so editable installs and direct repository execution resolve the
implementation directory consistently.
"""

from pathlib import Path

_IMPLEMENTATION = Path(__file__).parent / "mangadl"
if str(_IMPLEMENTATION) not in __path__:
    __path__.append(str(_IMPLEMENTATION))

__version__ = "1.14.1"
