from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path


from scripts_help import ag, command_registry, shell_integration


def test_command_registry_load_search_resolve_and_validate(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pyscripts").mkdir(parents=True)
    (repo / "modules" / "demo").mkdir(parents=True)
    (repo / "pyscripts" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "modules" / "demo" / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndescription = "Demo project command tools."\n\n[project.scripts]\ndemo-cli = "scripts_help.ag:main"\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "commands": {
            "hello": {
                "name": "hello",
                "program_id": "pyscript:pyscripts/hello.py",
                "kind": "python_file",
                "source_path": "pyscripts/hello.py",
                "target": "pyscripts/hello.py",
                "version": "0.1.0",
            },
            "ghost": {
                "name": "ghost",
                "program_id": "pyscript:pyscripts/ghost.py",
                "kind": "python_file",
                "source_path": "pyscripts/ghost.py",
                "target": "pyscripts/ghost.py",
                "version": "0.1.0",
            },
        },
    }
    (repo / "scripts_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    entries = command_registry.load_command_registry(repo)
    names = {e.name for e in entries}
    assert {"hello", "ghost", "demo-cli", "ag"}.issubset(names)
    assert next(e for e in entries if e.name == "demo-cli").description == "Demo project command tools."

    found = command_registry.search_commands(entries, "demo")
    assert [e.name for e in found] == ["demo-cli"]

    resolved = command_registry.resolve_command(entries, "HELLO")
    assert len(resolved) == 1
    assert resolved[0].program_id == "pyscript:pyscripts/hello.py"

    vals = {v.name: v for v in command_registry.validate_entry_points(entries, repo_root=repo)}
    assert vals["hello"].status == "ok"
    assert vals["ghost"].status == "missing_target"
    assert vals["demo-cli"].status == "ok"

    unsupported = command_registry.CommandEntry(
        name="only-mac",
        program_id="command:only-mac",
        invoked_name="only-mac",
        kind="console_script",
        source="test",
        target="scripts_help.ag:main",
        platforms=("nonexistent-os",),
    )
    u_val = command_registry.validate_entry_points([unsupported], repo_root=repo)[0]
    assert u_val.status == "unsupported_platform"


def test_clipboard_registered_tools_have_specific_help_descriptions():
    repo = command_registry.find_repo_root()
    entries = command_registry.load_command_registry(repo)
    c2c = next(e for e in entries if e.name == "c2c")
    assert c2c.description == "Copy selected file or path contents to the clipboard."
    assert c2c.description != c2c.target
    clipboard_entries = [e for e in entries if e.distribution == "clipboard_tools"]
    assert len(clipboard_entries) == 24
    assert {"cld", "cldd", "comp", "compd"} <= {entry.name for entry in clipboard_entries}
    assert all(e.description for e in clipboard_entries)
    assert all(e.description != "Clipboard command suite with multi-buffer support and tmux/Windows bridge." for e in clipboard_entries)


def test_ag_clip_search_lists_manifest_aliases_with_module_help(tmp_path: Path):
    repo = tmp_path / "repo"
    module = repo / "modules" / "clipboard_tools"
    module.mkdir(parents=True)
    (module / "pyproject.toml").write_text(
        '[project]\nname = "clipboard-tools"\nversion = "1.0.0"\n'
        '[project.scripts]\n'
        'c2c = "clipboard_tools.entrypoints:copy_main"\n'
        'otc = "clipboard_tools.entrypoints:output_to_clipboard_main"\n'
        'rwc = "clipboard_tools.entrypoints:replace_with_clipboard_main"\n'
        '[tool.scripts_help.descriptions]\n'
        'c2c = "Copy selected file or path contents to the clipboard."\n'
        'otc = "Copy command output to the clipboard."\n'
        'rwc = "Replace the current selection with clipboard contents."\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "commands": {
            "c2c": {
                "name": "c2c",
                "program_id": "module:clipboard_tools",
                "kind": "console_script",
                "source_path": "modules/clipboard_tools",
                "target": ".venv/Scripts/c2c.exe",
                "entry_point": "clipboard_tools.entrypoints:copy_main",
            },
            "otc": {
                "name": "otc",
                "program_id": "module:clipboard_tools",
                "kind": "console_script",
                "source_path": "modules/clipboard_tools",
                "target": ".venv/Scripts/otc.exe",
                "entry_point": "clipboard_tools.entrypoints:output_to_clipboard_main",
            },
            "rwc": {
                "name": "rwc",
                "program_id": "module:clipboard_tools",
                "kind": "console_script",
                "source_path": "modules/clipboard_tools",
                "target": ".venv/Scripts/rwc.exe",
                "entry_point": "clipboard_tools.entrypoints:replace_with_clipboard_main",
            }
        },
    }
    (repo / "scripts_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    entries = command_registry.load_command_registry(repo)
    entries.append(
        command_registry.CommandEntry(
            name="append_clipboard",
            program_id="pyscript:pyscripts/append_clipboard.py",
            invoked_name="append_clipboard",
            kind="python_file",
            source="scripts_manifest",
            target="pyscripts/append_clipboard.py",
            description="Append clipboard contents to the end of a file.",
        )
    )

    matches = ag.search_ag("clip", entries=entries)
    table = ag._format_table(matches)

    names = {entry.name for entry in matches}
    assert {"c2c", "otc", "rwc", "append_clipboard"}.issubset(names)
    assert "Copy selected file or path contents to the clipboard." in table
    assert "Copy command output to the clipboard." in table
    assert "Replace the current selection with clipboard contents." in table
    assert "append_clipboard" in table
    lines = table.splitlines()
    assert lines[0].split() == ["Name", "Help"]
    displayed_names = {line.split("  ", 1)[0].strip() for line in lines[2:]}
    assert {"c2c", "otc", "rwc", "append_clipboard"}.issubset(displayed_names)
    assert next(entry for entry in matches if entry.name == "c2c").target == "clipboard_tools.entrypoints:copy_main"


def test_alias_metadata_and_views_classify_short_and_full_commands(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    module = repo / "modules" / "clipboard_tools"
    module.mkdir(parents=True)
    (module / "pyproject.toml").write_text(
        '[project]\nname="clipboard_tools"\nversion="1.0"\n[project.scripts]\n'
        'c2c="clipboard_tools.entrypoints:copy_main"\n'
        'copy_to_clipboard="clipboard_tools.entrypoints:copy_main"\n'
        '[tool.scripts_help.commands]\nc2c={is_alias=true}\n', encoding="utf-8"
    )
    monkeypatch.setattr(ag, "find_repo_root", lambda: repo)
    monkeypatch.setattr(ag, "detect_silver_searcher_collision", lambda **_kwargs: None)
    assert ag.main(["clip"]) == 0
    alias_output = capsys.readouterr().out
    assert "c2c" in alias_output
    assert "copy_to_clipboard" not in alias_output

    assert ag.main(["clip", "--view", "full"]) == 0
    full_output = capsys.readouterr().out
    assert "copy_to_clipboard" in full_output
    assert "c2c" not in full_output

    entries = command_registry.load_command_registry(repo)
    assert next(item for item in entries if item.name == "c2c").is_alias is True


def test_scripts_help_registers_all_view_entrypoints():
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["ag"] == "scripts_help.ag:main"
    assert scripts["fg"] == "scripts_help.ag:full_main"
    assert scripts["mg"] == "scripts_help.ag:module_main"
    assert scripts["xg"] == "scripts_help.ag:all_main"


def test_ag_module_and_all_views_include_registered_commands():
    alias = command_registry.CommandEntry("c2c", "m", "c2c", "console_script", "test", "", is_alias=True)
    module = command_registry.CommandEntry("module-cli", "m", "module-cli", "console_script", "test", "")
    script = command_registry.CommandEntry("helper", "p", "helper", "python_file", "test", "")
    path_tool = command_registry.CommandEntry("unrelated", "x", "unrelated", "executable", "path", "")
    assert ag._view_matches(alias, "alias")
    assert ag._view_matches(module, "module")
    assert ag._view_matches(alias, "module")
    assert ag._view_matches(script, "all")
    assert ag._view_matches(path_tool, "all")


def test_xg_without_shell_inventory_prints_integration_hint(monkeypatch, capsys):
    monkeypatch.setattr(ag, "find_repo_root", lambda: None)
    monkeypatch.setattr(ag, "detect_silver_searcher_collision", lambda **_kwargs: None)
    monkeypatch.delenv("AG_SHELL_INVENTORY_FILE", raising=False)
    assert ag.all_main(["nothing"]) == 0
    assert "Live shell aliases unavailable; run 'scripts-help integrate --apply'." in capsys.readouterr().err


def test_shell_adapters_publish_requested_view_functions():
    pwsh = shell_integration.render_pwsh_adapter()
    posix = shell_integration.render_posix_adapter()
    for name in ("fg", "mg", "xg"):
        assert f"function global:{name}" in pwsh
        assert f"{name}() {{ ag --view" in posix


def test_ag_search_formatting_shell_inventory_and_silver_searcher_collision(tmp_path: Path, monkeypatch, capsys):
    inv_file = tmp_path / "inv.json"
    inv_file.write_text(
        json.dumps(
            {
                "shell": "pwsh",
                "items": [
                    {"name": "gcb", "kind": "shell_alias", "source": "pwsh", "definition": "Get-Clipboard", "curated": True},
                    {"name": "myHelper", "kind": "shell_function", "source": "pwsh", "definition": "Write-Host hi", "curated": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    ext_dir = tmp_path / "ext_bin"
    ext_dir.mkdir()
    ext_ag = ext_dir / ("ag.exe" if os.name == "nt" else "ag")
    ext_ag.write_text("binary", encoding="utf-8")
    path_tool = ext_dir / ("only-path-tool.exe" if os.name == "nt" else "only-path-tool")
    path_tool.write_text("binary", encoding="utf-8")
    if os.name != "nt":
        ext_ag.chmod(0o755)
        path_tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(ext_dir))

    rc = ag.main(["--shell-inventory", str(inv_file), "--type", "alias", "gcb"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name" in captured.out
    assert "Help" in captured.out
    assert "Definition" not in captured.out
    assert "gcb" in captured.out
    assert "Shell alias" in captured.out
    assert "Get-Clipboard" not in captured.out
    assert "External `ag`" in captured.err

    assert ag.main(["--shell-inventory", str(inv_file), "--type", "alias", "--definitions", "Get-Clipboard"]) == 0
    definition_output = capsys.readouterr().out
    assert "Get-Clipboard" in definition_output

    rc_json = ag.main(["--shell-inventory", str(inv_file), "--all", "--json", "myhelper"])
    assert rc_json == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 1
    assert data["matches"][0]["name"] == "myHelper"
    assert data["silver_searcher_collision"] is not None

    assert ag.main(["--executables", "--json", "only-path-tool"]) == 0
    path_result = json.loads(capsys.readouterr().out)
    assert path_result["matches"][0]["source"] == "path"


def test_ag_curated_default_and_definition_mode(tmp_path: Path, capsys, monkeypatch):
    inv_file = tmp_path / "inv.json"
    inv_file.write_text(json.dumps({"shell": "pwsh", "items": [
        {"name": "c2c", "kind": "shell_alias", "source": "pwsh", "definition": "copy_main", "description": "Copy text to clipboard", "curated": True},
        {"name": "Get-OdbcDsn", "kind": "shell_function", "source": "pwsh", "definition": "system function", "description": "system function", "curated": False},
    ]}), encoding="utf-8")
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert ag.main(["--shell-inventory", str(inv_file), "clip"]) == 0
    default = capsys.readouterr().out
    assert "c2c" in default and "Copy text to clipboard" in default
    assert "Get-OdbcDsn" not in default
    assert "copy_main" not in default

    assert ag.main(["--shell-inventory", str(inv_file), "--definitions", "copy_main"]) == 0
    definitions = capsys.readouterr().out
    assert "Definition" in definitions and "copy_main" in definitions

    assert ag.main(["--shell-inventory", str(inv_file), "--all", "odbc"]) == 0
    all_output = capsys.readouterr().out
    assert "Get-OdbcDsn" in all_output


def test_ag_color_is_terminal_only_and_no_color_wins(tmp_path: Path, capsys, monkeypatch):
    inv_file = tmp_path / "inv.json"
    inv_file.write_text(json.dumps({"shell": "pwsh", "items": [
        {"name": "myclip", "kind": "shell_alias", "source": "pwsh", "definition": "copy_main", "description": "Clipboard copy", "curated": True},
    ]}), encoding="utf-8")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(ag.sys.stdout, "isatty", lambda: True)
    assert ag.main(["--shell-inventory", str(inv_file), "clip"]) == 0
    assert "\x1b[" in capsys.readouterr().out

    monkeypatch.setenv("NO_COLOR", "1")
    assert ag.main(["--shell-inventory", str(inv_file), "clip"]) == 0
    assert "\x1b[" not in capsys.readouterr().out


def test_ag_output_width_and_json_remain_clean(tmp_path: Path, capsys, monkeypatch):
    entry = command_registry.CommandEntry(
        name="very-long-command-name",
        program_id="module:demo",
        invoked_name="very-long-command-name",
        kind="console_script",
        source="pyproject",
        target="demo.entrypoint:main --very-long-option",
        description="A long help description that should be clipped to fit the terminal width.",
    )
    table = ag._format_table([entry], definitions=True, terminal_width=34)
    assert all(len(line) <= 34 for line in table.splitlines())
    assert "..." in table

    inv_file = tmp_path / "inv.json"
    inv_file.write_text(json.dumps({"shell": "pwsh", "items": [
        {"name": "myclip", "kind": "shell_alias", "source": "pwsh", "definition": "copy_main", "description": "Clipboard copy", "curated": True},
    ]}), encoding="utf-8")
    monkeypatch.setattr(ag.sys.stdout, "isatty", lambda: True)
    assert ag.main(["--shell-inventory", str(inv_file), "--json", "clip"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert set(payload) == {"schema_version", "pattern", "count", "matches", "silver_searcher_collision"}
    assert "\x1b[" not in output


def test_ag_adapter_emits_curated_classification():
    assert "curated" in shell_integration.render_pwsh_adapter()
    assert "curated" in shell_integration.render_posix_adapter()


def test_shell_integration_dry_run_apply_idempotent_and_rollback(tmp_path: Path):
    target_dir = tmp_path / "dynamic"

    # Dry-run default does not create files
    dry = shell_integration.run_integration(target_dir=target_dir, apply=False)
    assert dry["dry_run"] is True
    assert not (target_dir / "ag_integration.ps1").exists()
    assert not (target_dir / "ag_integration.sh").exists()

    # Apply creates managed files
    applied = shell_integration.run_integration(target_dir=target_dir, apply=True)
    assert applied["dry_run"] is False
    ps1 = target_dir / "ag_integration.ps1"
    sh = target_dir / "ag_integration.sh"
    assert ps1.is_file()
    assert sh.is_file()

    # Check is clean and second apply is unchanged (idempotent)
    checked = shell_integration.run_integration(target_dir=target_dir, check=True)
    assert checked["clean"] is True
    again = shell_integration.run_integration(target_dir=target_dir, apply=True)
    assert all(a["status"] == "unchanged" for a in again["actions"])

    # User-authored content outside markers is preserved across update & rollback
    ps1.write_text("# user comment\n$myVar = 1\n" + ps1.read_text(encoding="utf-8"), encoding="utf-8")
    upd = shell_integration.run_integration(target_dir=target_dir, apply=True, shells=("pwsh",))
    assert upd["actions"][0]["status"] == "unchanged" or "# user comment" in ps1.read_text(encoding="utf-8")

    shell_integration.run_integration(target_dir=target_dir, apply=True, rollback=True)
    assert "# user comment" in ps1.read_text(encoding="utf-8")
    assert "$myVar = 1" in ps1.read_text(encoding="utf-8")
    assert shell_integration.MANAGED_START not in ps1.read_text(encoding="utf-8")
    assert not sh.exists()


def test_posix_adapter_has_no_pipe_heredoc_conflict():
    posix_src = shell_integration.render_posix_adapter()
    assert "| python3" not in posix_src
    assert "$_ag_raw" in posix_src
    assert "$_ag_fn_raw" in posix_src
