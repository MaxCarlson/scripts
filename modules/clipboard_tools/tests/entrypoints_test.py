from __future__ import annotations

import os
import sys
from pathlib import Path


def _venv_scripts_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    if os.name == "nt":
        return root / ".venv" / "Scripts"
    return root / ".venv" / "bin"


def test_executables_exist():
    scripts_dir = _venv_scripts_dir()
    names = ["c2c", "rwc", "pclip", "otcw"]
    missing = [n for n in names if not (scripts_dir / f"{n}.exe" if os.name == "nt" else scripts_dir / n).exists()]
    assert not missing, f"Missing executables in venv: {missing}"


def test_bin_proxies_point_to_venv():
    bin_dir = Path(__file__).resolve().parents[3] / "bin"
    proxy = bin_dir / ("c2c.cmd" if os.name == "nt" else "c2c")
    assert proxy.exists(), "c2c proxy missing in bin/"
    content = proxy.read_text(encoding="utf-8")
    assert ".venv" in content, "bin proxy should forward to repo .venv"
