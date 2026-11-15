#!/usr/bin/env python3
"""Early Python interpreter compatibility guard for H4 qualification tooling.

Keep this module strictly free of Python 3.11+ standard-library imports (such as
``tomllib``) and Python 3.12+ runtime APIs so unsupported interpreters (e.g.,
Python 3.10 or 3.11) fail with a clear, actionable message before extraction,
manifest loading, or guest mutation begins.

Production ``resource-coordinator`` itself continues to declare ``requires-python
>= 3.10`` in ``pyproject.toml``; only H4 release-building and guest-acceptance
tooling requires Python 3.12+ (due to stdlib ``tomllib`` and ``tarfile`` PEP 706
``filter="data"``).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional, Sequence, Tuple

MIN_H4_PYTHON_VERSION: Tuple[int, int] = (3, 12)
MIN_H4_PYTHON_STR = "3.12"
H4_TOOLING_PYTHON_REQUIRES = ">=3.12"
RC_PACKAGE_PYTHON_REQUIRES = ">=3.10"


class PythonCompatibilityError(RuntimeError):
    """Raised when H4 qualification tooling runs on Python older than 3.12."""

    def __init__(self, tool_name: str, actual_version: str) -> None:
        self.code = "unsupported_python_version"
        self.tool_name = tool_name
        self.actual_version = actual_version
        self.required_version = MIN_H4_PYTHON_STR
        message = (
            f"{tool_name} requires Python {MIN_H4_PYTHON_STR}+ (detected {actual_version}; "
            f"H4 release/acceptance tooling uses stdlib tomllib and tarfile filter='data'). "
            f"Production resource-coordinator package remains {RC_PACKAGE_PYTHON_REQUIRES}."
        )
        super().__init__(message)
        self.details: Dict[str, Any] = {
            "tool": tool_name,
            "detected_python": actual_version,
            "required_python": H4_TOOLING_PYTHON_REQUIRES,
            "rc_package_python_requires": RC_PACKAGE_PYTHON_REQUIRES,
        }


def _normalize_version_info(version_info: Optional[Sequence[int]]) -> Tuple[int, int, int]:
    info = sys.version_info if version_info is None else version_info
    major = int(info[0]) if len(info) > 0 else 0
    minor = int(info[1]) if len(info) > 1 else 0
    micro = int(info[2]) if len(info) > 2 else 0
    return (major, minor, micro)


def format_version(version_info: Optional[Sequence[int]] = None) -> str:
    major, minor, micro = _normalize_version_info(version_info)
    return f"{major}.{minor}.{micro}"


def is_supported_python(version_info: Optional[Sequence[int]] = None) -> bool:
    major, minor, _ = _normalize_version_info(version_info)
    return (major, minor) >= MIN_H4_PYTHON_VERSION


def require_supported_python(
    tool_name: str,
    *,
    version_info: Optional[Sequence[int]] = None,
) -> str:
    """Return formatted Python version or raise ``PythonCompatibilityError``."""
    actual = format_version(version_info)
    if not is_supported_python(version_info):
        raise PythonCompatibilityError(tool_name, actual)
    return actual


def enforce_cli_python(
    tool_name: str,
    argv: Optional[Sequence[str]] = None,
    *,
    version_info: Optional[Sequence[int]] = None,
) -> str:
    """Fail closed with exit code 2 before stdlib 3.11+/3.12+ imports run."""
    try:
        return require_supported_python(tool_name, version_info=version_info)
    except PythonCompatibilityError as exc:
        args = list(sys.argv[1:] if argv is None else argv)
        if "-j" in args or "--json" in args:
            payload = {
                "status": "failed",
                "reason_code": exc.code,
                "error": str(exc),
                "details": exc.details,
            }
            print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    enforce_cli_python("h4_qualification", sys.argv[1:])
    print(
        json.dumps(
            {
                "status": "ok",
                "python_version": format_version(),
                "h4_tooling_python_requires": H4_TOOLING_PYTHON_REQUIRES,
                "rc_package_python_requires": RC_PACKAGE_PYTHON_REQUIRES,
            },
            sort_keys=True,
        )
    )
