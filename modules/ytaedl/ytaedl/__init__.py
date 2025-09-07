# Compatibility shim + version surfacing
from __future__ import annotations

import sys as _sys

__all__ = ["__version__"]

# Bump as requested
__version__ = "0.6.1"

# Provide a friendly alias so `import ytaedl` points here too (and vice versa)
# If the short name gets imported first, it can reassign ytaedl as well.
if "ytaedl" not in _sys.modules:
    _sys.modules["ytaedl"] = _sys.modules[__name__]
