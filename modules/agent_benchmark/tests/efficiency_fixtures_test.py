"""Offline validation for the fixed Local Agent Efficiency task suite."""
from __future__ import annotations

import json
from pathlib import Path

from agent_benchmark.evidence import capture, load_task, prepare_workspace, verify
from agent_benchmark.tool_profile import FILE_PROFILE, RETRIEVAL_PROFILE, STRUCTURAL_PROFILE

TASKS = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks"
FIXTURE_IDS = ("py-repository-investigation", "py-focused-bug-fix", "py-multifile-change",
               "py-test-development")


def _reference(task_id: str, root: Path) -> None:
    if task_id == "py-repository-investigation":
        (root / "answer.json").write_text(json.dumps({"retryable_statuses": [429, 503],
            "delay_rule": "min(exponential_backoff, max_delay)"}), encoding="utf-8")
    elif task_id == "py-focused-bug-fix":
        (root / "score.py").write_text("def clamp_score(score):\n    return max(0, min(score, 100))\n", encoding="utf-8")
    elif task_id == "py-multifile-change":
        (root / "retry_config.py").write_text("MAX_RETRIES = 5\n", encoding="utf-8")
        (root / "client.py").write_text(
            "from retry_config import MAX_RETRIES\nRETRYABLE_STATUSES = (429, 503)\n\n"
            "def retry_count(status):\n    return MAX_RETRIES if status in RETRYABLE_STATUSES else 0\n",
            encoding="utf-8")
    elif task_id == "py-test-development":
        (root / "tests/test_normalize.py").write_text(
            "import sys, unittest\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parents[1] / 'src'))\n"
            "from normalize import normalize\n\nclass NormalizeTests(unittest.TestCase):\n"
            "    def test_trims(self): self.assertEqual(normalize('  abc  '), 'abc')\n"
            "    def test_collapses(self): self.assertEqual(normalize('a\\t  b'), 'a b')\n"
            "    def test_empty(self): self.assertEqual(normalize(''), '')\n"
            "    def test_unicode(self): self.assertEqual(normalize(' λ  雪 '), 'λ 雪')\n\n"
            "if __name__ == '__main__': unittest.main()\n", encoding="utf-8")


def test_efficiency_fixtures_are_distinct_fixed_and_matched(tmp_path):
    ids = tuple(path.name for path in sorted(TASKS.iterdir())
                if path.is_dir() and path.name in FIXTURE_IDS)
    assert ids == tuple(sorted(FIXTURE_IDS))
    categories = set()
    profiles = (FILE_PROFILE, RETRIEVAL_PROFILE, STRUCTURAL_PROFILE)
    for task_id in FIXTURE_IDS:
        task_dir = TASKS / task_id
        task = load_task(task_dir)
        categories.add(task.category)
        manifest = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert manifest["time_budget_seconds"] == 120
        assert set(manifest["allowed_paths"]).isdisjoint(manifest["forbidden_paths"])
        assert (task_dir / "verifier/check.py").is_file()
        assert (task_dir / "instruction.md").is_file()

        # Each condition starts from the same immutable task seed and task hash.
        seed_hash = None
        for profile in profiles:
            workspace = tmp_path / task_id / profile
            prepare_workspace(task, workspace)
            snapshot = capture(workspace, tmp_path / f"{task_id}-{profile}-snapshot")
            if seed_hash is None:
                seed_hash = snapshot.tree_hash
            else:
                assert snapshot.tree_hash == seed_hash
        assert seed_hash
    assert len(categories) == 4


def test_all_fixture_verifiers_accept_reference_solutions_and_reject_seed(tmp_path):
    for task_id in FIXTURE_IDS:
        task = load_task(TASKS / task_id)
        workspace = tmp_path / task_id / "candidate"
        prepare_workspace(task, workspace)
        failed_snapshot = capture(workspace, tmp_path / task_id / "failed-snapshot")
        failed = verify(failed_snapshot, task.verifier, tmp_path / task_id / "failed-verification")
        assert failed.status == "failed", (task_id, failed)

        _reference(task_id, workspace)
        passed_snapshot = capture(workspace, tmp_path / task_id / "passed-snapshot")
        passed = verify(passed_snapshot, task.verifier, tmp_path / task_id / "passed-verification")
        assert passed.status == "passed", (task_id, passed)


def test_fixture_runs_are_confined_to_pytest_owned_temporary_tree(tmp_path):
    task = load_task(TASKS / FIXTURE_IDS[0])
    workspace = tmp_path / "owned-workspace"
    prepare_workspace(task, workspace)
    assert workspace.is_dir() and workspace.resolve().is_relative_to(tmp_path.resolve())
