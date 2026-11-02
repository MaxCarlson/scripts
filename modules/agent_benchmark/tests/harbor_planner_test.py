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

def test_agent_defaults_and_isolation():
    # 1. Local qwen-coder defaults
    p_qwen = plan_benchmark("aider/aider-polyglot", agent="qwen-coder", count=1)
    assert p_qwen.agent == "qwen-coder"
    assert p_qwen.model == "qwen38_23GB"
    assert p_qwen.base_url == "http://host.docker.internal:1234/v1"

    # 2. Oracle defaults
    p_oracle = plan_benchmark("aider/aider-polyglot", agent="oracle", count=1)
    assert p_oracle.agent == "oracle"
    assert p_oracle.model == "none"
    assert p_oracle.base_url is None

    # 3. Nop defaults
    p_nop = plan_benchmark("aider/aider-polyglot", agent="nop", count=1)
    assert p_nop.agent == "nop"
    assert p_nop.model == "none"
    assert p_nop.base_url is None

    # 4. Cloud codex defaults
    p_codex = plan_benchmark("aider/aider-polyglot", agent="codex", count=1)
    assert p_codex.agent == "codex"
    assert p_codex.model == "default"
    assert p_codex.base_url is None

    # 5. Cloud antigravity-cli defaults
    p_agy = plan_benchmark("aider/aider-polyglot", agent="antigravity-cli", count=1)
    assert p_agy.agent == "antigravity-cli"
    assert p_agy.model == "default"
    assert p_agy.base_url is None

    # 6. Local opencode defaults
    p_opencode = plan_benchmark("aider/aider-polyglot", agent="opencode", count=1)
    assert p_opencode.agent == "opencode"
    assert p_opencode.model == "openai/qwen38_23GB"
    assert p_opencode.base_url == "http://host.docker.internal:1234/v1" 


def test_cloud_agent_credential_blockers(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p_codex = plan_benchmark("aider/aider-polyglot", agent="codex", count=1)
    assert any("OPENAI_API_KEY must be set in environment" in b for b in p_codex.readiness.blockers)
    assert p_codex.readiness.is_runnable is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    p_codex_auth = plan_benchmark("aider/aider-polyglot", agent="codex", count=1)
    assert not any("OPENAI_API_KEY must be set in environment" in b for b in p_codex_auth.readiness.blockers)

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    p_agy = plan_benchmark("aider/aider-polyglot", agent="antigravity-cli", count=1)
    assert any("GEMINI_API_KEY must be set in environment" in b for b in p_agy.readiness.blockers)
    assert p_agy.readiness.is_runnable is False

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    p_agy_auth = plan_benchmark("aider/aider-polyglot", agent="antigravity-cli", count=1)
    assert not any("GEMINI_API_KEY must be set in environment" in b for b in p_agy_auth.readiness.blockers)


def test_unsupported_agent_configurations():
    # Passing model to oracle
    p_oracle_m = plan_benchmark("aider/aider-polyglot", agent="oracle", model="qwen38_23GB", count=1)
    assert any("does not accept a model parameter" in b for b in p_oracle_m.readiness.blockers)
    assert p_oracle_m.readiness.is_runnable is False

    # Passing base-url to oracle
    p_oracle_u = plan_benchmark("aider/aider-polyglot", agent="oracle", base_url="http://localhost:1234/v1", count=1)
    assert any("does not accept an inference base-url parameter" in b for b in p_oracle_u.readiness.blockers)
    assert p_oracle_u.readiness.is_runnable is False


def test_model_api_format_planning():
    # 1. Accepted canonical format
    p = plan_benchmark(
        "aider/aider-polyglot",
        agent="opencode",
        count=1,
        model_api_format="openai_chat_completions",
    )
    assert p.model_api_format == "openai_chat_completions"
    assert p.to_dict()["model_api_format"] == "openai_chat_completions"

    # 2. Canonicalization from hyphen to underscore
    p_hyphen = plan_benchmark(
        "aider/aider-polyglot",
        agent="opencode",
        count=1,
        model_api_format="openai-chat-completions",
    )
    assert p_hyphen.model_api_format == "openai_chat_completions"

    # 3. Default without override is None
    p_default = plan_benchmark("aider/aider-polyglot", agent="opencode", count=1)
    assert p_default.model_api_format is None
    assert p_default.to_dict()["model_api_format"] is None

    # 4. Invalid format raises ValueError
    import pytest
    with pytest.raises(ValueError, match="Unsupported model API format"):
        plan_benchmark(
            "aider/aider-polyglot",
            agent="opencode",
            count=1,
            model_api_format="unsupported_format_xyz",
        )

    # 5. Blocked for agents that do not accept api-format (oracle / nop)
    p_oracle = plan_benchmark(
        "aider/aider-polyglot",
        agent="oracle",
        count=1,
        model_api_format="openai_chat_completions",
    )
    assert any("does not accept an api-format parameter" in b for b in p_oracle.readiness.blockers)
    assert p_oracle.readiness.is_runnable is False
