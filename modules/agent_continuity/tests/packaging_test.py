from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def test_terminal_launcher_is_required_and_versions_match_metadata():
    repo_root = Path(__file__).resolve().parents[3]
    agent_metadata = tomllib.loads((repo_root / "modules/agent_continuity/pyproject.toml").read_text())
    terminal_metadata = tomllib.loads((repo_root / "modules/terminal_launcher/pyproject.toml").read_text())
    terminal_init = (repo_root / "modules/terminal_launcher/__init__.py").read_text()

    requirements = [Requirement(value) for value in agent_metadata["project"]["dependencies"]]
    terminal_requirement = next(
        requirement for requirement in requirements
        if canonicalize_name(requirement.name) == "terminal-launcher"
    )
    terminal_version = Version(terminal_metadata["project"]["version"])
    module_version = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', terminal_init, re.MULTILINE)

    assert terminal_version in terminal_requirement.specifier
    assert module_version and Version(module_version.group(1)) == terminal_version
    assert not any("agent-continuity" in dependency for dependency in terminal_metadata["project"]["dependencies"])
