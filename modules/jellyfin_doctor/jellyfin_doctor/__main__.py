"""Module entry point for ``python -m jellyfin_doctor``."""

from __future__ import annotations

from .cli import main

raise SystemExit(main())

