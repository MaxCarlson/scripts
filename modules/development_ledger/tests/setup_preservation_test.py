from __future__ import annotations

from pathlib import Path

from development_ledger.setup import apply_setup, plan_repository_setup


def test_existing_docs_readmes_and_handoff_are_preserved(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "docs" / "plans").mkdir(parents=True)
    (root / "docs" / "README.md").write_text("custom docs\n", encoding="utf-8")
    (root / "docs" / "plans" / "README.md").write_text("custom plans\n", encoding="utf-8")
    (root / "docs" / "HANDOFF.md").write_text("active handoff\n", encoding="utf-8")

    result = plan_repository_setup(root, agents=["codex"])

    assert not result.has_conflicts
    apply_setup(result)
    assert (root / "docs" / "README.md").read_text(encoding="utf-8") == "custom docs\n"
    assert (root / "docs" / "plans" / "README.md").read_text(encoding="utf-8") == "custom plans\n"
    assert (root / "docs" / "HANDOFF.md").read_text(encoding="utf-8") == "active handoff\n"


def test_existing_agent_file_with_broken_marker_blocks_application(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text(
        "# Existing\n\n<!-- development-ledger:managed-instructions:start -->\nbroken\n",
        encoding="utf-8",
    )

    result = plan_repository_setup(root, agents=["codex"])

    assert result.has_conflicts
    operation = next(item for item in result.operations if item.path == "AGENTS.md")
    assert operation.action == "conflict"
