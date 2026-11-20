from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from scripts_help import ag, command_registry, shell_integration


def test_command_registry_load_search_resolve_and_validate(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pyscripts").mkdir(parents=True)
    (repo / "modules" / "demo").mkdir(parents=True)
    (repo / "pyscripts" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "modules" / "demo" / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[project.scripts]\ndemo-cli = "scripts_help.ag:main"\n',
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


def test_ag_search_formatting_shell_inventory_and_silver_searcher_collision(tmp_path: Path, monkeypatch, capsys):
    inv_file = tmp_path / "inv.json"
    inv_file.write_text(
        json.dumps(
            {
                "shell": "pwsh",
                "items": [
                    {"name": "gcb", "kind": "shell_alias", "source": "pwsh", "definition": "Get-Clipboard"},
                    {"name": "myHelper", "kind": "shell_function", "source": "pwsh", "definition": "Write-Host hi"},
                ],
            }
        ),
        encoding="utf-8",
    )

    ext_dir = tmp_path / "ext_bin"
    ext_dir.mkdir()
    ext_ag = ext_dir / ("ag.exe" if os.name == "nt" else "ag")
    ext_ag.write_text("binary", encoding="utf-8")
    if os.name != "nt":
        ext_ag.chmod(0o755)
    monkeypatch.setenv("PATH", str(ext_dir))

    rc = ag.main(["--shell-inventory", str(inv_file), "--type", "alias", "clip"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Name" in captured.out
    assert "Definition" in captured.out
    assert "gcb" in captured.out
    assert "Get-Clipboard" in captured.out
    assert "External `ag`" in captured.err

    rc_json = ag.main(["--shell-inventory", str(inv_file), "--json", "myhelper"])
    assert rc_json == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 1
    assert data["matches"][0]["name"] == "myHelper"
    assert data["silver_searcher_collision"] is not None


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

    rb = shell_integration.run_integration(target_dir=target_dir, apply=True, rollback=True)
    assert "# user comment" in ps1.read_text(encoding="utf-8")
    assert "$myVar = 1" in ps1.read_text(encoding="utf-8")
    assert shell_integration.MANAGED_START not in ps1.read_text(encoding="utf-8")
    assert not sh.exists()
