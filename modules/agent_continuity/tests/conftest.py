"""Test suite pytest configuration keeping temp roots inside modules/agent_continuity/.pytest_tmp_root."""

from __future__ import annotations

import os
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = MODULE_ROOT / ".pytest_tmp_root"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMPDIR", str(TMP_ROOT))
os.environ.setdefault("TEMP", str(TMP_ROOT))
os.environ.setdefault("TMP", str(TMP_ROOT))
