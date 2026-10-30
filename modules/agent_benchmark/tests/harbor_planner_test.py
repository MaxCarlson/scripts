"""Unit tests for non-executing Harbor evaluation planning and readiness checks."""

from __future__ import annotations

import pytest

from agent_benchmark.harbor import (
    plan_benchmark,
    verify_agent_readiness,
)


def test_plan_benchmark_deterministic():
    plan1 = plan_benchmark(
        "aider/aider-polyglot",
        agent="oracle",
        model="default",
        language="python",
        count=5,
        repetitions=2,
        seed=42,
    )

    plan2 = plan_benchmark(
        "aider/aider-polyglot",
        agent="oracle",
        model="default",
        language="python",
        count=5,
        repetitions=2,
        seed=42,
    )

    assert plan1.selected_tasks == plan2.selected_tasks
    assert len(plan1.selected_tasks) == 5
    assert plan1.repetitions == 2
    assert plan1.projected_trials == 10  # 5 tasks * 2 reps
    assert plan1.scoring_protocol == "single-attempt-v1"

    # Plan dictionary is serializable and preserves provenance
    p_dict = plan1.to_dict()
    assert p_dict["selected_tasks_count"] == 5
    assert p_dict["projected_trials"] == 10
    assert p_dict["seed"] == 42
    assert "readiness" in p_dict


def test_agent_readiness_supported():
    ok, msg = verify_agent_readiness("oracle")
    assert ok is True
    assert "Authoritative task reference solution" in msg

    ok, msg = verify_agent_readiness("codex")
    assert ok is True

    ok, msg = verify_agent_readiness("antigravity-cli")
    assert ok is True

    ok, msg = verify_agent_readiness("qwen-coder")
    assert ok is True

    ok, msg = verify_agent_readiness("completely_fake_agent")
    assert ok is False
    assert "Unsupported Harbor agent" in msg


def test_invalid_plan_inputs():
    with pytest.raises(ValueError, match="Repetitions must be a positive integer"):
        plan_benchmark("aider/aider-polyglot", repetitions=0)
