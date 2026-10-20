"""Versioned scratch policy: real local files/subprocesses, no model or service calls."""

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from agent_benchmark.evidence import audit_scope, capture, load_task, prepare_workspace, verify
from agent_benchmark.scratch import SCOPE_POLICY, SCRATCH_NAME, is_scratch, temp_environment
from attempt_test import TASK, GOOD, Worker, attempt
from agent_benchmark.lifecycle import DispatchGuard, TerminationDecision, WorkerHandle, cleanup_workspace
from agent_benchmark.results import trial_from_attempt


def history(path, tool="write"):
    return [
        {
            "info": {"id": "assistant"},
            "parts": [
                {
                    "type": "tool",
                    "tool": tool,
                    "callID": "call",
                    "state": {"status": "completed", "input": {"filePath": str(path), "command": "python test.py"}},
                }
            ],
        }
    ]


def test_new_policy_separates_scratch_retains_bytes_and_legacy_stays_strict(tmp_path):
    task = load_task(TASK)
    workspace = tmp_path / "worker"
    prepare_workspace(task, workspace, scope_policy=SCOPE_POLICY)
    assert (workspace / SCRATCH_NAME).is_dir()
    s0 = capture(workspace, tmp_path / "S0")
    scratch = f"{SCRATCH_NAME}/test_grep.py"
    (workspace / scratch).write_text("scratch tests")
    (workspace / "grep.py").write_text(GOOD)
    s1 = capture(workspace, tmp_path / "S1")
    audit = audit_scope(task, workspace, s0, s1, history(scratch), scope_policy=SCOPE_POLICY)
    assert audit.compliance == "compliant" and audit.all_violations == ()
    assert audit.scratch_changed_paths == (scratch,) and audit.task_changed_paths == ("grep.py",)
    assert audit.mutation_events[0].category == "scratch"
    assert s1.files[scratch] == b"scratch tests"
    legacy = audit_scope(task, workspace, s0, s1, history(scratch))
    assert scratch in legacy.all_violations and legacy.scope_policy is None
    # Scratch cannot shadow or contaminate the authoritative verifier's input.
    verification = verify(s1, task.verifier, tmp_path / "verification", scope_policy=SCOPE_POLICY)
    assert verification.status == "passed"
    assert not (tmp_path / "verification/workspace" / SCRATCH_NAME).exists()
    s0.check_intact()
    s1.check_intact()


@pytest.mark.parametrize(
    "target",
    [
        "../outside.txt",
        ".git/config",
        f"{SCRATCH_NAME}/../../outside.txt",
        f"{SCRATCH_NAME}/../instruction.md",
        f"{SCRATCH_NAME}/.git/config",
        f"{SCRATCH_NAME}-other/test.py",
    ],
)
def test_scratch_never_grants_external_protected_or_sibling_paths(tmp_path, target):
    task = load_task(TASK)
    workspace = tmp_path / "worker"
    prepare_workspace(task, workspace, scope_policy=SCOPE_POLICY)
    s0 = capture(workspace, tmp_path / "S0")
    audit = audit_scope(task, workspace, s0, s0, history(target), scope_policy=SCOPE_POLICY)
    assert audit.compliance == "violated" and len(audit.transcript_violations) == 1
    assert not audit.mutation_events[0].in_scope


def test_shared_temp_remains_violation_and_shell_remains_uncertain(tmp_path):
    task = load_task(TASK)
    workspace = tmp_path / "worker"
    prepare_workspace(task, workspace, scope_policy=SCOPE_POLICY)
    s0 = capture(workspace, tmp_path / "S0")
    external = tmp_path / "shared/Temp/opencode/test.py"
    audit = audit_scope(
        task,
        workspace,
        s0,
        s0,
        history(external) + history(SCRATCH_NAME + "/test.py", "shell"),
        scope_policy=SCOPE_POLICY,
    )
    assert audit.transcript_violations == (str(external.resolve()),)
    assert len(audit.unverifiable_operations) == 1


@pytest.mark.parametrize("kind", ["seed", "allowed", "forbidden"])
def test_reserved_fixture_collision_fails_before_git_initialization(tmp_path, kind):
    task_dir = tmp_path / "fixture"
    shutil.copytree(TASK, task_dir)
    task = load_task(task_dir)
    if kind == "seed":
        (task_dir / "seed" / SCRATCH_NAME).mkdir()
        (task_dir / "seed" / SCRATCH_NAME / "payload").write_text("fixture")
    else:
        task = replace(task, **{f"{kind}_paths": (SCRATCH_NAME + "/file",)})
    workspace = tmp_path / "worker"
    with pytest.raises(ValueError, match="reserved"):
        prepare_workspace(task, workspace, scope_policy=SCOPE_POLICY)
    assert not (workspace / ".git").exists()


def test_unknown_policy_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="policy"):
        prepare_workspace(load_task(TASK), tmp_path / "worker", scope_policy="future-unknown")
    assert not (tmp_path / "worker").exists()


def test_temp_selection_in_fresh_python_and_powershell_is_child_local(tmp_path):
    workspace = tmp_path / "trial with spaces"
    prepare_workspace(load_task(TASK), workspace, scope_policy=SCOPE_POLICY)
    before = {k: os.environ.get(k) for k in ("TMPDIR", "TEMP", "TMP")}
    env = {**os.environ, **temp_environment(workspace)}
    python = subprocess.run(
        [sys.executable, "-I", "-B", "-c", "import tempfile; print(tempfile.gettempdir())"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert Path(python.stdout.strip()).resolve() == (workspace / SCRATCH_NAME).resolve()
    if os.name == "nt":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        assert shell
        ps = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", "[System.IO.Path]::GetTempPath()"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert Path(ps.stdout.strip()).resolve() == (workspace / SCRATCH_NAME).resolve()
    assert {k: os.environ.get(k) for k in before} == before


@pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")
@pytest.mark.parametrize("tail", [r".AGENT-BENCH-SCRATCH\sub\test.py", r".agent-bench-scratch\sub\..\test.py"])
def test_windows_case_separators_and_normalization(tmp_path, tail):
    workspace = tmp_path / "worker"
    prepare_workspace(load_task(TASK), workspace, scope_policy=SCOPE_POLICY)
    assert is_scratch(workspace, workspace / tail, SCOPE_POLICY)


@pytest.mark.skipif(os.name != "nt", reason="Windows ambiguous paths")
@pytest.mark.parametrize(
    "target", [f"{SCRATCH_NAME}/file:stream", f"{SCRATCH_NAME}./file", f"{SCRATCH_NAME}/dir /file", r"C:relative.txt"]
)
def test_windows_ambiguous_spellings_do_not_gain_permission(tmp_path, target):
    workspace = tmp_path / "worker"
    task = load_task(TASK)
    prepare_workspace(task, workspace, scope_policy=SCOPE_POLICY)
    s0 = capture(workspace, tmp_path / "S0")
    audit = audit_scope(task, workspace, s0, s0, history(target), scope_policy=SCOPE_POLICY)
    assert audit.compliance == "violated"


def test_junction_escape_is_rejected_and_owned_cleanup_never_follows_target(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction")
    owned = DispatchGuard().allocate(tmp_path / "workspaces")
    workspace = owned.path
    prepare_workspace(load_task(TASK), workspace, scope_policy=SCOPE_POLICY)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep"
    sentinel.write_text("untouched")
    junction = workspace / SCRATCH_NAME / "escape"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, check=True, timeout=10
    )
    assert not is_scratch(workspace, junction / "keep", SCOPE_POLICY)
    s0 = capture(outside, tmp_path / "outside-S0")
    with pytest.raises(ValueError, match="link"):
        capture(workspace, tmp_path / "bad-S1")
    decision = TerminationDecision(WorkerHandle("job", "session", "message", workspace), True, False, 10, 0, None, ())
    assert cleanup_workspace(owned, decision).removed
    assert sentinel.read_text() == "untouched"
    s0.check_intact()


def test_mocked_pipeline_records_policy_scratch_paths_and_preserves_scoring(tmp_path):
    class ScratchWorker(Worker):
        async def dispatch(self, workspace, prompt, **kwargs):
            self.prompt = prompt
            (workspace / SCRATCH_NAME / "test_grep.py").write_text("worker tests")
            self.last_history += history(SCRATCH_NAME + "/test_grep.py")
            return await super().dispatch(workspace, prompt, **kwargs)

    worker = ScratchWorker()
    result = attempt(tmp_path, worker, task=replace(load_task(TASK), opencode_tool_profile="shell-v1"))
    assert result.verification.status == "passed" and result.scope_violations == ()
    assert SCRATCH_NAME in worker.prompt and "TMPDIR" in worker.prompt and "every" in worker.prompt
    journal = json.loads((tmp_path / "evidence/lifecycle.json").read_text())
    assert journal["scope_policy"] == SCOPE_POLICY
    runtime = json.loads((tmp_path / "evidence/runtime.json").read_text())
    assert runtime["scratch"]["environment_delivery"] == "worker_command_local"
    trial = trial_from_attempt(
        result,
        run_id="run",
        trial_id="trial",
        task_id="task",
        variant_id="model",
        repetition=1,
        evidence_path="evidence/trial",
    )
    assert trial.status == "passed" and trial.details["scope_policy"] == SCOPE_POLICY
    assert trial.details["scratch_changed_paths"] == [SCRATCH_NAME + "/test_grep.py"]
    assert trial.details["task_changed_paths"] == ["grep.py"]
    timed = trial_from_attempt(
        replace(result, task_budget_expired=True),
        run_id="run",
        trial_id="trial",
        task_id="task",
        variant_id="model",
        repetition=1,
        evidence_path="evidence/trial",
    )
    assert timed.status == "timed_out"


def test_canonical_run_policy_recorded_even_when_runtime_unavailable(tmp_path):
    from runner_test import run
    from benchmark_core import load_run
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def unavailable(**kwargs):
        raise ConnectionError("offline")
        yield

    directory = run(tmp_path, unavailable)
    info, trials = load_run(directory)
    assert info.metadata["scope_policy"] == SCOPE_POLICY
    assert trials[0].details["scope_policy"] == SCOPE_POLICY


def test_reaudit_uses_recorded_policy_and_never_upgrades_unversioned_history(tmp_path):
    from agent_benchmark.evidence import reaudit_trial

    result = attempt(tmp_path, Worker())
    evidence = tmp_path / "evidence"
    # Add a synthetic historical scratch difference, keeping a separate legacy copy.
    (evidence / "S1" / SCRATCH_NAME).mkdir()
    (evidence / "S1" / SCRATCH_NAME / "test.py").write_text("scratch")
    assert reaudit_trial(evidence, load_task(TASK)).compliance == "compliant"
    legacy = tmp_path / "legacy"
    shutil.copytree(evidence, legacy)
    journal_path = legacy / "lifecycle.json"
    journal = json.loads(journal_path.read_text())
    del journal["scope_policy"]
    journal_path.write_text(json.dumps(journal))
    audit = reaudit_trial(legacy, load_task(TASK))
    assert audit.compliance == "violated"
    assert SCRATCH_NAME + "/test.py" in audit.snapshot_violations
    journal["scope_policy"] = "unknown-future"
    journal_path.write_text(json.dumps(journal))
    with pytest.raises(ValueError, match="policy"):
        reaudit_trial(legacy, load_task(TASK))
    assert result.verification.status == "passed"


def test_empty_reserved_fixture_directory_is_rejected(tmp_path):
    fixture = tmp_path / "fixture"
    shutil.copytree(TASK, fixture)
    (fixture / "seed" / SCRATCH_NAME).mkdir()
    with pytest.raises(ValueError, match="reserved"):
        prepare_workspace(load_task(fixture), tmp_path / "worker", scope_policy=SCOPE_POLICY)


def test_scratch_symlink_never_grants_permission(tmp_path):
    workspace = tmp_path / "worker"
    prepare_workspace(load_task(TASK), workspace, scope_policy=SCOPE_POLICY)
    outside = tmp_path / "outside.py"
    outside.write_text("untouched")
    link = workspace / SCRATCH_NAME / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink privilege unavailable")
    assert not is_scratch(workspace, link, SCOPE_POLICY)
    with pytest.raises(ValueError, match="link"):
        capture(workspace, tmp_path / "snapshot")


def test_scratch_hardlink_is_not_automatically_allowed(tmp_path):
    workspace = tmp_path / "worker"
    prepare_workspace(load_task(TASK), workspace, scope_policy=SCOPE_POLICY)
    outside = tmp_path / "outside.py"
    outside.write_text("untouched")
    link = workspace / SCRATCH_NAME / "linked.py"
    os.link(outside, link)
    assert not is_scratch(workspace, link, SCOPE_POLICY)


@pytest.mark.skipif(os.name != "nt", reason="Windows shell environment")
def test_powershell_command_local_settings_are_inherited_by_python(tmp_path):
    workspace = tmp_path / "trial with spaces"
    prepare_workspace(load_task(TASK), workspace, scope_policy=SCOPE_POLICY)
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell
    executable = sys.executable.replace("'", "''")
    command = (
        f"$env:TEMP = Join-Path (Get-Location).Path '{SCRATCH_NAME}'; "
        "$env:TMP = $env:TEMP; $env:TMPDIR = $env:TEMP; "
        f"& '{executable}' -I -B -c 'import tempfile; print(tempfile.gettempdir())'"
    )
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert Path(completed.stdout.strip()).resolve() == (workspace / SCRATCH_NAME).resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows workdir aliases")
def test_ambiguous_workdir_does_not_grant_scratch_permission(tmp_path):
    workspace = tmp_path / "worker"
    task = load_task(TASK)
    prepare_workspace(task, workspace, scope_policy=SCOPE_POLICY)
    s0 = capture(workspace, tmp_path / "S0")
    transcript = history("test.py")
    transcript[0]["parts"][0]["state"]["input"]["workdir"] = SCRATCH_NAME + "."
    audit = audit_scope(task, workspace, s0, s0, transcript, scope_policy=SCOPE_POLICY)
    assert audit.compliance == "violated"


def test_unresolved_worker_preserves_scratch_and_prevents_further_allocation(tmp_path):
    class UnresolvedScratch(Worker):
        async def dispatch(self, workspace, prompt, **kwargs):
            (workspace / SCRATCH_NAME / "pending.py").write_text("worker may still be using this")
            return await super().dispatch(workspace, prompt, **kwargs)

    guard = DispatchGuard()
    with pytest.warns(RuntimeWarning, match="Unresolved"):
        result = attempt(tmp_path, UnresolvedScratch(unresolved=True), guard=guard, task_seconds=0.001)
    assert not result.termination.confirmed and result.s1 is None
    assert (result.workspace.path / SCRATCH_NAME / "pending.py").exists()
    assert not cleanup_workspace(result.workspace, result.termination).removed
    with pytest.raises(RuntimeError, match="halted"):
        guard.allocate(tmp_path / "workers")


@pytest.mark.skipif(os.name != "nt", reason="Windows reserved devices")
@pytest.mark.parametrize("name", ["NUL.txt", "CON", "COM1.log"])
def test_windows_device_names_never_gain_scratch_permission(tmp_path, name):
    workspace = tmp_path / "worker"
    task = load_task(TASK)
    prepare_workspace(task, workspace, scope_policy=SCOPE_POLICY)
    s0 = capture(workspace, tmp_path / "S0")
    audit = audit_scope(task, workspace, s0, s0, history(SCRATCH_NAME + "/" + name), scope_policy=SCOPE_POLICY)
    assert audit.compliance != "compliant"


def test_full_canonical_scratch_run_persists_policy_and_separate_paths(tmp_path):
    from contextlib import asynccontextmanager
    from benchmark_core import load_run
    from runner_test import run
    from agent_benchmark.evidence import reaudit_trial

    class ScratchWorker(Worker):
        async def dispatch(self, workspace, prompt, **kwargs):
            (workspace / SCRATCH_NAME / "test.py").write_text("worker-generated check")
            self.last_history += history(SCRATCH_NAME + "/test.py")
            return await super().dispatch(workspace, prompt, **kwargs)

    @asynccontextmanager
    async def connector(**kwargs):
        yield ScratchWorker()

    directory = run(tmp_path, connector)
    info, trials = load_run(directory)
    assert info.metadata["scope_policy"] == SCOPE_POLICY
    assert info.metadata["runtime"]["scratch"]["automatic_server_redirection"] is False
    assert len(trials) == 1 and trials[0].status == "passed"
    assert trials[0].details["scope_policy"] == SCOPE_POLICY
    assert trials[0].details["task_changed_paths"] == ["grep.py"]
    assert trials[0].details["scratch_changed_paths"] == [SCRATCH_NAME + "/test.py"]
    assert (
        reaudit_trial(directory / "evidence/trial-001", load_task(TASK)).to_dict() == trials[0].details["scope_audit"]
    )
