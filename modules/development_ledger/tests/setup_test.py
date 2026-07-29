from __future__ import annotations

import json
from pathlib import Path

import pytest

from development_ledger.setup import SetupError, apply_setup, plan_repository_setup


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "modules" / "alpha").mkdir(parents=True)
    (root / "apps" / "web").mkdir(parents=True)
    return root


def test_setup_dry_run_is_non_mutating_and_targets_multiple_scopes(tmp_path: Path):
    root = _repo(tmp_path)

    result = plan_repository_setup(root, scopes=["apps/web"], modules=["alpha"])

    assert not (root / "AGENTS.md").exists()
    assert result.scopes == [".", "apps/web", "modules/alpha"]
    paths = {operation.path for operation in result.operations}
    assert "AGENTS.md" in paths
    assert "modules/alpha/AGENTS.md" in paths
    assert "apps/web/docs/plans/README.md" in paths
    assert ".github/copilot-instructions.md" in paths
    assert ".development-ledger.json" in paths


def test_apply_setup_creates_native_files_docs_and_config(tmp_path: Path):
    root = _repo(tmp_path)
    result = plan_repository_setup(root, modules=["alpha"])

    apply_setup(result)

    assert (root / "AGENTS.md").exists()
    assert (root / "CLAUDE.md").exists()
    assert (root / "GEMINI.md").exists()
    assert (root / ".github" / "copilot-instructions.md").exists()
    assert (root / "docs" / "agent" / "DEVELOPMENT_LEDGER_WORKFLOW.md").exists()
    assert (root / "modules" / "alpha" / "docs" / "HANDOFF.md").exists()
    config = json.loads((root / ".development-ledger.json").read_text(encoding="utf-8"))
    assert [scope["path"] for scope in config["scopes"]] == [".", "modules/alpha"]


def test_existing_agents_content_is_preserved_and_setup_is_idempotent(tmp_path: Path):
    root = _repo(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text("# Existing\n\nKeep this rule.\n", encoding="utf-8")

    first = plan_repository_setup(root, agents=["codex"])
    apply_setup(first)
    first_content = agents.read_text(encoding="utf-8")
    second = plan_repository_setup(root, agents=["codex"])

    assert "Keep this rule." in first_content
    assert first_content.count("development-ledger:managed-instructions:start") == 1
    assert first_content.index("development-ledger:managed-instructions:start") < first_content.index("# Existing")
    assert next(operation for operation in second.operations if operation.path == "AGENTS.md").action == "unchanged"


def test_nested_claude_and_gemini_import_scoped_agents_and_root_workflow(tmp_path: Path):
    root = _repo(tmp_path)
    result = plan_repository_setup(root, modules=["alpha"], agents=["claude", "gemini"])
    apply_setup(result)

    claude = (root / "modules" / "alpha" / "CLAUDE.md").read_text(encoding="utf-8")
    gemini = (root / "modules" / "alpha" / "GEMINI.md").read_text(encoding="utf-8")
    assert "@./AGENTS.md" in claude
    assert "@../../docs/agent/DEVELOPMENT_LEDGER_WORKFLOW.md" in claude
    assert "@./AGENTS.md" in gemini
    assert "@../../docs/agent/DEVELOPMENT_LEDGER_WORKFLOW.md" in gemini


def test_copilot_scope_file_has_apply_to_pattern(tmp_path: Path):
    root = _repo(tmp_path)
    result = plan_repository_setup(root, scopes=["apps/web"], agents=["copilot"])
    apply_setup(result)

    text = (root / ".github" / "instructions" / "development-ledger-apps-web.instructions.md").read_text(
        encoding="utf-8"
    )
    assert 'applyTo: "apps/web/**"' in text
    assert "apps/web/AGENTS.md" in text


def test_unmarked_managed_document_conflicts_unless_forced(tmp_path: Path):
    root = _repo(tmp_path)
    workflow = root / "docs" / "agent" / "DEVELOPMENT_LEDGER_WORKFLOW.md"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("custom content", encoding="utf-8")

    result = plan_repository_setup(root)
    forced = plan_repository_setup(root, force=True)

    assert result.has_conflicts
    assert next(operation for operation in result.operations if operation.path.endswith("DEVELOPMENT_LEDGER_WORKFLOW.md")).action == "conflict"
    assert next(operation for operation in forced.operations if operation.path.endswith("DEVELOPMENT_LEDGER_WORKFLOW.md")).action == "update"


def test_missing_module_and_scope_escape_are_rejected(tmp_path: Path):
    root = _repo(tmp_path)

    with pytest.raises(SetupError, match="does not exist"):
        plan_repository_setup(root, modules=["missing"])
    with pytest.raises(SetupError, match="cannot contain"):
        plan_repository_setup(root, scopes=["../outside"])


def test_all_modules_discovers_immediate_module_directories(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "modules" / "beta").mkdir()

    result = plan_repository_setup(root, all_modules=True, agents=["codex"])

    assert result.scopes == [".", "modules/alpha", "modules/beta"]
