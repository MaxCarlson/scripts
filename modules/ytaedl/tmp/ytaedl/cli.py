"""Short-name CLI proxy so `python -m ytaedl.cli` works too."""
from __future__ import annotations

from ytaedl.cli import main  # re-export canonical entry

if __name__ == "__main__":
    raise SystemExit(main())
