from __future__ import annotations

import json
from pathlib import Path

from development_ledger.cli import main
from development_ledger.setup_cli import main as setup_main


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "modules" / "alpha").mkdir(parents=True)
    return root


def test_setup_cli_dry_run_then_write(tmp_path: Path, capsys):
    root = _repo(tmp_path)

    result = main(["setup", "-r", str(root), "-m", "alpha", "-a", "claude"])

    assert result == 0
    assert not (root / "AGENTS.md").exists()
    assert "DRY-RUN" in capsys.readouterr().out

    result = main(["setup", "-r", str(root), "-m", "alpha", "-a", "claude", "-w"])

    assert result == 0
    assert (root / "AGENTS.md").exists()
    assert (root / "CLAUDE.md").exists()
    assert not (root / "GEMINI.md").exists()
    assert "APPLY" in capsys.readouterr().out


def test_setup_cli_json_output(tmp_path: Path, capsys):
    root = _repo(tmp_path)

    result = main(["setup", "-r", str(root), "-F", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["repo_root"] == str(root.resolve())
    assert payload["scopes"] == ["."]


def test_dedicated_setup_entrypoint_prepends_subcommand(tmp_path: Path):
    root = _repo(tmp_path)

    result = setup_main(["-r", str(root), "-a", "codex", "-w"])

    assert result == 0
    assert (root / "AGENTS.md").exists()
