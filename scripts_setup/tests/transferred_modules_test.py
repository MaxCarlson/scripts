"""Tests for permanent ownership boundary and transferred-module exclusions in scripts."""
from __future__ import annotations

from pathlib import Path

import bootstrap_latest
from modules.setup_utils.dependency_resolver import resolve_module_order
from scripts_setup.launcher_generator import (
    generate_posix_wrapper,
    generate_windows_wrapper,
    scan_repository_programs,
)
from scripts_setup.setup_skills import discover_skills
from scripts_setup.transferred_modules import (
    SCRIPTS_OWNED_SHARED_MODULES,
    TRANSFERRED_CLI_COMMANDS,
    TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION,
    TRANSFERRED_MODULE_DIRS,
    is_transferred_cli_command,
    is_transferred_distribution,
    is_transferred_module_dir,
)
from scripts_setup.shared_packages import SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_transferred_registry_contains_exact_23_modules_and_excludes_shared_scripts_modules() -> None:
    assert len(TRANSFERRED_MODULE_DIRS) == 23
    assert len(TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION) == 23
    assert TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION["llm-interface"] == "api-parser"
    for shared in SCRIPTS_OWNED_SHARED_MODULES:
        assert not is_transferred_module_dir(shared)
        assert not is_transferred_distribution(shared)

    for directory, dist_name in TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION.items():
        assert is_transferred_module_dir(directory)
        assert is_transferred_module_dir(REPO_ROOT / "modules" / directory)
        assert is_transferred_distribution(dist_name)
        assert is_transferred_distribution(dist_name.replace("-", "_"))
        # Original source directory must remain untouched on disk!
        assert (REPO_ROOT / "modules" / directory).is_dir()


def test_dependency_resolver_excludes_all_23_transferred_modules() -> None:
    order = resolve_module_order(REPO_ROOT / "modules")
    assert not (set(order) & set(TRANSFERRED_MODULE_DIRS))
    assert not (set(order) & set(SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION))


def test_bootstrap_latest_package_sources_excludes_all_transferred_modules() -> None:
    sources, _unknown = bootstrap_latest.package_sources(REPO_ROOT)
    source_dirs = {path.name for _name, path in sources if path.parent == REPO_ROOT / "modules"}
    source_dists = {name for name, _path in sources}

    assert not (source_dirs & set(TRANSFERRED_MODULE_DIRS))
    assert not any(is_transferred_distribution(name) for name in source_dists)
    assert not (source_dirs & set(SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION))
    assert not any(name in SHARED_MODULE_DIRECTORY_TO_DISTRIBUTION.values() for name in source_dists)


def test_launcher_generator_scan_excludes_all_transferred_commands() -> None:
    commands = scan_repository_programs(REPO_ROOT)
    assert not (set(commands.keys()) & set(TRANSFERRED_CLI_COMMANDS.keys()))
    for cmd_name, entry in commands.items():
        assert not is_transferred_cli_command(cmd_name)
        if entry.distribution:
            assert not is_transferred_distribution(entry.distribution)
    assert "termdash" in commands
    assert commands["termdash"].source_path == "installed-distribution:mxc-termdash"
    assert "scripts-help" in commands


def test_launcher_generator_includes_console_scripts_from_pscripts_setup_py(tmp_path: Path) -> None:
    module = tmp_path / "pscripts" / "modules" / "legacy_cli"
    module.mkdir(parents=True)
    (module / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='legacy_cli', version='1.2.3', entry_points={"
        "'console_scripts': ['legacy-cli=legacy_cli.cli:main']})\n",
        encoding="utf-8",
    )

    commands = scan_repository_programs(tmp_path)

    assert commands["legacy-cli"].program_id == "module:legacy_cli"
    assert commands["legacy-cli"].source_path == "pscripts/modules/legacy_cli"
    assert commands["legacy-cli"].distribution == "legacy_cli"
    assert commands["legacy-cli"].entry_point == "legacy_cli.cli:main"
    assert commands["legacy-cli"].version == "1.2.3"


def test_setup_skills_excludes_transferred_modules() -> None:
    skills = discover_skills(REPO_ROOT / "modules")
    for skill_dir in skills:
        rel = skill_dir.relative_to(REPO_ROOT / "modules")
        assert not is_transferred_module_dir(rel.parts[0])


def test_generated_wrappers_delegate_script_logging_launcher_with_target_python() -> None:
    win = generate_windows_wrapper("scripts-help")
    assert 'set "_LAUNCHER_PY=%_VENV_PY%"' in win
    assert "llm-agent-toolkit" not in win
    assert "LLM_AGENT_TOOLKIT_ROOT" not in win
    assert r'-I "%_ROOT%scripts_setup\launcher.py"' in win
    assert "-m scripts_setup.launcher" not in win
    assert '--target-python "%_VENV_PY%"' in win

    posix = generate_posix_wrapper("scripts-help")
    assert 'LAUNCHER_PY="$VENV_PY"' in posix
    assert "llm-agent-toolkit" not in posix
    assert "LLM_AGENT_TOOLKIT_ROOT" not in posix
    assert '-I "$ROOT/scripts_setup/launcher.py"' in posix
    assert "-m scripts_setup.launcher" not in posix
    assert '--target-python "$VENV_PY"' in posix
