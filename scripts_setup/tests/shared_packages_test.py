"""Ownership and staging policy for independently distributed shared libraries."""
from __future__ import annotations

from pathlib import Path

from scripts_setup.shared_packages import (
    SHARED_DISTRIBUTION_REQUIREMENTS,
    SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION,
    is_shared_distribution,
    is_shared_module_dir,
    is_shared_source_install,
    needs_shared_distribution_replacement,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_retired_shared_source_directories_are_absent() -> None:
    retired_source_dirs = {"script_logging", "termdash", "cross_platform"}
    assert not any((REPO_ROOT / "modules" / module_dir).exists() for module_dir in retired_source_dirs)
    # resource_metrics remains temporarily for resource_coordinator's pinned H4 bundle builder.
    assert (REPO_ROOT / "modules" / "resource_metrics").is_dir()
    # web_ui_tools remains pending the explicit scripts-ownership review.
    assert (REPO_ROOT / "modules" / "web_ui_tools").is_dir()


def test_validation_targets_do_not_install_retired_shared_source_paths() -> None:
    import json

    manifest = json.loads((REPO_ROOT / "validation-targets.json").read_text(encoding="utf-8"))
    text = json.dumps(manifest)
    assert not any(
        f"modules/{module_dir}" in text
        for module_dir in ("script_logging", "termdash", "cross_platform")
    )


def test_shared_package_registry_uses_qualified_compatible_ranges() -> None:
    assert SHARED_DISTRIBUTION_REQUIREMENTS == {
        "mxc-resource-metrics": "mxc-resource-metrics>=0.3.0,<0.4",
        "mxc-script-logging": "mxc-script-logging>=0.1.1,<0.2",
        "mxc-web-ui-tools": "mxc-web-ui-tools>=0.2.0,<0.3",
        "mxc-termdash": "mxc-termdash>=0.10.0,<0.11",
        "mxc-platform-utils": "mxc-platform-utils>=0.9.0,<0.10",
    }
    assert SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION == {
        "resource_metrics": "mxc-resource-metrics",
        "script_logging": "mxc-script-logging",
        "web_ui_tools": "mxc-web-ui-tools",
        "termdash": "mxc-termdash",
        "cross_platform": "mxc-platform-utils",
    }


def test_shared_source_directory_and_distribution_detection_are_distinct() -> None:
    for module_dir, distribution in SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION.items():
        assert is_shared_module_dir(module_dir)
        assert is_shared_module_dir(f"modules/{module_dir}")
        assert is_shared_distribution(distribution)
    assert not is_shared_module_dir("runmux")
    assert not is_shared_distribution("runmux")
    for legacy in ("resource-metrics", "script-logging", "web-ui-tools", "termdash", "cross-platform"):
        assert not is_shared_distribution(legacy)


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
    assert is_shared_source_install(
        {
            "url": "file:///C:/Users/example/src/scripts/modules/script_logging",
            "dir_info": {"editable": True},
        }
    )
    assert not is_shared_source_install(
        {
            "url": "file:///C:/wheelhouse/mxc_script_logging-0.1.1-py3-none-any.whl",
            "archive_info": {"hash": "sha256=example"},
        }
    )


def test_toolkit_compatibility_wheel_is_replaced_even_when_version_matches() -> None:
    direct_url = {
        "url": "file:///C:/Users/example/src/llm-agent-toolkit/dist/mxc_script_logging-0.1.1-py3-none-any.whl",
        "archive_info": {"hash": "sha256=example"},
    }
    assert not is_shared_source_install(direct_url)
    assert needs_shared_distribution_replacement(direct_url)
    assert not needs_shared_distribution_replacement(
        {
            "url": "file:///C:/Users/example/AppData/Local/scripts-shared-wheelhouse/mxc_script_logging-0.1.1-py3-none-any.whl",
            "archive_info": {"hash": "sha256=example"},
        }
    )


def test_installer_replaces_toolkit_source_and_validates_the_environment(monkeypatch, capsys) -> None:
    import json

    from scripts_setup import shared_packages

    calls: list[list[str]] = []
    lookup_count: dict[str, int] = {}
    installed: set[str] = set()

    class Distribution:
        def __init__(self, source: bool = False) -> None:
            self.source = source

        def read_text(self, filename: str) -> str:
            if filename != "direct_url.json":
                return ""
            if self.source:
                return json.dumps({
                    "url": "file:///C:/Users/example/src/llm-agent-toolkit/dist/mxc_script_logging-0.1.1-py3-none-any.whl",
                    "archive_info": {"hash": "sha256=example"},
                })
            return json.dumps({
                "url": "file:///C:/wheelhouse/mxc_script_logging-0.1.1-py3-none-any.whl",
                "archive_info": {"hash": "sha256=example"},
            })

    def distribution(name: str) -> Distribution:
        if name not in SHARED_DISTRIBUTION_REQUIREMENTS:
            from importlib.metadata import PackageNotFoundError

            raise PackageNotFoundError(name)
        lookup_count[name] = lookup_count.get(name, 0) + 1
        if name == "mxc-script-logging" and lookup_count[name] == 1:
            return Distribution(source=True)
        if name in installed:
            return Distribution()
        from importlib.metadata import PackageNotFoundError

        raise PackageNotFoundError(name)

    def run(command, **_kwargs):
        calls.append(list(command))
        if command[4] == "uninstall":
            installed.discard(command[-1])
        elif command[4] == "install":
            installed.add(command[-1].split(">", 1)[0])
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(shared_packages.metadata, "distribution", distribution)
    monkeypatch.setattr(shared_packages.subprocess, "run", run)
    monkeypatch.setattr(shared_packages, "_legacy_editable_consumer_paths", lambda _root: [])

    assert shared_packages.ensure_shared_distributions(python="isolated-python")
    assert ["isolated-python", "-I", "-m", "pip", "uninstall", "-y", "mxc-script-logging"] in calls
    assert sum(call[4] == "install" and call[-1].startswith("mxc-") for call in calls) == 5
    assert calls[-1] == ["isolated-python", "-I", "-m", "pip", "check"]
    assert "Replacing checkout-local installation of mxc-script-logging" in capsys.readouterr().out


def test_installer_removes_legacy_shared_distributions_before_installing_namespaced_wheels(monkeypatch, tmp_path) -> None:
    from importlib import metadata
    from scripts_setup import shared_packages

    installed = {"resource-metrics": object()}
    calls: list[list[str]] = []

    class Distribution:
        def read_text(self, _filename: str) -> str:
            return '{"url":"file:///C:/wheelhouse/qualified.whl","archive_info":{"hash":"sha256=test"}}'

    def distribution(name: str):
        if name in installed:
            return Distribution()
        raise metadata.PackageNotFoundError(name)

    def run(command, **_kwargs):
        calls.append(list(command))
        if command[4] == "uninstall":
            installed.pop(command[-1], None)
        elif command[4] == "install":
            requirement = command[-1].split(">", 1)[0]
            installed[requirement] = Distribution()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(shared_packages.metadata, "distribution", distribution)
    monkeypatch.setattr(shared_packages.subprocess, "run", run)
    consumer = tmp_path / "modules" / "backup_module"
    monkeypatch.setattr(shared_packages, "_legacy_editable_consumer_paths", lambda _root: [consumer])

    assert shared_packages.ensure_shared_distributions(python="isolated-python")
    assert calls[0] == ["isolated-python", "-I", "-m", "pip", "uninstall", "-y", "resource-metrics"]
    assert sum(call[4] == "install" and call[-1].startswith("mxc-") for call in calls) == 5
    assert all(name not in installed for name in ("resource-metrics", "script-logging", "web-ui-tools", "termdash", "cross-platform"))
    assert [
        "isolated-python",
        "-I",
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--editable",
        str(consumer),
    ] in calls


def test_legacy_consumer_discovery_targets_only_scripts_owned_editable_modules(tmp_path) -> None:
    import json

    from scripts_setup.shared_packages import _legacy_editable_consumer_paths

    root = tmp_path / "current"
    consumer = root / "modules" / "backup_module"
    consumer.mkdir(parents=True)
    (consumer / "pyproject.toml").write_text('[project]\nname = "backup-module"\n', encoding="utf-8")

    class Distribution:
        def __init__(self, name: str, source: Path | None, requirements: list[str]) -> None:
            self.metadata = {"Name": name}
            self.requires = requirements
            self.source = source

        def read_text(self, filename: str) -> str:
            if filename != "direct_url.json" or self.source is None:
                return ""
            return json.dumps({"url": self.source.as_uri(), "dir_info": {"editable": True}})

    old_source = tmp_path / "prior" / "modules" / "backup_module"
    transferable_source = tmp_path / "prior" / "modules" / "llm_monitor"
    distributions = [
        Distribution("backup-module", old_source, ["resource-metrics>=0.3.0"]),
        Distribution("backup-module", old_source, ["pytest>=8"]),
        Distribution("llm-monitor", transferable_source, ["resource-metrics>=0.3.0"]),
    ]

    assert _legacy_editable_consumer_paths(root, distributions) == [consumer]


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
