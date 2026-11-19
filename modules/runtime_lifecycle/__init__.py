"""Package shim so PYTHONPATH=<repo>/modules resolves nested runtime_lifecycle."""

from __future__ import annotations

from pathlib import Path as _Path

_PKG_DIR = _Path(__file__).resolve().parent / "runtime_lifecycle"
__path__ = [str(_PKG_DIR)]
__file__ = str(_PKG_DIR / "__init__.py")
exec(compile((_PKG_DIR / "__init__.py").read_text(encoding="utf-8"), __file__, "exec"))
