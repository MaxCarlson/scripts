from pathlib import Path

from agent_sync.prompting.packs import build_delegation_prompt
from agent_sync.tasks import DelegationTask


def test_build_delegation_prompt_contains_required_headings(tmp_path: Path) -> None:
    task = DelegationTask(
        task_type="review",
        prompt="Review this plan.",
        repo_root=tmp_path,
        context_level="standard",
        high_stakes=True,
    )
    prompt = build_delegation_prompt(task)
    assert "# agent_sync Delegated Task Packet" in prompt
    assert "## Output Contract" in prompt
    assert "Review this plan." in prompt
    assert "High stakes: yes" in prompt
