"""Ownership and staging policy for independently distributed shared libraries."""
from __future__ import annotations

from scripts_setup.shared_packages import (
    SHARED_DISTRIBUTION_REQUIREMENTS,
    SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION,
    is_shared_distribution,
    is_shared_module_dir,
    is_shared_source_install,
    needs_shared_distribution_replacement,
)


def test_shared_package_registry_uses_qualified_compatible_ranges() -> None:
    assert SHARED_DISTRIBUTION_REQUIREMENTS == {
        "resource-metrics": "resource-metrics>=0.3.0,<0.4",
        "script-logging": "script-logging>=0.1.1,<0.2",
        "web-ui-tools": "web-ui-tools>=0.2.0,<0.3",
        "termdash": "termdash>=0.10.0,<0.11",
        "cross-platform": "cross-platform>=0.9.0,<0.10",
    }
    assert SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION == {
        "resource_metrics": "resource-metrics",
        "script_logging": "script-logging",
        "web_ui_tools": "web-ui-tools",
        "termdash": "termdash",
        "cross_platform": "cross-platform",
    }


def test_shared_source_directory_and_distribution_detection_are_distinct() -> None:
    for module_dir, distribution in SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION.items():
        assert is_shared_module_dir(module_dir)
        assert is_shared_module_dir(f"modules/{module_dir}")
        assert is_shared_distribution(distribution)
    assert not is_shared_module_dir("runmux")
    assert not is_shared_distribution("runmux")


def test_toolkit_source_installs_are_detected_but_wheel_artifacts_are_not() -> None:
    assert is_shared_source_install(
        {
            "url": "file:///C:/Users/example/src/llm-agent-toolkit/modules/script_logging",
            "dir_info": {"editable": False},
        }
    )
    assert is_shared_source_install(
        {
            "url": "file:///C:/Users/example/src/scripts/modules/cross_platform",
            "dir_info": {"editable": True},
        }
    )
    assert not is_shared_source_install(
        {
            "url": "file:///C:/wheelhouse/script_logging-0.1.1-py3-none-any.whl",
            "archive_info": {"hash": "sha256=example"},
        }
    )


def test_toolkit_compatibility_wheel_is_replaced_even_when_version_matches() -> None:
    direct_url = {
        "url": "file:///C:/Users/example/src/llm-agent-toolkit/dist/script_logging-0.1.1-py3-none-any.whl",
        "archive_info": {"hash": "sha256=example"},
    }
    assert not is_shared_source_install(direct_url)
    assert needs_shared_distribution_replacement(direct_url)
    assert not needs_shared_distribution_replacement(
        {
            "url": "file:///C:/Users/example/AppData/Local/scripts-shared-wheelhouse/script_logging-0.1.1-py3-none-any.whl",
            "archive_info": {"hash": "sha256=example"},
        }
    )


def test_installer_replaces_toolkit_source_and_validates_the_environment(monkeypatch, capsys) -> None:
    import json

    from scripts_setup import shared_packages

    calls: list[list[str]] = []
    lookup_count: dict[str, int] = {}

    class Distribution:
        def __init__(self, source: bool = False) -> None:
            self.source = source

        def read_text(self, filename: str) -> str:
            if filename != "direct_url.json":
                return ""
            if self.source:
                return json.dumps({
                    "url": "file:///C:/Users/example/src/llm-agent-toolkit/dist/script_logging-0.1.1-py3-none-any.whl",
                    "archive_info": {"hash": "sha256=example"},
                })
            return json.dumps({
                "url": "file:///C:/wheelhouse/script_logging-0.1.1-py3-none-any.whl",
                "archive_info": {"hash": "sha256=example"},
            })

    def distribution(name: str) -> Distribution:
        lookup_count[name] = lookup_count.get(name, 0) + 1
        return Distribution(source=name == "script-logging" and lookup_count[name] == 1)

    def run(command, **_kwargs):
        calls.append(list(command))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(shared_packages.metadata, "distribution", distribution)
    monkeypatch.setattr(shared_packages.subprocess, "run", run)

    assert shared_packages.ensure_shared_distributions(python="isolated-python")
    assert ["isolated-python", "-I", "-m", "pip", "uninstall", "-y", "script-logging"] in calls
    assert sum(call[4] == "install" for call in calls) == 5
    assert calls[-1] == ["isolated-python", "-I", "-m", "pip", "check"]
    assert "Replacing checkout-local installation of script-logging" in capsys.readouterr().out


def test_installer_dry_run_does_not_call_pip(monkeypatch, capsys) -> None:
    from importlib import metadata
    from scripts_setup import shared_packages

    calls: list[list[str]] = []

    def missing(_name: str):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(shared_packages.metadata, "distribution", missing)
    monkeypatch.setattr(shared_packages.subprocess, "run", lambda command, **_kwargs: calls.append(command))

    assert shared_packages.ensure_shared_distributions(python="isolated-python", dry_run=True)
    assert calls == []
    assert "[DRY RUN] Would install shared distribution" in capsys.readouterr().out
