from pathlib import Path

import pytest

from agent_sync.config import default_config
from agent_sync.errors import PolicyError
from agent_sync.policy.delegation import enforce_external_policy, select_worker
from agent_sync.tasks import DelegationTask


def test_policy_blocks_worker_without_allow_external() -> None:
    worker = default_config().get_worker("local-lmstudio")
    with pytest.raises(PolicyError):
        enforce_external_policy(allow_external=False, worker=worker)


def test_select_worker_prefers_local_for_summary(tmp_path: Path) -> None:
    task = DelegationTask(task_type="summarize", prompt="Summarize this.", repo_root=tmp_path)
    worker = select_worker(default_config(), task, preferred="auto")
    assert worker.name == "local-lmstudio"


def test_select_worker_prefers_strong_worker_for_verify(tmp_path: Path) -> None:
    task = DelegationTask(task_type="verify", prompt="Verify this.", repo_root=tmp_path, high_stakes=True)
    worker = select_worker(default_config(), task, preferred="auto")
    assert worker.name in {"claude", "codex", "gemini"}
    assert worker.capability_score >= 0.85
