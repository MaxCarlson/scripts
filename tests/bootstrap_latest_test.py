"""Behavioral tests for the missing-only bootstrap (no real pip calls)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("bootstrap_latest", Path(__file__).resolve().parents[1] / "bootstrap_latest.py")
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


@pytest.fixture(autouse=True)
def isolate_shared_distribution_installation(monkeypatch):
    """Keep bootstrap unit tests independent from the caller's Python environment."""
    from scripts_setup import shared_packages

    monkeypatch.setattr(shared_packages, "ensure_shared_distributions", lambda **_kwargs: True)


def project(path: Path, name: str) -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "2.0"\n', encoding="utf-8")
    return path


def test_run_validates_shared_packages_before_local_sources(tmp_path, monkeypatch):
    from scripts_setup import shared_packages

    calls = []
    monkeypatch.setattr(
        shared_packages,
        "ensure_shared_distributions",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(bootstrap, "installed_versions", dict)
    monkeypatch.setattr(bootstrap, "console_scripts", lambda _names: [])

    assert bootstrap.run(tmp_path, dry_run=True, verbose=True) == 0
    assert calls == [{"dry_run": True, "verbose": True}]


def test_package_sources_core_first_and_duplicate_canonical(tmp_path):
    project(tmp_path / "modules" / "standard_ui", "standard-ui")
    project(tmp_path / "modules" / "aebndl_module", "aebndl")
    project(tmp_path / "pscripts" / "modules" / "old_aebndl", "aebndl")
    sources, unknown = bootstrap.package_sources(tmp_path)
    assert unknown == []
    assert [name for name, _ in sources] == ["standard-ui", "aebndl"]
    assert sources[-1][1].name == "aebndl_module"


def test_installed_package_at_source_version_is_not_reinstalled(tmp_path, monkeypatch):
    project(tmp_path / "modules" / "standard_ui", "standard-ui")
    monkeypatch.setattr(bootstrap, "installed_versions", lambda: {"standard-ui": "2.0"})
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pip should not run")))
    assert bootstrap.run(tmp_path) == 0


def test_dry_run_does_not_install_or_create_launcher(tmp_path, monkeypatch):
    project(tmp_path / "modules" / "standard_ui", "standard-ui")
    scripts = tmp_path / "pyscripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text("print('hi')", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "installed_versions", dict)
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pip should not run")))
    assert bootstrap.run(tmp_path, dry_run=True) == 0
    assert not (tmp_path / "bin").exists()


def test_missing_package_installed_once_and_existing_launcher_preserved(tmp_path, monkeypatch):
    project(tmp_path / "modules" / "standard_ui", "standard-ui")
    scripts = tmp_path / "pyscripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text("print('hi')", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    destination = bootstrap.launcher_path(bin_dir, "tool", bootstrap.os.name == "nt")
    destination.write_text("user content", encoding="utf-8")
    calls = []
    monkeypatch.setattr(bootstrap, "installed_versions", dict)
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    assert bootstrap.run(tmp_path) == 0
    assert len(calls) == 1
    assert calls[0][-1] == str(tmp_path / "modules" / "standard_ui")
    assert destination.read_text(encoding="utf-8") == "user content"


def test_missing_launcher_created_and_second_run_preserves_it(tmp_path, monkeypatch):
    scripts = tmp_path / "pyscripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text("print('hi')", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "installed_versions", dict)
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    assert bootstrap.run(tmp_path) == 0
    destination = bootstrap.launcher_path(tmp_path / "bin", "tool", bootstrap.os.name == "nt")
    assert destination.is_file()
    destination.write_text("edited by user", encoding="utf-8")
    assert bootstrap.run(tmp_path) == 0
    assert destination.read_text(encoding="utf-8") == "edited by user"


def test_unknown_package_name_fails_closed(tmp_path, monkeypatch):
    source = tmp_path / "modules" / "dynamic"
    source.mkdir(parents=True)
    (source / "setup.py").write_text("setup(name=get_name())", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "installed_versions", dict)
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    assert bootstrap.run(tmp_path) == 1


def test_missing_private_submodule_access_reports_failure(tmp_path, monkeypatch, capsys):
    (tmp_path / ".gitmodules").write_text(
        '[submodule "pscripts"]\n\tpath = pscripts\n\turl = https://example.invalid/pscripts.git\n',
        encoding="utf-8",
    )
    calls = []

    def fail_submodule_access(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=128)

    monkeypatch.setattr(bootstrap.subprocess, "run", fail_submodule_access)

    assert bootstrap.run(tmp_path) == 1
    assert calls == [["git", "-C", str(tmp_path), "submodule", "update", "--init", "--recursive", "--", "pscripts"]]
    assert "[ERROR] pscripts submodule is missing and could not be initialized" in capsys.readouterr().err


def test_missing_pscripts_project_installs_requirements_only_when_missing(tmp_path, monkeypatch):
    source = project(tmp_path / "pscripts" / "modules" / "utility", "utility")
    (source / "requirements.txt").write_text("requests\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(bootstrap, "installed_versions", dict)
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    assert bootstrap.run(tmp_path) == 0
    assert len(calls) == 2
    assert "-r" in calls[0]
    assert "-e" in calls[1]


def test_console_proxy_does_not_replace_existing_file(tmp_path):
    destination = tmp_path / "bin" / "tool.cmd"
    destination.parent.mkdir()
    destination.write_text("owned by user", encoding="utf-8")
    try:
        bootstrap.write_console_proxy(destination, "tool", True, tmp_path / ".venv")
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing console proxy should be preserved")
    assert destination.read_text(encoding="utf-8") == "owned by user"


def test_private_canonical_aebndl_wins_when_public_copy_is_absent(tmp_path, monkeypatch):
    project(tmp_path / "pscripts" / "modules" / "aebn-vod-downloader-custom", "aebndl")
    canonical = project(tmp_path / "pscripts" / "modules" / "aebndl_module", "aebndl")
    monkeypatch.setattr(bootstrap, "installed_versions", dict)
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    sources, unknown = bootstrap.package_sources(tmp_path)

    assert unknown == []
    assert [(name, path) for name, path in sources] == [("aebndl", canonical)]


def test_installed_older_version_is_upgraded_from_local_source(tmp_path, monkeypatch):
    source = project(tmp_path / "pscripts" / "modules" / "utility", "utility")
    (source / "pyproject.toml").write_text('[project]\nname="utility"\nversion="2.0"\n', encoding="utf-8")
    monkeypatch.setattr(bootstrap, "installed_versions", lambda: {"utility": "1.0"})
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    calls = []
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))

    assert bootstrap.run(tmp_path) == 0
    assert len(calls) == 1
    assert calls[0][-1] == str(source)


def test_managed_stale_console_wrapper_is_repaired(tmp_path, monkeypatch):
    from scripts_setup.launcher_generator import generate_windows_wrapper

    source = project(tmp_path / "pscripts" / "modules" / "utility", "utility")
    (source / "pyproject.toml").write_text(
        '[project]\nname="utility"\nversion="2.0"\n[project.scripts]\ntool="utility:main"\n',
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    destination = bootstrap.launcher_path(bin_dir, "tool", True)
    stale_content = generate_windows_wrapper("tool").replace("exit /b %ERRORLEVEL%", "exit /b 7")
    destination.write_bytes(stale_content.encode("utf-8"))
    monkeypatch.setattr(bootstrap, "installed_versions", lambda: {"utility": "2.0"})
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [("tool", "utility")])
    monkeypatch.setattr(bootstrap, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(bootstrap, "sys", SimpleNamespace(executable="python", path=[]))
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "tool.exe").write_bytes(b"fixture")

    assert bootstrap.run(tmp_path) == 0
    actual = destination.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == generate_windows_wrapper("tool").replace("\r\n", "\n")


def test_actual_pinned_private_media_packages_are_discovered_once():
    root = Path(__file__).resolve().parents[1]

    sources, unknown = bootstrap.package_sources(root)

    assert unknown == []
    by_name = {bootstrap.normalized(name): path for name, path in sources}
    for name in ("mangadl", "ytaedl", "aebndl"):
        assert name in by_name
        assert "pscripts" in by_name[name].parts
    assert sum(bootstrap.normalized(name) == "aebndl" for name, _ in sources) == 1
