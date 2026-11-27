from __future__ import annotations

import tomllib
from pathlib import Path


def test_termdash_extra_uses_namespaced_distribution() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    requirements = project["optional-dependencies"]["termdash"]
    assert project["version"] == "0.3.0"
    assert "mxc-termdash>=0.10.0,<0.11" in requirements
    assert "windows-curses>=2.4; sys_platform == 'win32'" in requirements
    assert not any(requirement.lower().startswith("termdash") for requirement in requirements)
