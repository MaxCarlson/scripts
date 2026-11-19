"""Tests for reversible, dry-run-first hook installation, uninstall, and rollback."""

from __future__ import annotations

import json
from pathlib import Path

from agent_continuity.cli import main
from agent_continuity.installer import inspect_hooks_status, install_hooks, rollback_hooks, uninstall_hooks


def test_codex_hook_install_preserves_unrelated_hooks_and_legacy_notify(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.toml").write_text('notify = ["pwsh", "notify.ps1"]\n', encoding="utf-8")
    original_hooks = {
        "Stop": [{"type": "command", "command": "echo existing-stop"}],
    }
    (codex_dir / "hooks.json").write_text(json.dumps(original_hooks, indent=2), encoding="utf-8")

    # Dry-run must not modify hooks.json
    dry = install_hooks("codex", config_dir=codex_dir, apply=False)
    assert dry["applied"] is False
    assert json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8")) == original_hooks

    # Apply creates backup, preserves existing Stop hook, and is idempotent
    res1 = install_hooks("codex", config_dir=codex_dir, apply=True)
    assert res1["applied"] is True
    assert res1["backup_path"] is not None
    res2 = install_hooks("codex", config_dir=codex_dir, apply=True)
    data = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
    assert len(data["Stop"]) == 2
    assert data["Stop"][0]["command"] == "echo existing-stop"
    assert len(data["UserPromptSubmit"]) == 1
    assert res2["applied"] is True

    st = inspect_hooks_status("codex", config_dir=codex_dir)
    assert st["installed"] is True
    assert st["legacy_notify_present"] is True
    assert st["unrelated_hooks_present"] >= 1

    # Uninstall removes only managed entries
    uninst = uninstall_hooks("codex", config_dir=codex_dir, apply=True)
    assert uninst["changed"] is True
    after_uninst = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
    assert after_uninst == original_hooks

    # Rollback restores backup
    rb = rollback_hooks("codex", config_dir=codex_dir, backup_path=res1["backup_path"], apply=True)
    assert rb["applied"] is True
    assert json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8")) == original_hooks


def test_agy_hook_install_and_cli_roundtrip(tmp_path: Path, capsys) -> None:
    gemini_cfg = tmp_path / ".gemini" / "config"
    gemini_cfg.mkdir(parents=True)
    existing = {"custom-lint": {"enabled": True, "PostToolUse": []}}
    (gemini_cfg / "hooks.json").write_text(json.dumps(existing), encoding="utf-8")

    # CLI install with --no-session-start (for AGY 1.2.x compatibility)
    assert main(["hooks", "install", "-p", "agy", "-c", str(gemini_cfg), "-S", "-a", "-j"]) == 0
    inst_out = json.loads(capsys.readouterr().out)
    assert inst_out["applied"] is True
    data = json.loads((gemini_cfg / "hooks.json").read_text(encoding="utf-8"))
    assert "custom-lint" in data
    assert "agent_continuity" in data
    assert "SessionStart" not in data["agent_continuity"]
    assert "PreInvocation" in data["agent_continuity"]

    assert main(["hooks", "status", "-p", "agy", "-c", str(gemini_cfg), "-j"]) == 0
    st_out = json.loads(capsys.readouterr().out)
    assert st_out["hooks"][0]["installed"] is True

    assert main(["hooks", "uninstall", "-p", "agy", "-c", str(gemini_cfg), "-a", "-j"]) == 0
    capsys.readouterr()
    assert json.loads((gemini_cfg / "hooks.json").read_text(encoding="utf-8")) == existing
