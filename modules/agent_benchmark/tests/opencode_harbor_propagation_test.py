"""Offline proof of the production Harbor-to-OpenCode correlation handoff."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import replace
import hmac
import json
import subprocess
import sys

import httpx
from fastapi import FastAPI

from agent_benchmark.harbor import plan_benchmark
from agent_benchmark.harbor import runner as harbor_runner
from agent_benchmark.harbor.opencode_v1 import scoped_opencode_environment
from llm_monitor.gateway import OpenAIInferenceGateway
from llm_monitor.inference_correlation import ExecutionCredentialRegistry
from llm_monitor.gateway import RequestEventHub
from llm_monitor.live_store import LiveInferenceStore


def test_harbor_child_environment_reaches_opencode_and_verified_gateway(monkeypatch, tmp_path):
    real_subprocess_run = subprocess.run
    registry = ExecutionCredentialRegistry()
    context, credential = registry.register(
        "synthetic-run", "task-alpha", "attempt-1", repetition_id="0", variant_id="variant-a"
    )
    second_context, second_credential = registry.register(
        "synthetic-run", "task-alpha", "attempt-2", repetition_id="1", variant_id="variant-a"
    )
    assert context.execution_id != second_context.execution_id
    assert credential != second_credential

    original_config = {
        "model": "openai/synthetic-model",
        "provider": {
            "openai": {
                "options": {
                    "baseURL": "http://127.0.0.1:4196/v1",
                    "headers": {"x-existing": "preserved"},
                }
            },
            "unrelated": {"options": {"headers": {"x-other": "untouched"}}},
        },
        "agent": {"name": "synthetic-policy"},
    }
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", json.dumps(original_config))
    monkeypatch.setenv("BENCHMARK_CORRELATION_TOKEN", "ambient-value-must-not-win")

    plan = plan_benchmark(
        "aider/aider-polyglot",
        agent="opencode",
        model="openai/synthetic-model",
        base_url="http://127.0.0.1:4196/v1",
        task_ids=["polyglot_python_beer-song"],
    )
    plan = replace(plan, readiness=replace(plan.readiness, blockers=()))
    from agent_benchmark import study_network_policy

    registry_path = tmp_path / "registry.json"
    registry_path.write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "study"
    task_path = tmp_path / plan.selected_tasks[0]
    task_path.mkdir()
    manifest = {
        "provenance": {
            "effective_base_url": plan.base_url,
            "study_network": {"network_policy": study_network_policy.NETWORK_POLICY},
        },
        "prompt_policy": None,
    }
    network_snapshot = {
        "source_git_url": study_network_policy._SOURCE_GIT_URL,
        "source_revision": study_network_policy._SOURCE_REVISION,
        "network_policy": study_network_policy.NETWORK_POLICY,
    }
    monkeypatch.setattr(harbor_runner, "_require_study_network_qualification", lambda *_: None)
    monkeypatch.setattr(harbor_runner, "check_docker_readiness", lambda: (True, "mocked"))
    monkeypatch.setattr(harbor_runner, "check_harbor_readiness", lambda: (True, "mocked"))
    monkeypatch.setattr(
        "agent_benchmark.study_network_policy.verify_study_network_manifest",
        lambda *_: (task_path, network_snapshot),
    )
    monkeypatch.setattr(
        "agent_benchmark.suite_revision.verify_saved_registry_snapshot",
        lambda *_: registry_path.resolve(),
    )
    monkeypatch.setattr("agent_benchmark.study_task_integrity.verify_study_task_trees", lambda *_: None)
    monkeypatch.setattr(harbor_runner, "command_lock", lambda _state: nullcontext())

    captured = {}

    class StopBeforeHarbor(Exception):
        pass

    def fake_harbor_process(command, *, env, **_kwargs):
        captured.update(command=command, env=dict(env))
        raise StopBeforeHarbor("simulated Harbor process boundary")

    monkeypatch.setattr(harbor_runner.subprocess, "run", fake_harbor_process)
    try:
        harbor_runner.execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=tmp_path / "jobs",
            state_dir=tmp_path / "state",
            registry_path=registry_path,
            study_adapter=True,
            study_manifest=manifest,
            study_run_dir=run_dir,
            correlation_credential=credential,
        )
    except RuntimeError as error:
        assert "simulated Harbor process boundary" in str(error)
    else:
        raise AssertionError("fake Harbor process boundary was not reached")

    assert hmac.compare_digest(captured["env"]["BENCHMARK_CORRELATION_TOKEN"], credential)
    assert not hmac.compare_digest(captured["env"]["BENCHMARK_CORRELATION_TOKEN"], "ambient-value-must-not-win")
    assert "--agent" in captured["command"]
    assert "agent_benchmark.harbor.opencode_v1:OpenCodeV1" in captured["command"]

    # This is the same production environment builder called by OpenCodeV1.exec_as_agent.
    opencode_env = scoped_opencode_environment(
        captured["env"], command=["opencode", "run"], token=captured["env"]["BENCHMARK_CORRELATION_TOKEN"]
    )
    child_probe = (
        "import json,os; c=json.loads(os.environ['OPENCODE_CONFIG_CONTENT']); "
        "o=c['provider']['openai']['options']; "
        "print(json.dumps({'model':c['model'],'baseURL':o['baseURL'],'headers':o['headers'],"
        "'other':c['provider']['unrelated']['options']['headers'],'agent':c['agent']['name']}))"
    )
    child = real_subprocess_run(
        [sys.executable, "-c", child_probe], env=opencode_env, capture_output=True, text=True, timeout=10
    )
    assert child.returncode == 0
    child_config = json.loads(child.stdout)
    assert child_config["model"] == "openai/synthetic-model"
    assert child_config["baseURL"] == "http://127.0.0.1:4196/v1"
    assert child_config["headers"]["x-existing"] == "preserved"
    assert hmac.compare_digest(child_config["headers"]["x-benchmark-correlation-token"], credential)
    assert child_config["other"] == {"x-other": "untouched"}
    assert child_config["agent"] == "synthetic-policy"
    assert credential not in str(captured["command"])
    assert credential not in json.dumps(manifest)
    assert credential not in json.dumps(original_config)

    # A later attempt starts from its own environment; the previous header cannot persist.
    later_env = dict(captured["env"])
    later_env["OPENCODE_CONFIG_CONTENT"] = json.dumps(original_config)
    later_env.pop("BENCHMARK_CORRELATION_TOKEN", None)
    later = scoped_opencode_environment(later_env, command=["opencode", "run"], token=None)
    assert (
        "x-benchmark-correlation-token"
        not in json.loads(later["OPENCODE_CONFIG_CONTENT"])["provider"]["openai"]["options"]["headers"]
    )

    seen_upstream = []

    def upstream(request):
        seen_upstream.append(dict(request.headers))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    store = LiveInferenceStore()
    gateway = OpenAIInferenceGateway(
        "http://127.0.0.1:1234",
        store,
        RequestEventHub(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        correlation_registry=registry,
    )
    app = FastAPI()
    app.include_router(gateway.router())

    async def fake_completion():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={"model": child_config["model"], "messages": [{"role": "user", "content": "synthetic"}]},
                headers={"x-benchmark-correlation-token": child_config["headers"]["x-benchmark-correlation-token"]},
            )
            assert response.status_code == 200

    asyncio.run(fake_completion())
    recorded = store.requests()
    assert len(recorded) == 1
    assert recorded[0].benchmark_correlation == context.to_dict()
    assert registry.requests("attempt-1")["request_ids"] == [recorded[0].request_id]
    assert "x-benchmark-correlation-token" not in seen_upstream[0]
    registry.complete("attempt-1", "harbor-native-trial-7")
    reconciled = registry.requests("attempt-1")
    assert reconciled["trial_id"] == "harbor-native-trial-7"
    assert reconciled["context"]["execution_id"] == "attempt-1"
