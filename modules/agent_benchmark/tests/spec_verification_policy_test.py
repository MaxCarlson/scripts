"""Offline checks for policy bytes and template validation."""

import hashlib

import pytest

from agent_benchmark.spec_verification_policy import load_policy, verify_frozen_policy


def _study_run_fixture(tmp_path, monkeypatch, policy_file=None):
    import hashlib
    import json
    from agent_benchmark.suite import build_manifest
    from agent_benchmark.suite_revision import HARBOR_VERSION, include_registry_resolution

    task_id = "polyglot_python_beer-song"
    source_task = tmp_path / "harbor-cache" / task_id
    (source_task / "tests").mkdir(parents=True)
    (source_task / "task.toml").write_text(
        "[verifier]\ntimeout_sec = 1800\n[agent]\ntimeout_sec = 1800\n[environment]\ncpus = 1\n",
        encoding="utf-8",
    )
    (source_task / "instruction.md").write_bytes(b"Frozen task instructions.\n")
    (source_task / "tests" / "test_contract.py").write_bytes(b"assert True\n")
    verifier_hash = hashlib.sha256()
    verifier_hash.update(b"tests/test_contract.py\0")
    verifier_hash.update(hashlib.sha256(b"assert True\n").digest())
    monkeypatch.setitem(
        __import__("agent_benchmark.study_task_integrity", fromlist=["EXPECTED"]).EXPECTED,
        task_id,
        ("a" * 64, verifier_hash.hexdigest()),
    )
    source_revision = "f30b14415dd733c83627204bad0af69a89ceb46f"
    source_git_url = "https://github.com/laude-institute/harbor-datasets.git"
    custom = tmp_path / "cohort.json"
    custom.write_text(
        json.dumps(
            {
                "id": "test-study",
                "dataset": "aider/aider-polyglot",
                "source_revision": source_revision,
                "tasks": [task_id],
            }
        ),
        encoding="utf-8",
    )
    args = dict(
        cohort=None,
        manifest=custom,
        agent="opencode",
        model="openai/model",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
        study_adapter=True,
    )
    plan = build_manifest(**args, prompt_policy_file=policy_file)
    registry_bytes = b'{"test":"frozen"}\n'
    resolution = {
        "verified": True,
        "harbor_version": HARBOR_VERSION,
        "registry_url": "https://example.invalid/registry.json",
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "registry_path": "registry/registry.json",
        "expected_revision": source_revision,
        "tasks": [
            {
                "task_id": task_id,
                "git_url": source_git_url,
                "git_commit_id": source_revision,
                "git_path": "datasets/aider_polyglot/" + task_id,
            }
        ],
    }
    plan = include_registry_resolution(plan, resolution)
    monkeypatch.setattr(
        "agent_benchmark.study_task_integrity.verify_study_task_trees",
        lambda _: [
            {
                "task_id": task_id,
                "task_sha256": "a" * 64,
                "verifier_sha256": verifier_hash.hexdigest(),
                "task_root": str(source_task.resolve()),
            }
        ],
    )
    return args, plan, registry_bytes


def _create_study_run(tmp_path, monkeypatch, policy_file=None):
    from agent_benchmark.suite import create_run

    args, plan, registry_bytes = _study_run_fixture(tmp_path, monkeypatch, policy_file)
    run = create_run(
        tmp_path, **args, planned_manifest=plan, prompt_policy_file=policy_file, registry_snapshot=registry_bytes
    )
    return args, plan, run


def test_policy_bytes_are_frozen_in_template(tmp_path):
    path = tmp_path / "policy.md"
    content = b"check the specification\n"
    path.write_bytes(content)
    raw, template, identity = load_policy(path)
    assert raw == content
    assert template == b'{{ instruction }}\n\n{{ "check the specification\\n" }}'
    assert identity["sha256"] == hashlib.sha256(content).hexdigest()
    assert identity["template_sha256"] == hashlib.sha256(template).hexdigest()


@pytest.mark.parametrize("content", [b"", b"\xff", b"{{ x }}", b"{% raw %}", b"x" * 16385])
def test_invalid_policy_is_rejected(tmp_path, content):
    path = tmp_path / "policy.md"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        load_policy(path)


def test_frozen_run_ignores_original_and_detects_drift(tmp_path, monkeypatch):
    source = tmp_path / "input.md"
    source.write_bytes(b"verify requirements\n")
    _, plan, run = _create_study_run(tmp_path, monkeypatch, source)
    source.write_bytes(b"changed")
    template = verify_frozen_policy(run, plan["prompt_policy"])
    assert template.read_bytes().endswith(b'"verify requirements\\n" }}')
    (run / "policy" / "source.md").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        verify_frozen_policy(run, plan["prompt_policy"])


def test_changed_policy_before_run_creation_fails(tmp_path):
    from agent_benchmark.suite import build_manifest, create_run

    source = tmp_path / "input.md"
    source.write_bytes(b"original")
    args = dict(
        cohort="aider-python-10",
        agent="opencode",
        model="openai/model",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
    )
    plan = build_manifest(**args, prompt_policy_file=source)
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed since planning"):
        create_run(tmp_path, **args, planned_manifest=plan, prompt_policy_file=source)


def test_prompt_template_command_is_opt_in(tmp_path, monkeypatch):
    from agent_benchmark.harbor.runner import build_harbor_command
    from agent_benchmark.harbor.planner import plan_benchmark
    from agent_benchmark.study_network_policy import NETWORK_POLICY

    monkeypatch.setattr("agent_benchmark.harbor.runner.shutil.which", lambda _: "harbor")
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", task_ids=["polyglot_python_beer-song"])
    task_path = tmp_path / "polyglot_python_beer-song"
    task_path.mkdir()
    command_args = dict(
        jobs_dir=tmp_path,
        study_adapter=True,
        study_task_path=task_path,
        study_source_git_url="https://github.com/laude-institute/harbor-datasets.git",
        study_source_revision="f30b14415dd733c83627204bad0af69a89ceb46f",
        study_network_policy=NETWORK_POLICY,
    )
    baseline = build_harbor_command(plan, **command_args)
    template = tmp_path / "template.j2"
    template.write_text("{{ instruction }}", encoding="utf-8")
    intervention = build_harbor_command(plan, **command_args, prompt_template_path=template)
    assert "agent_benchmark.harbor.opencode_v1:OpenCodeV1" in baseline
    assert "disable_web_search=true" in baseline
    assert not any(arg.startswith("prompt_template_path=") for arg in baseline)
    assert f"prompt_template_path={template.resolve()}" in intervention


def test_literal_render_preserves_whitespace(tmp_path):
    jinja = pytest.importorskip("jinja2")
    source = tmp_path / "source.md"
    source.write_bytes("policy\r\n😀\n\n".encode())
    _, template, _ = load_policy(source)
    rendered = (
        jinja.Environment(undefined=jinja.StrictUndefined).from_string(template.decode()).render(instruction="  task\n")
    )
    assert rendered == "  task\n\n\npolicy\r\n😀\n\n"


def test_policy_requires_opencode_and_baseline_has_explicit_identity(tmp_path):
    from agent_benchmark.suite import build_manifest

    args = dict(
        cohort="aider-python-10",
        model="openai/model",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
    )
    baseline = build_manifest(**args, agent="opencode", study_adapter=True)
    assert baseline["prompt_policy"]["id"] == "sv0-unmodified-v1"
    with pytest.raises(ValueError, match="requires opencode"):
        build_manifest(**args, agent="qwen-coder", study_adapter=True)


def test_planned_conditions_differ_only_in_declared_policy(tmp_path):
    from agent_benchmark.suite import build_manifest

    source = tmp_path / "policy.md"
    source.write_text("verify requirements", encoding="utf-8")
    args = dict(
        cohort="aider-python-10",
        model="openai/model",
        base_url=None,
        api_format=None,
        llm_monitor=False,
        recording="off",
        agent="opencode",
        study_adapter=True,
        study_repetition=1,
        study_seed=20261102,
    )
    left = build_manifest(**args)
    right = build_manifest(**args, prompt_policy_file=source)
    assert {key for key in left if left[key] != right[key]} == {"prompt_policy", "manifest_sha256"}
    assert left["study_web_access"] == right["study_web_access"]
    assert all(row["content_fingerprint"] is None for row in left["task_fingerprints"])


def test_sv0_sv1_run_artifacts_share_network_snapshot_and_keep_policy_freeze(tmp_path, monkeypatch):
    _, _, sv0_run = _create_study_run(tmp_path / "sv0", monkeypatch)
    source = tmp_path / "sv1-policy.md"
    source.write_bytes(b"Verify from the task requirements.\n")
    _, _, sv1_run = _create_study_run(tmp_path / "sv1", monkeypatch, source)
    import json

    sv0 = json.loads((sv0_run / "manifest.json").read_text(encoding="utf-8"))
    sv1 = json.loads((sv1_run / "manifest.json").read_text(encoding="utf-8"))
    assert sv0["prompt_policy"]["id"] == "sv0-unmodified-v1"
    assert sv1["prompt_policy"]["id"] == "sv1-specification-verification-v1"
    assert sv0["provenance"]["study_network"] == sv1["provenance"]["study_network"]
    assert (
        sv0_run
        / sv0["provenance"]["study_network"]["task_snapshots"]["polyglot_python_beer-song"]["snapshot_path"]
        / "task.toml"
    ).is_file()
    assert not (sv0_run / "policy").exists()
    assert (sv1_run / "policy" / "source.md").read_bytes() == source.read_bytes()
    assert sv0["manifest_sha256"] != sv1["manifest_sha256"]


def test_network_snapshot_drift_fails_before_harbor_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_benchmark.harbor.runner._require_study_network_qualification", lambda *_: None)
    from contextlib import nullcontext
    from dataclasses import replace
    import json
    from agent_benchmark.harbor.planner import plan_benchmark
    from agent_benchmark.harbor.runner import execute_harbor_run

    _, _, run_dir = _create_study_run(tmp_path, monkeypatch)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_docker_readiness", lambda: (True, "ready"))
    monkeypatch.setattr("agent_benchmark.harbor.planner.check_harbor_readiness", lambda: (True, "0.25.0"))
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", task_ids=["polyglot_python_beer-song"])
    plan = replace(plan, readiness=replace(plan.readiness, blockers=()))
    snapshot = manifest["provenance"]["study_network"]["task_snapshots"]["polyglot_python_beer-song"]
    task_toml = run_dir / snapshot["snapshot_path"] / "task.toml"
    task_toml.write_bytes(task_toml.read_bytes().replace(b'"allowlist"', b'"public"'))
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_docker_readiness", lambda: (True, "ready"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_harbor_readiness", lambda: (True, "0.25.0"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.shutil.which", lambda _: "harbor")
    monkeypatch.setattr("agent_benchmark.harbor.runner.command_lock", lambda _: nullcontext())
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.subprocess.run",
        lambda *args, **kwargs: pytest.fail("Harbor dispatch must not occur on policy drift"),
    )
    registry = run_dir / "registry" / "registry.json"
    with pytest.raises(ValueError, match="snapshot changed"):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=tmp_path / "jobs",
            state_dir=tmp_path / "state",
            study_adapter=True,
            study_manifest=manifest,
            study_policy=manifest["prompt_policy"],
            registry_path=registry,
            study_run_dir=run_dir,
        )


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


def test_resume_refuses_modified_study_manifest(tmp_path, monkeypatch):
    import json
    from agent_benchmark.suite import execute_pending

    _, _, run = _create_study_run(tmp_path, monkeypatch)
    path = run / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("study_adapter")
    path.write_text(json.dumps(data), encoding="utf-8")
    called = []
    with pytest.raises(ValueError, match="manifest changed"):
        execute_pending(run, execute=True, executor=lambda *args: called.append(args))
    assert not called


def test_study_dispatch_uses_import_path_without_patching_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_benchmark.harbor.runner._require_study_network_qualification", lambda *_: None)
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
    monkeypatch.setattr(
        "agent_benchmark.harbor.runner.ensure_harbor_opencode_compatibility",
        lambda: pytest.fail("shared adapter patch was called"),
    )
    _, _, run_dir = _create_study_run(tmp_path, monkeypatch)
    manifest = __import__("json").loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    registry = run_dir / "registry" / "registry.json"
    monkeypatch.setattr("agent_benchmark.suite_revision.verify_saved_registry_snapshot", lambda *_: registry.resolve())
    monkeypatch.setattr("agent_benchmark.study_task_integrity.verify_study_task_trees", lambda _: [])
    captured = []

    def run(cmd, **kwargs):
        captured.append((cmd, kwargs["env"]))
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("agent_benchmark.harbor.runner.subprocess.run", run)
    plan = plan_benchmark("aider/aider-polyglot", agent="opencode", task_ids=["polyglot_python_beer-song"])
    with pytest.raises(RuntimeError, match="produced no job directory"):
        execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=tmp_path / "jobs",
            state_dir=tmp_path / "state",
            study_adapter=True,
            study_manifest=manifest,
            study_policy=manifest["prompt_policy"],
            registry_path=registry,
            study_run_dir=run_dir,
        )
    assert "agent_benchmark.harbor.opencode_v1:OpenCodeV1" in captured[0][0]
    assert "agent_benchmark" in captured[0][1]["PYTHONPATH"]
    assert "benchmark_core" in captured[0][1]["PYTHONPATH"]


def test_resume_refuses_modified_template_before_executor(tmp_path, monkeypatch):
    from agent_benchmark.suite import execute_pending

    source = tmp_path / "policy.md"
    source.write_text("verify", encoding="utf-8")
    _, plan, run = _create_study_run(tmp_path, monkeypatch, source)
    source.write_text("changed original", encoding="utf-8")
    (run / "policy" / "prompt-template.j2").write_text("changed", encoding="utf-8")
    called = []
    with pytest.raises(ValueError, match="changed"):
        execute_pending(run, execute=True, executor=lambda *args: called.append(args))
    assert not called
