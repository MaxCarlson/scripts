"""Short import name for ytaedl (backward/forward compatible)."""
from __future__ import annotations

import sys as _sys
from importlib import import_module as _import_module

# Load the canonical package, then alias both ways
_pkg = _import_module("ytaedl")
__version__ = getattr(_pkg, "__version__", "0.0.0")

# Ensure anyone importing the long name sees the same module object
_sys.modules["ytaedl"] = _pkg
# And the short name refers to that same object
_sys.modules["ytaedl"] = _pkg

# Re-export everything the canonical package exports at top-level
for _name in getattr(_pkg, "__all__", []):
    globals()[_name] = getattr(_pkg, _name)
