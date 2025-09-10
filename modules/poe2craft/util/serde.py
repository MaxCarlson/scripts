#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import is_dataclass, asdict
from enum import Enum
from typing import Any, Dict, List


def _convert(obj: Any) -> Any:
    """Recursively convert dataclasses and Enums into JSON-serializable forms."""
    if is_dataclass(obj):
        return _convert(asdict(obj))
    if isinstance(obj, Enum):
        # Prefer .value (human string) over enum name
        return obj.value
    if isinstance(obj, dict):
        return {k: _convert(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert(v) for v in obj]
    return obj


def as_serializable(obj: Any) -> Any:
    """
    Public entrypoint: turn nested dataclasses/enums into plain Python data
    that json.dumps can serialize without a custom encoder.
    """
    return _convert(obj)
