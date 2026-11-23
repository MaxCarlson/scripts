from pathlib import Path

from scripts_setup.launcher_generator import (
    CommandEntry,
    classify_wrapper,
    detect_collisions,
    generate_manifest,
    generate_posix_wrapper,
    generate_windows_wrapper,
    is_managed_wrapper,
    scan_repository_programs,
    write_wrapper,
)


def test_scan_repository_programs(tmp_path):
    mod_dir = tmp_path / "modules" / "mymod"
    mod_dir.mkdir(parents=True)
    (mod_dir / "pyproject.toml").write_text(
        """
[project]
name = "mymod"
version = "1.2.3"

[project.scripts]
mycmd = "mymod.cli:main"
alias_cmd = "mymod.cli:main"
""",
        encoding="utf-8",
    )

    pyscripts_dir = tmp_path / "pyscripts"
    pyscripts_dir.mkdir(parents=True)
    (pyscripts_dir / "my_standalone.py").write_text("__version__ = '0.3.0'\n", encoding="utf-8")

    shell_dir = tmp_path / "shell-scripts"
    shell_dir.mkdir(parents=True)
    (shell_dir / "my_script.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")

    commands = scan_repository_programs(tmp_path)

    assert "mycmd" in commands
    assert commands["mycmd"].program_id == "module:mymod"
    assert commands["mycmd"].kind == "console_script"
    assert commands["mycmd"].version == "1.2.3"

    assert "alias_cmd" in commands
    assert commands["alias_cmd"].program_id == "module:mymod"

    assert "my_standalone" in commands
    assert commands["my_standalone"].program_id == "pyscript:pyscripts/my_standalone.py"
    assert commands["my_standalone"].version == "0.3.0"

    assert "my_script" in commands
    assert commands["my_script"].program_id == "shell:shell-scripts/my_script.sh"


def test_detect_collisions_case_insensitive():
    commands = {
        "Foo": CommandEntry(
            name="Foo", program_id="module:foo", kind="console_script",
            source_path="modules/foo", target="foo", target_windows="foo.exe", target_posix="foo", version="1.0"
        ),
        "foo": CommandEntry(
            name="foo", program_id="module:bar", kind="console_script",
            source_path="modules/bar", target="bar", target_windows="bar.exe", target_posix="bar", version="1.0"
        ),
    }
    collisions = detect_collisions(commands)
    assert collisions.has_collisions is True
    assert "foo" in collisions.case_insensitive_clashes
    assert collisions.case_insensitive_clashes["foo"] == ["Foo", "foo"]


def test_classify_and_is_managed_wrapper(tmp_path):
    # Current Windows managed wrapper
    win_file = tmp_path / "win.cmd"
    win_file.write_text(generate_windows_wrapper("test_cmd"), encoding="utf-8")
    assert is_managed_wrapper(win_file) is True
    assert classify_wrapper(win_file).status == "managed_current"

    # Current POSIX managed wrapper
    posix_file = tmp_path / "posix"
    posix_file.write_text(generate_posix_wrapper("test_cmd"), encoding="utf-8")
    assert is_managed_wrapper(posix_file) is True
    assert classify_wrapper(posix_file).status == "managed_current"

    # Legacy setup.py wrapper
    legacy_file = tmp_path / "legacy.cmd"
    legacy_file.write_text(
        '@echo off\r\nsetlocal\r\nset "_B=%~dp0"\r\nset "_V=%_B%..\\.venv\\Scripts"\r\n"%_V%\\legacy.exe" %*\r\n',
        encoding="utf-8",
    )
    assert is_managed_wrapper(legacy_file) is True
    assert classify_wrapper(legacy_file).status == "managed_legacy"

    # Unmanaged / custom user wrapper
    custom_file = tmp_path / "custom.cmd"
    custom_file.write_text("@echo off\r\necho Custom user launcher\r\n", encoding="utf-8")
    assert is_managed_wrapper(custom_file) is False
    assert classify_wrapper(custom_file).status == "unmanaged"


def test_generate_manifest(tmp_path):
    mod_dir = tmp_path / "modules" / "pkg"
    mod_dir.mkdir(parents=True)
    (mod_dir / "pyproject.toml").write_text(
        '[project]\nname = "pkg"\nversion = "0.5.0"\n[project.scripts]\npkg = "pkg:main"\n',
        encoding="utf-8",
    )
    manifest_path = generate_manifest(tmp_path)
    assert manifest_path.is_file()
    import json
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert "pkg" in data["commands"]
    assert data["commands"]["pkg"]["program_id"] == "module:pkg"


def test_private_pscripts_does_not_shadow_public_aebndl_until_migration(tmp_path):
    public = tmp_path / "modules" / "aebndl_module"
    private = tmp_path / "pscripts" / "modules" / "aebndl_module"
    for directory in (public, private):
        directory.mkdir(parents=True)
        (directory / "pyproject.toml").write_text(
            '[project]\nname="aebndl"\nversion="0.8.1"\n[project.scripts]\naebndl="aebn_dl.cli:main"\n',
            encoding="utf-8",
        )

    commands = scan_repository_programs(tmp_path)

    assert commands["aebndl"].source_path == "modules/aebndl_module"


def test_duplicate_console_command_ownership_is_rejected(tmp_path):
    for module, distribution in (("one", "one"), ("two", "two")):
        directory = tmp_path / "modules" / module
        directory.mkdir(parents=True)
        (directory / "pyproject.toml").write_text(
            f'[project]\nname="{distribution}"\nversion="1.0"\n[project.scripts]\nshared="{distribution}:main"\n',
            encoding="utf-8",
        )

    try:
        scan_repository_programs(tmp_path)
    except ValueError as exc:
        assert "shared" in str(exc)
    else:
        raise AssertionError("duplicate console command owners should fail closed")


def test_pinned_pscripts_media_commands_are_in_manifest_inventory():
    root = Path(__file__).resolve().parents[1]

    commands = scan_repository_programs(root)

    for name in ("mangadl", "ytaedl", "aebndl", "video-tools"):
        assert name in commands
        assert commands[name].source_path.startswith("pscripts/modules/")


def test_windows_wrapper_write_is_idempotent_without_doubled_carriage_returns(tmp_path):
    wrapper = tmp_path / "demo.cmd"

    assert write_wrapper(wrapper, "demo", is_windows=True) is True
    first = wrapper.read_bytes()
    assert b"\r\r\n" not in first

    assert write_wrapper(wrapper, "demo", is_windows=True) is False
    assert wrapper.read_bytes() == first


def test_scan_repository_programs_reads_poetry_and_literal_setup_py_entry_points(tmp_path):
    syncmux = tmp_path / "modules" / "syncmux"
    syncmux.mkdir(parents=True)
    (syncmux / "pyproject.toml").write_text(
        "[tool.poetry]\nname = \"syncmux\"\nversion = \"0.1.0\"\n"
        "[tool.poetry.scripts]\nsyncmux = \"syncmux.__main__:main\"\n",
        encoding="utf-8",
    )

    translations = tmp_path / "modules" / "translations"
    translations.mkdir(parents=True)
    (translations / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name=\"translations\", version=\"0.1.0\", "
        "entry_points={\"console_scripts\": [\"translations=translations.cli:main\"]})\n",
        encoding="utf-8",
    )

    commands = scan_repository_programs(tmp_path)

    assert commands["syncmux"].distribution == "syncmux"
    assert commands["syncmux"].entry_point == "syncmux.__main__:main"
    assert commands["translations"].distribution == "translations"
    assert commands["translations"].entry_point == "translations.cli:main"
