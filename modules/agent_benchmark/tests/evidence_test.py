"""Independent filesystem evidence and verifier boundary regressions."""

from pathlib import Path

import pytest

from agent_benchmark.evidence import (audit_scope, capture, changed_paths,
                                    load_task, prepare_workspace, reaudit_trial, verify)

TASK = Path(__file__).resolve().parents[1] / "agent_benchmark" / "tasks" / "py-grep-smoke"
GOOD = "def grep(pattern, lines, ignore_case=False):\n    return [s for s in lines if (pattern.lower() in s.lower() if ignore_case else pattern in s)]\n"


def test_s1_bytes_survive_later_coordinator_repair(tmp_path):
    worker = tmp_path / "worker"
    prepare_workspace(load_task(TASK), worker)
    s0 = capture(worker, tmp_path / "S0")
    (worker / "grep.py").write_bytes(b"def grep(*args, **kwargs): return []\n")
    s1 = capture(worker, tmp_path / "S1")
    first = verify(s1, TASK / "verifier/check.py", tmp_path / "verify1", timeout_seconds=2)
    (worker / "grep.py").write_text(GOOD, encoding="utf-8")
    s3 = capture(worker, tmp_path / "S3")
    repaired = verify(s3, TASK / "verifier/check.py", tmp_path / "verify3", timeout_seconds=2)
    assert first.status == "failed"
    assert repaired.status == "passed"
    assert s1.files["grep.py"] == b"def grep(*args, **kwargs): return []\n"
    assert changed_paths(s0, s1) == ["grep.py"]
    assert s1.tree_hash != s3.tree_hash
    assert "Traceback" not in first.stdout


def test_snapshot_cannot_be_overwritten_or_modified_through_mapping(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "bytes.bin").write_bytes(b"\xff\x00\r\n")
    snap = capture(worker, tmp_path / "S1")
    assert (snap.path / "bytes.bin").read_bytes() == b"\xff\x00\r\n"
    with pytest.raises(TypeError):
        snap.files["new"] = b"bad"
    with pytest.raises(FileExistsError):
        capture(worker, snap.path)


def test_authoritative_verifier_runs_on_disposable_copy(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "grep.py").write_text("seed")
    snap = capture(worker, tmp_path / "S1")
    verifier = tmp_path / "check.py"
    verifier.write_text(
        "import sys, os, json; from pathlib import Path; "
        "(Path(sys.argv[1]) / 'grep.py').write_text('modified'); "
        "Path(os.environ['AGENT_BENCH_COMPLETION_PATH']).write_text(json.dumps({"
        "'nonce': os.environ['AGENT_BENCH_VERIFICATION_NONCE'], 'status': 'passed', 'checks_completed': 1}))"
    )
    result = verify(snap, verifier, tmp_path / "verification", timeout_seconds=2)
    assert result.status == "passed"
    assert (snap.path / "grep.py").read_text() == "seed"


def test_verifier_failures_are_distinct_and_output_retained(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    snap = capture(worker, tmp_path / "S1")
    verifier = tmp_path / "check.py"
    verifier.write_text("import sys; print('diagnostic'); sys.exit(2)")
    result = verify(snap, verifier, tmp_path / "infra", timeout_seconds=2)
    assert result.status == "infrastructure_error"
    assert "diagnostic" in (tmp_path / "infra/stdout.txt").read_text()
    verifier.write_text("import time; time.sleep(5)")
    assert verify(snap, verifier, tmp_path / "timeout", timeout_seconds=0.03).status == "timed_out"


def test_changed_protected_added_and_deleted_files_are_all_auditable(tmp_path):
    worker = tmp_path / "worker"
    prepare_workspace(load_task(TASK), worker)
    s0 = capture(worker, tmp_path / "S0")
    (worker / "grep.py").unlink()
    (worker / "instruction.md").write_text("tampered")
    (worker / "extra.txt").write_text("new")
    assert changed_paths(s0, capture(worker, tmp_path / "S1")) == ["extra.txt", "grep.py", "instruction.md"]


def test_worker_does_not_receive_hidden_verifier(tmp_path):
    task = load_task(TASK)
    prepare_workspace(task, tmp_path / "worker")
    assert sorted(p.name for p in (tmp_path / "worker").iterdir()) == [".git", "grep.py", "instruction.md", "task.json"]


def test_symlink_entry_cannot_escape_snapshot(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("outside")
    try:
        (worker / "link").symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="link"):
        capture(worker, tmp_path / "S1")


def test_transcript_audit_detects_external_file_mutation(tmp_path):
    task = load_task(TASK)
    worker = tmp_path / "worker"
    prepare_workspace(task, worker)
    s0 = capture(worker, tmp_path / "S0")
    (worker / "grep.py").write_text(GOOD, encoding="utf-8")
    s1 = capture(worker, tmp_path / "S1")

    ext_path = "C:\\Users\\mcarls\\AppData\\Local\\Temp\\opencode\\test_grep_smoke.py"
    history = [
        {"info": {"id": "m1"}, "parts": [
            {"type": "tool", "tool": "write", "callID": "c1",
             "state": {"status": "completed", "input": {"filePath": ext_path, "content": "import pytest"}}},
        ]},
        {"info": {"id": "m2"}, "parts": [
            {"type": "tool", "tool": "edit", "callID": "c2",
             "state": {"status": "completed", "input": {"filePath": ext_path, "oldString": "a", "newString": "b"}}},
        ]},
    ]
    audit = audit_scope(task, worker, s0, s1, history)
    assert audit.snapshot_violations == ()
    assert len(audit.transcript_violations) == 1
    assert "test_grep_smoke.py" in audit.transcript_violations[0]
    assert audit.all_violations == audit.transcript_violations
    assert len(audit.mutation_events) == 2
    assert all(not e.in_workspace and not e.in_scope for e in audit.mutation_events)


def test_transcript_audit_detects_protected_file_mutation_and_restoration(tmp_path):
    task = load_task(TASK)
    worker = tmp_path / "worker"
    prepare_workspace(task, worker)
    s0 = capture(worker, tmp_path / "S0")
    (worker / "grep.py").write_text(GOOD, encoding="utf-8")
    s1 = capture(worker, tmp_path / "S1")

    history = [
        {"info": {"id": "m1"}, "parts": [
            {"type": "tool", "tool": "edit", "callID": "c1",
             "state": {"status": "completed", "input": {"filePath": str(worker / "instruction.md"),
                                                        "oldString": "a", "newString": "b"}}},
        ]},
        {"info": {"id": "m2"}, "parts": [
            {"type": "tool", "tool": "edit", "callID": "c2",
             "state": {"status": "completed", "input": {"filePath": "instruction.md",
                                                        "oldString": "b", "newString": "a"}}},
        ]},
        {"info": {"id": "m3"}, "parts": [
            {"type": "tool", "tool": "edit", "callID": "c3",
             "state": {"status": "completed", "input": {"filePath": "grep.py",
                                                        "oldString": "foo", "newString": "bar"}}},
        ]},
    ]
    audit = audit_scope(task, worker, s0, s1, history)
    assert audit.snapshot_violations == ()
    assert audit.transcript_violations == ("instruction.md",)
    assert audit.all_violations == ("instruction.md",)
    assert audit.mutated_paths == ("grep.py", "instruction.md")


def test_transcript_audit_allows_compliant_workspace_edits_and_ignores_reads(tmp_path):
    task = load_task(TASK)
    worker = tmp_path / "worker"
    prepare_workspace(task, worker)
    s0 = capture(worker, tmp_path / "S0")
    (worker / "grep.py").write_text(GOOD, encoding="utf-8")
    s1 = capture(worker, tmp_path / "S1")

    history = [
        {"info": {"id": "m1"}, "parts": [
            {"type": "tool", "tool": "read", "callID": "c1",
             "state": {"status": "completed", "input": {"filePath": str(worker / "instruction.md")}}},
            {"type": "tool", "tool": "read", "callID": "c2",
             "state": {"status": "completed", "input": {"filePath": "grep.py"}}},
            {"type": "tool", "tool": "edit", "callID": "c3",
             "state": {"status": "completed", "input": {"filePath": str(worker / "grep.py"),
                                                        "oldString": "a", "newString": "b"}}},
        ]},
    ]
    audit = audit_scope(task, worker, s0, s1, history)
    assert audit.snapshot_violations == ()
    assert audit.transcript_violations == ()
    assert audit.all_violations == ()
    assert audit.mutated_paths == ("grep.py",)
    assert len(audit.mutation_events) == 1


def test_transcript_audit_handles_malformed_and_unknown_mutation_targets(tmp_path):
    task = load_task(TASK)
    worker = tmp_path / "worker"
    prepare_workspace(task, worker)
    s0 = capture(worker, tmp_path / "S0")
    s1 = capture(worker, tmp_path / "S1")

    history = [
        {"info": {"id": "m1"}, "parts": [
            {"type": "tool", "tool": "write", "callID": "c1",
             "state": {"status": "completed", "input": {"filePath": None}}},
            {"type": "tool", "tool": "edit", "callID": "c2",
             "state": {"status": "completed", "input": {"not_a_path": "x"}}},
            {"type": "tool", "tool": "write", "callID": "c3",
             "state": {"status": "completed", "input": "invalid_input"}},
            {"type": "tool", "tool": "bash", "callID": "c4",
             "state": {"status": "completed", "input": {"command": "python -B check.py"}}},
        ]},
    ]
    audit = audit_scope(task, worker, s0, s1, history)
    assert audit.all_violations == ()
    assert len(audit.mutation_events) == 0
    assert len(audit.unverifiable_operations) == 4


def test_transcript_audit_resolves_relative_path_with_workdir_and_boundary_checks(tmp_path):
    task = load_task(TASK)
    worker = tmp_path / "worker"
    prepare_workspace(task, worker)
    s0 = capture(worker, tmp_path / "S0")
    s1 = capture(worker, tmp_path / "S1")

    sub = worker / "sub"
    sub.mkdir()
    history = [
        {"info": {"id": "m1"}, "parts": [
            {"type": "tool", "tool": "edit", "callID": "c1",
             "state": {"status": "completed", "input": {"filePath": "../grep.py", "workdir": str(sub)}}},
            {"type": "tool", "tool": "write", "callID": "c2",
             "state": {"status": "completed", "input": {"filePath": "../../escape.txt", "workdir": str(worker)}}},
            {"type": "tool", "tool": "write", "callID": "c3",
             "state": {"status": "completed", "input": {"filePath": str(worker) + "_other/file.txt"}}},
        ]},
    ]
    audit = audit_scope(task, worker, s0, s1, history)
    assert "grep.py" in audit.mutated_paths
    assert len(audit.transcript_violations) == 2
    assert any("escape.txt" in v for v in audit.transcript_violations)
    assert any("other" in v for v in audit.transcript_violations)


def test_reaudit_trial_traceably_audits_without_overwriting(tmp_path):
    import json
    task = load_task(TASK)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    worker = tmp_path / "worker"
    prepare_workspace(task, worker)
    capture(worker, evidence_dir / "S0")
    (worker / "grep.py").write_text(GOOD, encoding="utf-8")
    capture(worker, evidence_dir / "S1")

    (evidence_dir / "lifecycle.json").write_text(
        json.dumps({"workspace": {"path": str(worker)}}), encoding="utf-8"
    )
    ext_path = "C:\\Users\\mcarls\\AppData\\Local\\Temp\\opencode\\test_grep_smoke.py"
    (evidence_dir / "session.json").write_text(
        json.dumps([
            {"info": {"id": "m1"}, "parts": [
                {"type": "tool", "tool": "write", "callID": "c1",
                 "state": {"status": "completed", "input": {"filePath": ext_path, "content": "x"}}},
            ]},
        ]),
        encoding="utf-8",
    )
    audit = reaudit_trial(evidence_dir, task)
    assert len(audit.transcript_violations) == 1
    assert "test_grep_smoke.py" in audit.transcript_violations[0]
    audit_dict = audit.to_dict()
    assert isinstance(json.dumps(audit_dict), str)



@pytest.mark.parametrize("code", [
    "raise SystemExit(0)\n",
    "def grep(*args, **kwargs): raise SystemExit(0)\n",
    "import os; os._exit(0)\n",
    "def grep(*args, **kwargs):\n    import os; os._exit(0)\n",
    "print('PASS: all grep tests passed successfully', flush=True)\nraise SystemExit(0)\n",
])
def test_worker_termination_cannot_pass_hidden_verification(tmp_path, code):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "grep.py").write_text(code, encoding="utf-8")
    result = verify(capture(worker, tmp_path / "S1"), TASK / "verifier/check.py", tmp_path / "verification")
    assert result.status != "passed"


def test_zero_exit_without_completion_receipt_cannot_pass(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    verifier = tmp_path / "check.py"
    verifier.write_text("# exits successfully without running assertions\n")
    result = verify(capture(worker, tmp_path / "S1"), verifier, tmp_path / "verification")
    assert result.status == "infrastructure_error"
    assert "completion" in result.stderr.lower()



def test_relative_tool_workdir_is_relative_to_worker_not_coordinator(tmp_path):
    from agent_benchmark.evidence import audit_transcript
    workspace = tmp_path / "workspace"
    history = [{"info": {"id": "assistant-1"}, "parts": [{
        "type": "tool", "tool": "edit", "callID": "edit-1",
        "state": {"status": "completed", "input": {"filePath": "grep.py", "workdir": "."}},
    }]}]
    violations, paths, events, uncertain = audit_transcript(load_task(TASK), workspace, history)
    assert violations == () and paths == ("grep.py",)
    assert events[0].in_scope and not uncertain


def test_failed_mutation_is_uncertain_because_partial_writes_are_possible(tmp_path):
    from agent_benchmark.evidence import audit_transcript
    history = [{"info": {"id": "assistant-1"}, "parts": [{
        "type": "tool", "tool": "write", "callID": "write-1",
        "state": {"status": "error", "input": {"filePath": "instruction.md"}, "error": "write failed"},
    }]}]
    violations, _, events, uncertain = audit_transcript(load_task(TASK), tmp_path, history)
    assert not violations and len(events) == 1
    assert len(uncertain) == 1 and "partial" in uncertain[0].reason.lower()


@pytest.mark.parametrize("history", [None, [], [None], [{}], [{"info": {"id": "m"}, "parts": [None]}]])
def test_missing_or_malformed_transcripts_cannot_claim_compliance(tmp_path, history):
    from agent_benchmark.evidence import audit_scope
    worker = tmp_path / "worker"
    worker.mkdir()
    s0 = capture(worker, tmp_path / "S0")
    s1 = capture(worker, tmp_path / "S1")
    audit = audit_scope(load_task(TASK), worker, s0, s1, history)
    assert audit.compliance == "uncertain"
    assert audit.unverifiable_operations


@pytest.mark.parametrize("payload", [
    {"nonce": "stale", "status": "passed", "checks_completed": 22},
    {"status": "passed", "checks_completed": 0},
    {"status": "passed", "checks_completed": True},
])
def test_invalid_completion_receipts_do_not_authorize_pass(tmp_path, payload):
    worker = tmp_path / "worker"
    worker.mkdir()
    verifier = tmp_path / "check.py"
    verifier.write_text(
        "import os,json; from pathlib import Path\n"
        f"receipt = {payload!r}\n"
        "receipt.setdefault('nonce', os.environ['AGENT_BENCH_VERIFICATION_NONCE'])\n"
        "Path(os.environ['AGENT_BENCH_COMPLETION_PATH']).write_text(json.dumps(receipt))\n",
        encoding="utf-8",
    )
    assert verify(capture(worker, tmp_path / "S1"), verifier, tmp_path / "verification").status == "infrastructure_error"


@pytest.mark.parametrize(("version", "error", "uncertain"), [
    ("1.19.3", "File /C:/missing/grep.py not found", False),
    ("1.19.3", "Permission denied: /C:/missing/grep.py", True),
    ("1.19.2", "File /C:/missing/grep.py not found", True),
])
def test_failed_edit_is_exempt_only_for_versioned_proven_pre_mutation_error(tmp_path, version, error, uncertain):
    from agent_benchmark.scratch import SCOPE_POLICY

    task = load_task(TASK)
    worker = tmp_path / "worker"
    prepare_workspace(task, worker)
    s0 = capture(worker, tmp_path / "S0")
    s1 = capture(worker, tmp_path / "S1")
    history = [{"info": {"id": "m1"}, "parts": [{"type": "tool", "tool": "edit", "callID": "edit-1",
        "state": {"status": "error", "error": error,
                  "input": {"filePath": "/C:/missing/grep.py", "oldString": "old", "newString": "new"}}}]}]
    audit = audit_scope(task, worker, s0, s1, history, scope_policy=SCOPE_POLICY, opencode_version=version)
    assert bool(audit.unverifiable_operations) is uncertain
    if uncertain:
        assert audit.compliance == "uncertain"
    else:
        assert audit.compliance == "compliant"
        assert audit.mutated_paths == ()
        assert audit.mutation_events[0].safety_outcome == "failed_before_mutation"
        assert audit.to_dict()["mutation_events"][0]["safety_outcome"] == "failed_before_mutation"
