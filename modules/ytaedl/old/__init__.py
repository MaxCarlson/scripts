# ytaedl/__init__.py

from __future__ import annotations
import sys as _sys

__all__ = ["__version__"]
__version__ = "0.6.1"

# Optional helper so `import ytaedl` and `import ytaedl as pkg` always resolve the same module
if "ytaedl" not in _sys.modules:
    _sys.modules["ytaedl"] = _sys.modules[__name__]
