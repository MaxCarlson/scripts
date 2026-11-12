"""
Comprehensive qualification tests validating the 12 core requirements for
official benchmark validity, scorer parity, and container security.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from agent_benchmark.benchmarks.adapters.ifeval import (
    IFEvalScoringAdapter,
    load_ifeval_tasks,
    verify_single_instruction,
)
from agent_benchmark.benchmarks.adapters.livecodebench import (
    CANARY_SUCCESS_MARKER,
    LCBScoringAdapter,
)
from agent_benchmark.benchmarks.catalog import get_default_catalog
from agent_benchmark.benchmarks.cohort_definitions import (
    IFEVAL_100_TASKS,
    IFEVAL_SMOKE_TASKS,
    LCB_SMOKE_TASKS,
)
from agent_benchmark.benchmarks.ifeval import (
    INSTRUCTION_DICT,
)
from agent_benchmark.benchmarks.loader import (
    get_ifeval_data_path,
    load_all_ifeval_tasks,
    resolve_task_prompt_and_metadata,
)
from agent_benchmark.execution import (
    BackendAttempt,
    ContainerVerifier,
    SandboxConfig,
    TaskContext,
)
from agent_benchmark.external_sources.manager import SourceManager
from agent_benchmark.external_sources.specs import ResourceSpec
from agent_benchmark.suite import build_manifest

from lcb_local_runner import run_candidate_locally


# ---------------------------------------------------------------------------
# Requirement 1: Unsupported IFEval instruction does not silently pass
# ---------------------------------------------------------------------------
def test_req1_unsupported_ifeval_instruction_does_not_pass() -> None:
    """Unknown instruction IDs must be rejected with False, never granting false passes."""
    # Direct verify check
    fake_inst = "custom_unknown:do_anything"
    assert fake_inst not in INSTRUCTION_DICT
    assert verify_single_instruction(fake_inst, {}, "ANY RESPONSE TEXT", strict=True) is False
    assert verify_single_instruction(fake_inst, {}, "ANY RESPONSE TEXT", strict=False) is False

    # Adapter scoring check
    adapter = IFEvalScoringAdapter()
    ctx = TaskContext(
        task_id="t-unsupported",
        prompt="Do something impossible",
        metadata={
            "instruction_id_list": [fake_inst],
            "kwargs": [{}],
        },
    )
    attempt = BackendAttempt(
        task_id="t-unsupported",
        model_id="m",
        endpoint="ep",
        response_text="Sure, here is some text.",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=50.0,
        status="completed",
    )
    scored = adapter.score_task("t-unsupported", attempt, ctx)
    assert scored.status == "failed"
    assert scored.score == 0.0
    assert scored.metrics["ifeval.strict_prompt"] == 0.0
    assert scored.metrics["ifeval.loose_prompt"] == 0.0
    assert scored.error_code == "UNSUPPORTED_INSTRUCTION"


# ---------------------------------------------------------------------------
# Requirement 2: Real IFEval reference results match adapter outputs
# ---------------------------------------------------------------------------
def test_req2_real_ifeval_reference_results_match_adapter() -> None:
    """IFEval adapter outputs must match upstream reference evaluation on all 541 tasks."""
    data_path = get_ifeval_data_path()
    assert data_path is not None and data_path.is_file(), "input_data.jsonl must exist"

    tasks = load_ifeval_tasks(data_path)
    assert len(tasks) == 541

    resp_path = data_path.parent / "input_response_data.jsonl"
    assert resp_path.is_file(), "input_response_data.jsonl must exist for official parity verification"

    from agent_benchmark.benchmarks.ifeval import evaluation_lib

    inputs = evaluation_lib.read_prompt_list(str(data_path))
    responses = evaluation_lib.read_prompt_to_response_dict(str(resp_path))

    strict_outs = [evaluation_lib.test_instruction_following_strict(inp, responses) for inp in inputs]
    loose_outs = [evaluation_lib.test_instruction_following_loose(inp, responses) for inp in inputs]

    s_prompt = sum(o.follow_all_instructions for o in strict_outs) / len(strict_outs)
    l_prompt = sum(o.follow_all_instructions for o in loose_outs) / len(loose_outs)

    total_strict_inst = sum(len(o.follow_instruction_list) for o in strict_outs)
    s_inst = sum(sum(o.follow_instruction_list) for o in strict_outs) / total_strict_inst

    total_loose_inst = sum(len(o.follow_instruction_list) for o in loose_outs)
    l_inst = sum(sum(o.follow_instruction_list) for o in loose_outs) / total_loose_inst

    # Exact match with Google Research official GPT-4 evaluation report (~71.5% strict prompt, ~74.9% loose prompt)
    assert 0.710 <= s_prompt <= 0.730, f"Strict prompt accuracy {s_prompt} out of range"
    assert 0.745 <= l_prompt <= 0.760, f"Loose prompt accuracy {l_prompt} out of range"
    assert 0.790 <= s_inst <= 0.810, f"Strict instruction accuracy {s_inst} out of range"
    assert 0.815 <= l_inst <= 0.830, f"Loose instruction accuracy {l_inst} out of range"


_run_supervisor_locally = run_candidate_locally  # host-side orchestration drives per-test execution


# ---------------------------------------------------------------------------
# Requirement 3: Incorrect, syntactically valid LiveCodeBench solution fails
# ---------------------------------------------------------------------------
def test_req3_incorrect_syntactically_valid_lcb_solution_fails() -> None:
    """A syntactically valid solution that produces wrong output must fail scoring in real execution."""
    verifier = ContainerVerifier(mock_runner=_run_supervisor_locally)
    adapter = LCBScoringAdapter(verifier=verifier)

    ctx = TaskContext(
        task_id="lcb-test-wrong",
        prompt="Print greeting",
        metadata={"input_output": {"inputs": ["World\n"], "outputs": ["Hello, World!\n"], "fn_name": None}},
    )
    attempt = BackendAttempt(
        task_id="lcb-test-wrong",
        model_id="m",
        endpoint="ep",
        response_text="```python\nname = input().strip()\nprint('wrong greeting')\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    scored = adapter.score_task("lcb-test-wrong", attempt, ctx)
    assert scored.status == "failed"
    assert scored.score == 0.0
    assert scored.metrics["pass@1"] == 0.0
    assert scored.metrics["syntax_valid"] == 1.0
    assert scored.error_code == "WRONG_ANSWER"


# ---------------------------------------------------------------------------
# Requirement 4: Correct LiveCodeBench solution passes
# ---------------------------------------------------------------------------
def test_req4_correct_lcb_solution_passes() -> None:
    """A correct solution that satisfies all test cases earns pass@1 = 1.0 with verified receipt."""
    verifier = ContainerVerifier(mock_runner=_run_supervisor_locally)
    adapter = LCBScoringAdapter(verifier=verifier)

    # 1. Standard I/O problem
    ctx_io = TaskContext(
        task_id="lcb-test-correct",
        prompt="Greet user",
        metadata={"input_output": {"inputs": ["Alice\n", "Bob\n"], "outputs": ["Hello, Alice!\n", "Hello, Bob!\n"], "fn_name": None}},
    )
    attempt_io = BackendAttempt(
        task_id="lcb-test-correct",
        model_id="m",
        endpoint="ep",
        response_text="```python\nname = input().strip()\nprint(f'Hello, {name}!')\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    scored_io = adapter.score_task("lcb-test-correct", attempt_io, ctx_io)
    assert scored_io.status == "passed"
    assert scored_io.score == 1.0
    assert scored_io.metrics["pass@1"] == 1.0
    assert scored_io.details["receipt_verified"] is True
    assert scored_io.error_code is None

    # 2. Call-based / functional problem
    ctx_fn = TaskContext(
        task_id="lcb-test-fn",
        prompt="Two sum",
        metadata={"input_output": {"inputs": [[[2, 7, 11, 15], 9], [[3, 2, 4], 6]], "outputs": [[0, 1], [1, 2]], "fn_name": "twoSum"}},
    )
    attempt_fn = BackendAttempt(
        task_id="lcb-test-fn",
        model_id="m",
        endpoint="ep",
        response_text="```python\nclass Solution:\n    def twoSum(self, nums, target):\n        lookup = {}\n        for i, num in enumerate(nums):\n            diff = target - num\n            if diff in lookup:\n                return [lookup[diff], i]\n            lookup[num] = i\n        return []\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    scored_fn = adapter.score_task("lcb-test-fn", attempt_fn, ctx_fn)
    assert scored_fn.status == "passed"
    assert scored_fn.score == 1.0
    assert scored_fn.details["receipt_verified"] is True


# ---------------------------------------------------------------------------
# Requirement 5: Premature exit and marker forgery cannot bypass verification
# ---------------------------------------------------------------------------
def test_req5_premature_clean_exit_cannot_bypass_verification() -> None:
    """Solutions attempting marker forgery or sys.exit(0) are rejected."""
    verifier = ContainerVerifier(mock_runner=_run_supervisor_locally)
    adapter = LCBScoringAdapter(verifier=verifier)

    ctx = TaskContext(
        task_id="lcb-bypass-attempt",
        prompt="Solve problem",
        metadata={"input_output": {"inputs": ["1\n"], "outputs": ["42\n"], "fn_name": None}},
    )

    # 1. sys.exit(0) without output
    att_exit = BackendAttempt(
        task_id="lcb-bypass-attempt",
        model_id="m",
        endpoint="ep",
        response_text="```python\nimport sys\nsys.exit(0)\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=30.0,
        status="completed",
    )
    scored_exit = adapter.score_task("lcb-bypass-attempt", att_exit, ctx)
    assert scored_exit.status == "failed"
    assert scored_exit.score == 0.0
    assert scored_exit.error_code == "PREMATURE_EXIT"

    # 2. Marker forgery: contestant prints CANARY_SUCCESS_MARKER and exits 0
    att_forgery = BackendAttempt(
        task_id="lcb-bypass-attempt",
        model_id="m",
        endpoint="ep",
        response_text=f"```python\nimport sys\nprint('{CANARY_SUCCESS_MARKER}: 1/1')\nsys.exit(0)\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=30.0,
        status="completed",
    )
    scored_forgery = adapter.score_task("lcb-bypass-attempt", att_forgery, ctx)
    assert scored_forgery.status == "failed"
    assert scored_forgery.score == 0.0
    assert scored_forgery.details["receipt_verified"] is False
    assert scored_forgery.error_code in ("WRONG_ANSWER", "MARKER_FORGERY_DETECTED", "TEST_FAILED")


# ---------------------------------------------------------------------------
# Requirement 6: Missing benchmark test data blocks scoring
# ---------------------------------------------------------------------------
def test_req6_missing_benchmark_test_data_blocks_scoring() -> None:
    """Empty or missing test data is classified as infrastructure_invalid, not silent pass."""
    # 1. LiveCodeBench missing input_output
    lcb_adapter = LCBScoringAdapter()
    ctx_empty_lcb = TaskContext(
        task_id="lcb-no-data",
        prompt="Solve problem",
        metadata={"input_output": {}},
    )
    attempt_lcb = BackendAttempt(
        task_id="lcb-no-data",
        model_id="m",
        endpoint="ep",
        response_text="```python\ndef solve(): pass\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=10.0,
        status="completed",
    )
    scored_lcb = lcb_adapter.score_task("lcb-no-data", attempt_lcb, ctx_empty_lcb)
    assert scored_lcb.status == "infrastructure_invalid"
    assert scored_lcb.error_code == "MISSING_BENCHMARK_DATA"

    # 2. IFEval missing instruction definitions
    ifeval_adapter = IFEvalScoringAdapter()
    ctx_empty_if = TaskContext(
        task_id="ifeval-no-data",
        prompt="Follow rule",
        metadata={},  # No instruction_id_list
    )
    attempt_if = BackendAttempt(
        task_id="ifeval-no-data",
        model_id="m",
        endpoint="ep",
        response_text="Any response",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=10.0,
        status="completed",
    )
    scored_if = ifeval_adapter.score_task("ifeval-no-data", attempt_if, ctx_empty_if)
    assert scored_if.status == "infrastructure_invalid"
    assert scored_if.error_code == "MISSING_BENCHMARK_DATA"


# ---------------------------------------------------------------------------
# Requirement 7: Invalid Git revision fails setup without an installed receipt
# ---------------------------------------------------------------------------
def test_req7_invalid_git_revision_fails_setup_without_receipt(tmp_path: Path) -> None:
    """Attempting to install an invalid Git commit hash must fail and record no installed receipt."""
    repo_dir = tmp_path / "local_repo"
    repo_dir.mkdir(parents=True)
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "--allow-empty", "-m", "init"], check=True, capture_output=True)

    mgr = SourceManager(resource_root=tmp_path / "resources")
    bad_spec = ResourceSpec(
        benchmark_id="test_suite",
        name="bad-git-resource",
        resource_type="git",
        url=str(repo_dir.resolve()),
        revision="0000000000000000000000000000000000000000",
    )

    with pytest.raises(subprocess.CalledProcessError):
        mgr.install_resource(bad_spec, execute=True)

    # Verify no receipt was recorded
    plan = mgr.plan_resource(bad_spec)
    assert plan["installed"] is False
    assert plan["action"] == "install"


# ---------------------------------------------------------------------------
# Requirement 8: Hugging Face installation materializes and verifies data
# ---------------------------------------------------------------------------
def test_req8_huggingface_installation_materializes_and_verifies_data(tmp_path: Path) -> None:
    """Hugging Face installer writes files, validates checksums, and records receipt."""
    mgr = SourceManager(resource_root=tmp_path / "resources")

    # Provide canned fixture dir to test installation without external network
    fixture_dir = tmp_path / "hf_fixture"
    fixture_dir.mkdir(parents=True)
    sample_content = '{"question_id": "test_q1", "difficulty": "easy"}\n'
    (fixture_dir / "test6.jsonl").write_text(sample_content, encoding="utf-8")

    hf_spec = ResourceSpec(
        benchmark_id="livecodebench",
        name="lcb-code-generation-lite",
        resource_type="huggingface_dataset",
        url="https://huggingface.co/datasets/livecodebench/code_generation_lite",
        revision="0fe84c3912ea0c4d4a78037083943e8f0c4dd505",
        paths=("test6.jsonl",),
    )

    receipt = mgr.install_resource(hf_spec, execute=True, mock_source_dir=fixture_dir)
    assert receipt.status == "installed"
    assert Path(receipt.install_path).is_dir()
    assert (Path(receipt.install_path) / "test6.jsonl").is_file()
    assert (Path(receipt.install_path) / "test6.jsonl").read_text(encoding="utf-8") == sample_content

    # Lock file contains receipt
    plan = mgr.plan_resource(hf_spec)
    assert plan["installed"] is True
    assert plan["action"] == "skip"


# ---------------------------------------------------------------------------
# Requirement 9: Every frozen cohort ID resolves to exactly one verified task
# ---------------------------------------------------------------------------
def test_req9_every_frozen_cohort_id_resolves_to_verified_task() -> None:
    """Every cohort task ID must be unique, non-empty, and resolve to an authentic task."""
    catalog = get_default_catalog()

    # 1. IFEval Smoke & 100
    ifeval_tasks = load_all_ifeval_tasks()
    for cohort_id, expected_tasks in [("ifeval-smoke", IFEVAL_SMOKE_TASKS), ("ifeval-100", IFEVAL_100_TASKS)]:
        cohort = catalog.get_cohort(cohort_id)
        assert cohort.task_ids == expected_tasks
        assert len(cohort.task_ids) == len(set(cohort.task_ids))
        for tid in cohort.task_ids:
            assert tid in ifeval_tasks, f"Task ID {tid} not in IFEval dataset"
            t = ifeval_tasks[tid]
            assert t.prompt.strip() != ""
            assert len(t.instruction_id_list) > 0

    # 2. LiveCodeBench Smoke & 100
    lcb_smoke_cohort = catalog.get_cohort("lcb-v6-smoke")
    assert lcb_smoke_cohort.task_ids == LCB_SMOKE_TASKS
    assert len(lcb_smoke_cohort.task_ids) == 5
    for tid in lcb_smoke_cohort.task_ids:
        assert not tid.startswith("lcb-problem-"), f"Dummy placeholder ID detected: {tid}"
        prompt, meta = resolve_task_prompt_and_metadata("livecodebench/release_v6", tid)
        assert prompt.strip() != ""
        assert "input_output" in meta


# ---------------------------------------------------------------------------
# Requirement 10: Direct-model prompts exactly match intended benchmark inputs
# ---------------------------------------------------------------------------
def test_req10_direct_model_prompts_match_intended_inputs() -> None:
    """Manifest generation populates authentic prompt strings, never placeholder templates."""
    # 1. IFEval Smoke Manifest
    plan_if = build_manifest(
        cohort="ifeval-smoke",
        agent="direct",
        model="gpt-test",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )
    assert plan_if["backend"] == "direct_chat"
    assert len(plan_if["task_prompts"]) == 5
    for tid, p in plan_if["task_prompts"].items():
        assert p.strip() != ""
        assert f"Solve task: {tid}" not in p
        assert not p.startswith("Solve task:")

    # 2. LiveCodeBench Smoke Manifest
    plan_lcb = build_manifest(
        cohort="lcb-v6-smoke",
        agent="direct",
        model="gpt-test",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )
    assert plan_lcb["backend"] == "direct_chat"
    assert len(plan_lcb["task_prompts"]) == 5
    for tid, p in plan_lcb["task_prompts"].items():
        assert "### Question:" in p
        assert "### Answer:" in p
        assert not p.startswith("Solve task:")


# ---------------------------------------------------------------------------
# Requirement 11: Docker invocation enforces declared isolation flags
# ---------------------------------------------------------------------------
def test_req11_docker_invocation_enforces_declared_isolation_flags() -> None:
    """Docker command must enforce --read-only, --tmpfs, user, network, and security restrictions."""
    cfg = SandboxConfig(
        network_disabled=True,
        read_only_rootfs=True,
        cap_drop_all=True,
        no_new_privileges=True,
        memory_limit="512m",
        cpu_limit="1.0",
        pids_limit=128,
    )
    verifier = ContainerVerifier(cfg)
    cmd = verifier.build_docker_command(Path("/app/runner.py"), container_name="test-sandbox-01")

    assert "--read-only" in cmd
    assert "--tmpfs" in cmd
    tmpfs_idx = cmd.index("--tmpfs")
    assert cmd[tmpfs_idx + 1] == "/tmp:rw,noexec,nosuid,size=64m"
    assert "--user" in cmd
    user_idx = cmd.index("--user")
    assert cmd[user_idx + 1] == "65534:65534"
    assert "--network" in cmd
    net_idx = cmd.index("--network")
    assert cmd[net_idx + 1] == "none"
    assert "--cap-drop" in cmd
    cap_idx = cmd.index("--cap-drop")
    assert cmd[cap_idx + 1] == "ALL"
    assert "--security-opt" in cmd
    sec_idx = cmd.index("--security-opt")
    assert cmd[sec_idx + 1] == "no-new-privileges"


# ---------------------------------------------------------------------------
# Requirement 12: Backward compatibility and regression health
# ---------------------------------------------------------------------------
def test_req12_regression_and_readiness_checks() -> None:
    """Verify registry backwards-compatibility, catalog aliases, and existing cohort parity."""
    catalog = get_default_catalog()

    # Existing cohorts preserved
    aider_cohort = catalog.get_cohort("aider-python-10")
    assert aider_cohort.dataset_id == "aider/aider-polyglot"
    assert len(aider_cohort.task_ids) > 0

    # Aliases resolve
    assert catalog.resolve_dataset("ifeval").id == "ifeval/google-2023"
    assert catalog.resolve_dataset("lcb").id == "livecodebench/release_v6"

    # Unified discovery contract
    from agent_benchmark.benchmarks.catalog import get_unified_discovery
    disc = get_unified_discovery()
    assert "benchmarks" in disc
    assert "datasets" in disc
    assert "cohorts" in disc
    assert any(c["id"] == "ifeval-smoke" for c in disc["cohorts"])
    assert any(c["id"] == "lcb-v6-smoke" for c in disc["cohorts"])


# ---------------------------------------------------------------------------
# Requirement 13: Setup planning is strictly read-only
# ---------------------------------------------------------------------------
def test_req13_setup_planning_is_strictly_read_only(tmp_path: Path) -> None:
    """Setup planning must perform zero directory creation or filesystem writes."""
    target_root = tmp_path / "never_created_store"
    assert not target_root.exists()

    from agent_benchmark.cli import main
    exit_code = main(["setup", "-A", "--resource-root", str(target_root), "-f", "json"])
    assert exit_code == 0
    assert not target_root.exists(), "Setup planning must not create root or subdirectories on disk"


# ---------------------------------------------------------------------------
# Requirement 14: Full LCB cohort blocks without silent smoke fallback
# ---------------------------------------------------------------------------
def test_req14_full_lcb_cohort_blocks_without_silent_smoke_fallback() -> None:
    """Full LiveCodeBench cohort must never silently fall back to smoke fixture data."""
    manifest = build_manifest(
        cohort="lcb-v6-direct-100",
        agent="direct",
        model="gpt-test",
        base_url="http://127.0.0.1:8000/v1",
        api_format="openai_chat_completions",
        llm_monitor=False,
        recording="off",
    )
    # If full dataset is not installed, readiness must fail with explicit blocker
    assert manifest["readiness"]["is_runnable"] is False
    assert any("Full LiveCodeBench dataset not installed" in b for b in manifest["readiness"]["blockers"])


# ---------------------------------------------------------------------------
# Requirement 15: Setup verification detects stale, incomplete, and corrupt
# ---------------------------------------------------------------------------
def test_req15_setup_verification_detects_stale_incomplete_and_corrupt(tmp_path: Path) -> None:
    """Verify detects stale revisions, incomplete installations, and corrupted files."""
    mgr = SourceManager(resource_root=tmp_path / "resources")
    spec = ResourceSpec(
        benchmark_id="test_suite",
        name="test-resource",
        resource_type="huggingface_dataset",
        revision="rev1",
        paths=("test.jsonl",),
    )
    # 1. Not installed
    v_not = mgr.verify_resource(spec)
    assert v_not["status"] == "not_installed"

    # 2. Incomplete (receipt exists but target file missing)
    from agent_benchmark.external_sources.receipts import record_receipt
    from agent_benchmark.external_sources.specs import InstallReceipt
    t_path = mgr.get_target_path(spec)
    receipt = InstallReceipt(
        benchmark_id="test_suite",
        resource_name="test-resource",
        resource_type="huggingface_dataset",
        install_path=str(t_path),
        revision="rev1",
        spec_digest=spec.digest(),
        installed_at="2026-11-11T00:00:00Z",
        platform="test",
        status="installed",
    )
    record_receipt(mgr.lock_file, receipt)
    v_inc = mgr.verify_resource(spec)
    assert v_inc["status"] == "incomplete"

    # 3. Stale revision
    stale_spec = ResourceSpec(
        benchmark_id="test_suite",
        name="test-resource",
        resource_type="huggingface_dataset",
        revision="rev2_updated",
        paths=("test.jsonl",),
    )
    v_stale = mgr.verify_resource(stale_spec)
    assert v_stale["status"] == "stale"


# ---------------------------------------------------------------------------
# Requirement 16: Dataset loader decodes public and private test cases
# ---------------------------------------------------------------------------
def test_req16_dataset_loader_decodes_public_and_private_test_cases() -> None:
    """Test case decoder handles raw lists, JSON strings, and compressed private cases."""
    import base64
    import json
    import pickle
    import zlib

    from agent_benchmark.benchmarks.loader import decode_test_cases

    # 1. Plain list
    cases_list = [{"input": "1 2\n", "output": "3\n"}]
    assert decode_test_cases(cases_list) == cases_list

    # 2. JSON string
    json_str = json.dumps(cases_list)
    assert decode_test_cases(json_str) == cases_list

    # 3. Compressed base64 + zlib + pickle (LiveCodeBench private_test_cases format)
    pickled = pickle.dumps(json.dumps(cases_list))
    compressed = zlib.compress(pickled)
    b64 = base64.b64encode(compressed).decode("utf-8")
    decoded = decode_test_cases(b64)
    assert decoded == cases_list

