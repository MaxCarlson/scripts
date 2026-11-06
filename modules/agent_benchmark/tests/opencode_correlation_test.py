import json

import pytest

from agent_benchmark.harbor.opencode_v1 import scoped_opencode_environment


def test_scoped_header_merges_without_changing_route_or_model():
    token = "a" * 40
    env = {
        "OPENCODE_FAKE_VCS": "git",
        "OPENCODE_CONFIG_CONTENT": json.dumps(
            {
                "model": "openai/local-model",
                "provider": {"openai": {"options": {"baseURL": "http://monitor/v1", "headers": {"x-existing": "yes"}}}},
            }
        ),
    }
    result = scoped_opencode_environment(env, command=["opencode", "run"], token=token)
    config = json.loads(result["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == "openai/local-model"
    assert config["provider"]["openai"]["options"]["baseURL"] == "http://monitor/v1"
    assert config["provider"]["openai"]["options"]["headers"] == {
        "x-existing": "yes",
        "x-benchmark-correlation-token": token,
    }
    assert "OPENCODE_FAKE_VCS" not in result
    assert "x-benchmark-correlation-token" not in env.get("OPENCODE_CONFIG_CONTENT", "")


def test_credential_is_not_injected_into_other_commands_and_invalid_tokens_fail():
    env = {"PATH": "x"}
    assert scoped_opencode_environment(env, command=["git", "status"], token="a" * 40) == env
    with pytest.raises(ValueError):
        scoped_opencode_environment(env, command=["opencode", "run"], token="bad")


def test_invalid_existing_inline_config_fails_closed():
    with pytest.raises(ValueError):
        scoped_opencode_environment(
            {"OPENCODE_CONFIG_CONTENT": "not json"}, command=["opencode", "run"], token="a" * 40
        )
