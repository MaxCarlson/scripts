from scripts_setup.launcher_generator import (
    scan_repository_programs,
    detect_collisions,
    generate_manifest,
    generate_windows_wrapper,
    generate_posix_wrapper,
    classify_wrapper,
    is_managed_wrapper,
    CommandEntry,
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
