"""Behavioral tests for the missing-only bootstrap (no real pip calls)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


SPEC = importlib.util.spec_from_file_location("bootstrap_latest", Path(__file__).resolve().parents[1] / "bootstrap_latest.py")
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def project(path: Path, name: str) -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "2.0"\n', encoding="utf-8")
    return path


def test_package_sources_core_first_and_duplicate_canonical(tmp_path):
    project(tmp_path / "modules" / "standard_ui", "standard-ui")
    project(tmp_path / "modules" / "aebndl_module", "aebndl")
    project(tmp_path / "pscripts" / "modules" / "old_aebndl", "aebndl")
    sources, unknown = bootstrap.package_sources(tmp_path)
    assert unknown == []
    assert [name for name, _ in sources] == ["standard-ui", "aebndl"]
    assert sources[-1][1].name == "aebndl_module"


def test_installed_package_is_not_reinstalled_even_if_source_version_differs(tmp_path, monkeypatch):
    project(tmp_path / "modules" / "standard_ui", "standard-ui")
    monkeypatch.setattr(bootstrap, "installed_names", lambda: {"standard-ui"})
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pip should not run")))
    assert bootstrap.run(tmp_path) == 0


def test_dry_run_does_not_install_or_create_launcher(tmp_path, monkeypatch):
    project(tmp_path / "modules" / "standard_ui", "standard-ui")
    scripts = tmp_path / "pyscripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text("print('hi')", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "installed_names", lambda: set())
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
    monkeypatch.setattr(bootstrap, "installed_names", lambda: set())
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
    monkeypatch.setattr(bootstrap, "installed_names", lambda: set())
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
    monkeypatch.setattr(bootstrap, "installed_names", lambda: set())
    monkeypatch.setattr(bootstrap, "console_scripts", lambda names: [])
    assert bootstrap.run(tmp_path) == 1


def test_missing_pscripts_project_installs_requirements_only_when_missing(tmp_path, monkeypatch):
    source = project(tmp_path / "pscripts" / "modules" / "utility", "utility")
    (source / "requirements.txt").write_text("requests\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(bootstrap, "installed_names", lambda: set())
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
