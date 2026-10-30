"""Unit tests for Harbor dataset catalogs, task selection, and deterministic sampling."""

from __future__ import annotations

import pytest

from agent_benchmark.harbor import (
    resolve_dataset,
    select_tasks,
)


def test_resolve_dataset():
    # Canonical IDs
    d1 = resolve_dataset("aider/aider-polyglot")
    assert d1.id == "aider/aider-polyglot"
    assert "python" in d1.supported_languages
    assert len(d1.all_tasks) > 200

    d2 = resolve_dataset("terminal-bench/terminal-bench@4.0.0")
    assert d2.id == "terminal-bench/terminal-bench@4.0.0"
    assert len(d2.all_tasks) == 5

    # Short / alias names
    d3 = resolve_dataset("aider-polyglot")
    assert d3.id == "aider/aider-polyglot"

    with pytest.raises(KeyError, match="Unknown dataset"):
        resolve_dataset("nonexistent-dataset-xyz")


def test_select_tasks_language_filter():
    desc = resolve_dataset("aider/aider-polyglot")
    python_tasks = select_tasks(desc, language="python")
    assert len(python_tasks) > 0
    assert all("_python_" in t or t.startswith("python/") for t in python_tasks)

    cpp_tasks = select_tasks(desc, language="cpp")
    assert len(cpp_tasks) > 0
    assert all("_cpp_" in t or t.startswith("cpp/") for t in cpp_tasks)

    with pytest.raises(ValueError, match="No tasks found for language"):
        select_tasks(desc, language="brainfuck")


def test_select_tasks_explicit_ids():
    desc = resolve_dataset("aider/aider-polyglot")
    selected = select_tasks(desc, task_ids=["polyglot_python_proverb", "polyglot_python_grep"])
    assert "polyglot_python_proverb" in selected
    assert "polyglot_python_grep" in selected
    assert len(selected) == 2

    with pytest.raises(ValueError, match="Task ID 'unknown_task_123' not found"):
        select_tasks(desc, task_ids=["unknown_task_123"])


def test_deterministic_seed_sampling():
    desc = resolve_dataset("aider/aider-polyglot")
    # Same seed + count produces identical task list
    sample1 = select_tasks(desc, language="python", count=5, seed=12345)
    sample2 = select_tasks(desc, language="python", count=5, seed=12345)
    assert sample1 == sample2
    assert len(sample1) == 5

    # Different seed produces different subset
    sample3 = select_tasks(desc, language="python", count=5, seed=99999)
    assert sample1 != sample3
