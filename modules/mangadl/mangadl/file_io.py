"""Bounded replacement retry for briefly locked Windows control/report files."""
from __future__ import annotations

import os
import time
from pathlib import Path


def replace_file(source: str | Path, target: str | Path) -> None:
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))
