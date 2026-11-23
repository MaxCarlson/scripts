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
    assert p_qwen.base_url == "http://host.docker.internal:1235/v1"

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
    assert p_opencode.base_url == "http://host.docker.internal:1235/v1"

    # 7. Local opencode-v2 defaults
    p_opencode_v2 = plan_benchmark("aider/aider-polyglot", agent="opencode-v2", count=1)
    assert p_opencode_v2.agent == "opencode-v2"
    assert p_opencode_v2.model == "openai/qwen38_23GB"
    assert p_opencode_v2.base_url == "http://host.docker.internal:1235/v1"


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


@pytest.mark.parametrize("agent_name", ["qwen-coder", "opencode", "opencode-v2"])
@pytest.mark.parametrize(
    "bypass_url",
    [
        "http://host.docker.internal:1234/v1",
        "http://localhost:1234/v1",
        "http://127.0.0.1:1234/v1",
        "http://[::1]:1234/v1",
        "http://0.0.0.0:1234/v1",
        "http://localhost:1235/v1",
        "http://127.0.0.1:1235/v1",
        "http://[::1]:1235/v1",
        "http://0.0.0.0:1235/v1",
    ],
)
def test_local_agent_rejects_explicit_bypass_routes(monkeypatch, agent_name: str, bypass_url: str):
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ready"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))

    plan = plan_benchmark("aider/aider-polyglot", agent=agent_name, base_url=bypass_url, count=1)
    assert plan.base_url == bypass_url
    assert plan.readiness.is_runnable is False
    assert len(plan.readiness.blockers) >= 1


@pytest.mark.parametrize(
    "bad_url, expected_fragment",
    [
        ("", "Malformed"),
        ("   ", "Malformed"),
        ("host.docker.internal:1235/v1", "Malformed"),
        ("ftp://host.docker.internal:1235/v1", "Malformed"),
        ("http://host.docker.internal:abc/v1", "Malformed"),
        ("http://host.docker.internal/v1", "Malformed or unverified"),
        ("http://host.docker.internal:1235", "Malformed"),
        ("http://host.docker.internal:1235/v2", "Malformed"),
        ("http://user@host.docker.internal:1235/v1", "Malformed"),
        ("http://host.docker.internal:1235/v1?token=1", "Malformed"),
        ("http://host.docker.internal:8788/v1", "Unverified LLM Monitor"),
        ("http://host.docker.internal:8789/v1", "Unverified LLM Monitor"),
        ("http://host.docker.internal:9999/v1", "Unverified local inference route"),
        ("https://api.example.com/v1", "Unverified local inference route"),
    ],
)
def test_local_agent_rejects_malformed_and_unverified_routes(monkeypatch, bad_url: str, expected_fragment: str):
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ready"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))

    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", base_url=bad_url, count=1)
    assert plan.base_url == bad_url
    assert plan.readiness.is_runnable is False
    assert any(expected_fragment in blocker for blocker in plan.readiness.blockers)


def test_local_agent_accepts_protected_coordinator_route(monkeypatch):
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ready"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))

    for agent_name in ("qwen-coder", "opencode", "opencode-v2"):
        plan = plan_benchmark("aider/aider-polyglot", agent=agent_name, count=1)
        assert plan.base_url == "http://host.docker.internal:1235/v1"
        assert plan.readiness.is_runnable is True
        assert plan.readiness.blockers == ()


def test_cloud_agent_isolation_and_bypass_protection(monkeypatch):
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ready"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    # Default cloud plan remains runnable without base_url
    p_cloud = plan_benchmark("aider/aider-polyglot", agent="codex", count=1)
    assert p_cloud.base_url is None
    assert p_cloud.readiness.is_runnable is True

    # Explicit remote HTTPS endpoint for cloud agent remains runnable
    p_custom = plan_benchmark(
        "aider/aider-polyglot",
        agent="codex",
        base_url="https://api.openai.com/v1",
        count=1,
    )
    assert p_custom.readiness.is_runnable is True

    # Explicit local bypasses are blocked even for cloud agents
    for unsafe_url in (
        "http://host.docker.internal:1234/v1",
        "http://127.0.0.1:1235/v1",
        "http://host.docker.internal:8788/v1",
    ):
        p_unsafe = plan_benchmark("aider/aider-polyglot", agent="codex", base_url=unsafe_url, count=1)
        assert p_unsafe.readiness.is_runnable is False


def test_non_executing_planning_makes_no_network_calls(monkeypatch):
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ready"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))

    import socket

    def fail_connect(*args, **kwargs):
        raise AssertionError("Non-executing planning must not open network connections")

    monkeypatch.setattr(socket, "create_connection", fail_connect)

    plan = plan_benchmark("aider/aider-polyglot", agent="qwen-coder", count=1)
    assert plan.base_url == "http://host.docker.internal:1235/v1"
    assert plan.readiness.is_runnable is True
