"""Keep the optional shared-library extras on their canonical distributions."""
from __future__ import annotations

import tomllib
from pathlib import Path


def test_optional_shared_dependencies_use_namespaced_distributions() -> None:
    metadata = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    optional = metadata["project"]["optional-dependencies"]

    assert "mxc-web-ui-tools>=0.2.0,<0.3" in optional["web"]
    assert "mxc-resource-metrics>=0.3.0,<0.4" in optional["gpu"]
    assert "mxc-web-ui-tools>=0.2.0,<0.3" in optional["all"]
    assert "mxc-resource-metrics>=0.3.0,<0.4" in optional["all"]
    assert not any(
        requirement.lower().startswith(("web-ui-tools", "resource-metrics"))
        for requirements in optional.values()
        for requirement in requirements
    )
