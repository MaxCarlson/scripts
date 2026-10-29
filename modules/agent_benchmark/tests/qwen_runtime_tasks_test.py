"""Independent verifier contract tests for the Qwen runtime task additions."""
from __future__ import annotations

import json
from pathlib import Path

from agent_benchmark.evidence import capture, load_task, prepare_workspace, verify

TASKS = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _reference(task_id: str, root: Path) -> None:
    if task_id == "qwen-file-creation":
        (root / "src").mkdir()
        (root / "src/greeting.py").write_text(
            "def greet(name):\n    name = name.strip()\n    return f'Hello, {name}!' if name else 'Hello!'\n",
            encoding="utf-8",
        )
    elif task_id == "qwen-existing-code-modification":
        (root / "src/names.py").write_text(
            "def display_name(first, last, *, separator=' '):\n"
            "    return separator.join(part for part in (first.strip(), last.strip()) if part)\n",
            encoding="utf-8",
        )
    elif task_id == "qwen-async-behavior":
        (root / "src/async_jobs.py").write_text(
            "import asyncio\n\n"
            "async def run_bounded(items, worker, max_concurrency):\n"
            "    if max_concurrency <= 0:\n        raise ValueError('max_concurrency must be positive')\n"
            "    semaphore = asyncio.Semaphore(max_concurrency)\n"
            "    async def run(item):\n"
            "        async with semaphore:\n            return await worker(item)\n"
            "    return await asyncio.gather(*(run(item) for item in items))\n",
            encoding="utf-8",
        )
    elif task_id == "qwen-session-state":
        (root / "src/session_state.py").write_text(
            "TERMINAL = {'succeeded', 'failed', 'cancelled'}\n"
            "TRANSITIONS = {('idle', 'submit'): 'queued', ('queued', 'start'): 'running', "
            "('queued', 'cancel'): 'cancelled', ('running', 'succeed'): 'succeeded', "
            "('running', 'fail'): 'failed', ('running', 'cancel'): 'cancelled'}\n"
            "def transition(state, event):\n"
            "    if state not in {'idle', 'queued', 'running', *TERMINAL}:\n"
            "        raise ValueError('unknown state')\n"
            "    if state in TERMINAL and event == 'reset':\n        return 'idle'\n"
            "    try:\n        return TRANSITIONS[state, event]\n"
            "    except KeyError as error:\n        raise ValueError('invalid transition') from error\n",
            encoding="utf-8",
        )
    else:
        raise AssertionError(f"Unknown fixture: {task_id}")


def test_qwen_tasks_are_valid_fixed_agent_benchmark_fixtures(tmp_path: Path) -> None:
    expected = {"qwen-file-creation", "qwen-existing-code-modification", "qwen-async-behavior",
                "qwen-session-state"}
    for task_id in sorted(expected):
        task = load_task(TASKS / task_id)
        assert task.task_id == task_id
        assert task.opencode_tool_profile == "file-tools-v1"
        assert task.time_budget_seconds == 120
        assert task.allowed_paths
        seed_workspace = tmp_path / task_id / "seed"
        prepare_workspace(task, seed_workspace)
        seed = capture(seed_workspace, tmp_path / task_id / "seed-snapshot")
        failed = verify(seed, task.verifier, tmp_path / task_id / "seed-verification", timeout_seconds=5)
        assert failed.status == "failed", (task_id, failed)

        _reference(task_id, seed_workspace)
        reference = capture(seed_workspace, tmp_path / task_id / "reference-snapshot")
        passed = verify(reference, task.verifier, tmp_path / task_id / "reference-verification", timeout_seconds=10)
        assert passed.status == "passed", (task_id, passed)


def test_six_stage_suite_resolves_only_agent_benchmark_task_bundles() -> None:
    manifest_path = REPO_ROOT / "experiments/qwen_runtime_investigation/taskset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = manifest["tasks"]
    assert [item["id"] for item in tasks] == [
        "qwen-file-creation", "py-focused-bug-fix", "py-test-development",
        "qwen-session-state", "qwen-async-behavior", "py-multifile-change",
    ]
    for item in tasks:
        task_path = (manifest_path.parent / item["path"]).resolve()
        task = load_task(task_path)
        assert task.task_id == item["id"]
        assert list(task.allowed_paths) == item["allowed_paths"]
    assert manifest["execution_policy"]["do_not_expand_as_full_cartesian_product"] is True
