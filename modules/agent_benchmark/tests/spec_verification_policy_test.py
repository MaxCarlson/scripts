"""Offline checks for policy bytes and template validation."""

import hashlib

import pytest

from agent_benchmark.spec_verification_policy import load_policy, verify_frozen_policy


def test_policy_bytes_are_frozen_in_template(tmp_path):
    path = tmp_path / "policy.md"
    content = b"check the specification\n"
    path.write_bytes(content)
    raw, template, identity = load_policy(path)
    assert raw == content
    assert template == b"{{ instruction }}\n\n" + content + b"{{ '' }}"
    assert identity["sha256"] == hashlib.sha256(content).hexdigest()
    assert identity["template_sha256"] == hashlib.sha256(template).hexdigest()


@pytest.mark.parametrize("content", [b"", b"\xff", b"{{ x }}", b"{% raw %}", b"x" * 16385])
def test_invalid_policy_is_rejected(tmp_path, content):
    path = tmp_path / "policy.md"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        load_policy(path)


def test_frozen_run_ignores_original_and_detects_drift(tmp_path):
    from agent_benchmark.suite import build_manifest, create_run

    source = tmp_path / "input.md"
    source.write_bytes(b"verify requirements\n")
    args = dict(cohort="aider-python-10", agent="opencode", model="openai/model",
                base_url=None, api_format=None, llm_monitor=False, recording="off")
    plan = build_manifest(**args, study_adapter=True, prompt_policy_file=source)
    run = create_run(tmp_path, **args, planned_manifest=plan, prompt_policy_file=source)
    source.write_bytes(b"changed")
    template = verify_frozen_policy(run, plan["prompt_policy"])
    assert template.read_bytes().endswith(b"verify requirements\n{{ '' }}")
    (run / "policy" / "source.md").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        verify_frozen_policy(run, plan["prompt_policy"])


def test_changed_policy_before_run_creation_fails(tmp_path):
    from agent_benchmark.suite import build_manifest, create_run

    source = tmp_path / "input.md"
    source.write_bytes(b"original")
    args = dict(cohort="aider-python-10", agent="opencode", model="openai/model",
                base_url=None, api_format=None, llm_monitor=False, recording="off")
    plan = build_manifest(**args, prompt_policy_file=source)
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed since planning"):
        create_run(tmp_path, **args, planned_manifest=plan, prompt_policy_file=source)


def test_prompt_template_command_is_opt_in(tmp_path, monkeypatch):
    from agent_benchmark.harbor.runner import build_harbor_command
    from agent_benchmark.harbor.planner import plan_benchmark

    monkeypatch.setattr("agent_benchmark.harbor.runner.shutil.which", lambda _: "harbor")
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", count=1)
    baseline = build_harbor_command(plan, jobs_dir=tmp_path, study_adapter=True)
    template = tmp_path / "template.j2"
    template.write_text("{{ instruction }}", encoding="utf-8")
    intervention = build_harbor_command(plan, jobs_dir=tmp_path, study_adapter=True,
                                        prompt_template_path=template)
    assert "agent_benchmark.harbor.opencode_v1:OpenCodeV1" in baseline
    assert "--ak" not in baseline
    assert f"prompt_template_path={template.resolve()}" in intervention


def test_literal_render_preserves_whitespace(tmp_path):
    jinja = pytest.importorskip("jinja2")
    source = tmp_path / "source.md"
    source.write_bytes(b"policy\n\n")
    _, template, _ = load_policy(source)
    rendered = jinja.Environment(undefined=jinja.StrictUndefined).from_string(template.decode()).render(
        instruction="  task\n"
    )
    assert rendered == "  task\n\n\npolicy\n\n"


def test_policy_requires_opencode_and_baseline_has_explicit_identity(tmp_path):
    from agent_benchmark.suite import build_manifest

    args = dict(cohort="aider-python-10", model="openai/model", base_url=None,
                api_format=None, llm_monitor=False, recording="off")
    baseline = build_manifest(**args, agent="opencode", study_adapter=True)
    assert baseline["prompt_policy"]["id"] == "sv0-unmodified-v1"
    with pytest.raises(ValueError, match="requires opencode"):
        build_manifest(**args, agent="qwen-coder", study_adapter=True)


def test_adapter_strips_forced_vcs_and_pins_version(monkeypatch):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    fake = types.ModuleType("harbor.agents.installed.opencode")

    class FakeOpenCode:
        def __init__(self):
            self._version = None

        async def exec_as_agent(self, *args, **kwargs):
            return kwargs["env"]

    fake.OpenCode = FakeOpenCode
    monkeypatch.setitem(sys.modules, "harbor.agents.installed.opencode", fake)
    path = Path(__file__).parents[1] / "agent_benchmark" / "harbor" / "opencode_v1.py"
    spec = importlib.util.spec_from_file_location("isolated_adapter_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = module.OpenCodeV1()
    assert agent._version == "1.19.5"
    env = {"OPENCODE_FAKE_VCS": "git", "OTHER": "value"}
    coroutine = agent.exec_as_agent(None, command="noop", env=env)
    with pytest.raises(StopIteration) as returned:
        coroutine.send(None)
    result = returned.value.value
    assert result == {"OTHER": "value"}
    assert env["OPENCODE_FAKE_VCS"] == "git"


def test_resume_refuses_modified_study_manifest(tmp_path):
    import json
    from agent_benchmark.suite import build_manifest, create_run, execute_pending

    args = dict(cohort="aider-python-10", agent="opencode", model="openai/model",
                base_url=None, api_format=None, llm_monitor=False, recording="off")
    plan = build_manifest(**args, study_adapter=True)
    run = create_run(tmp_path, **args, planned_manifest=plan)
    path = run / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("study_adapter")
    path.write_text(json.dumps(data), encoding="utf-8")
    called = []
    with pytest.raises(ValueError, match="manifest changed"):
        execute_pending(run, execute=True, executor=lambda *args: called.append(args))
    assert not called


def test_study_dispatch_uses_import_path_without_patching_dependencies(tmp_path, monkeypatch):
    from contextlib import nullcontext
    import subprocess
    from agent_benchmark.harbor.planner import plan_benchmark
    from agent_benchmark.harbor.runner import execute_harbor_run

    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ok"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_docker_readiness", lambda: (True, "ok"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_harbor_readiness", lambda: (True, "0.25.0"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.shutil.which", lambda _: "harbor")
    monkeypatch.setattr("agent_benchmark.harbor.runner.command_lock", lambda _: nullcontext())
    monkeypatch.setattr("agent_benchmark.harbor.runner.ensure_harbor_opencode_compatibility",
                        lambda: pytest.fail("shared adapter patch was called"))
    captured = []
    def run(cmd, **kwargs):
        captured.append((cmd, kwargs["env"]))
        return subprocess.CompletedProcess(cmd, 1)
    monkeypatch.setattr("agent_benchmark.harbor.runner.subprocess.run", run)
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", count=1)
    with pytest.raises(RuntimeError, match="produced no job directory"):
        execute_harbor_run(plan, execute=True, output_dir=tmp_path / "out", jobs_dir=tmp_path / "jobs",
                           state_dir=tmp_path / "state", study_adapter=True)
    assert "agent_benchmark.harbor.opencode_v1:OpenCodeV1" in captured[0][0]
    assert "agent_benchmark" in captured[0][1]["PYTHONPATH"]
