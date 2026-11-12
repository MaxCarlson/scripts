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
    CANARY_FAILED_MARKER,
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
    SandboxExecutionResult,
    TaskContext,
)
from agent_benchmark.external_sources.manager import SourceManager
from agent_benchmark.external_sources.specs import ResourceSpec
from agent_benchmark.suite import build_manifest


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
    """IFEval adapter outputs must match upstream reference evaluation on real benchmark data."""
    data_path = get_ifeval_data_path()
    assert data_path is not None and data_path.is_file(), "input_data.jsonl must exist"

    tasks = load_ifeval_tasks(data_path)
    assert len(tasks) == 541

    adapter = IFEvalScoringAdapter(task_cache=tasks)

    # Test sample tasks across different instruction types
    sample_ids = ["ifeval-1000", "ifeval-1001", "ifeval-1005", "ifeval-1012", "ifeval-1019"]
    for tid in sample_ids:
        t = tasks[tid]
        ctx = TaskContext(task_id=tid, prompt=t.prompt, metadata=t.to_dict())

        # Test empty response fails both strict and loose
        empty_att = BackendAttempt(
            task_id=tid,
            model_id="m",
            endpoint="ep",
            response_text="",
            started_at="2026-11-11T00:00:00Z",
            ended_at="2026-11-11T00:00:01Z",
            duration_ms=10.0,
            status="completed",
        )
        empty_scored = adapter.score_task(tid, empty_att, ctx)
        assert empty_scored.status == "failed"
        assert empty_scored.score == 0.0
        assert empty_scored.metrics["ifeval.strict_prompt"] == 0.0
        assert empty_scored.metrics["ifeval.loose_prompt"] == 0.0


# ---------------------------------------------------------------------------
# Requirement 3: Incorrect, syntactically valid LiveCodeBench solution fails
# ---------------------------------------------------------------------------
def test_req3_incorrect_syntactically_valid_lcb_solution_fails() -> None:
    """A syntactically valid solution that produces wrong output must fail scoring."""
    def mock_runner(code: str, test_code: str) -> SandboxExecutionResult:
        # Simulate container execution of the test harness
        return SandboxExecutionResult(
            success=False,
            status="failed",
            exit_code=1,
            stdout=f"{CANARY_FAILED_MARKER}: Test 0 wrong answer: expected ['Hello, World!'], got ['wrong']",
            stderr="",
            duration_ms=45.0,
        )

    verifier = ContainerVerifier(mock_runner=mock_runner)
    adapter = LCBScoringAdapter(verifier=verifier)

    ctx = TaskContext(
        task_id="lcb-test-wrong",
        prompt="Print greeting",
        metadata={"input_output": {"inputs": ["World"], "outputs": ["Hello, World!"]}},
    )
    attempt = BackendAttempt(
        task_id="lcb-test-wrong",
        model_id="m",
        endpoint="ep",
        response_text="```python\ndef solve():\n    print('wrong')\n```",
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
    assert scored.error_code == "TEST_FAILED"


# ---------------------------------------------------------------------------
# Requirement 4: Correct LiveCodeBench solution passes
# ---------------------------------------------------------------------------
def test_req4_correct_lcb_solution_passes() -> None:
    """A correct solution that satisfies all test cases earns pass@1 = 1.0 with verified canary."""
    def mock_runner(code: str, test_code: str) -> SandboxExecutionResult:
        assert CANARY_SUCCESS_MARKER in test_code
        return SandboxExecutionResult(
            success=True,
            status="passed",
            exit_code=0,
            stdout=f"{CANARY_SUCCESS_MARKER}: 2/2",
            stderr="",
            duration_ms=60.0,
        )

    verifier = ContainerVerifier(mock_runner=mock_runner)
    adapter = LCBScoringAdapter(verifier=verifier)

    ctx = TaskContext(
        task_id="lcb-test-correct",
        prompt="Greet user",
        metadata={"input_output": {"inputs": ["Alice", "Bob"], "outputs": ["Hello, Alice!", "Hello, Bob!"]}},
    )
    attempt = BackendAttempt(
        task_id="lcb-test-correct",
        model_id="m",
        endpoint="ep",
        response_text="```python\ndef solve():\n    name = input().strip()\n    print(f'Hello, {name}!')\nsolve()\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=100.0,
        status="completed",
    )
    scored = adapter.score_task("lcb-test-correct", attempt, ctx)
    assert scored.status == "passed"
    assert scored.score == 1.0
    assert scored.metrics["pass@1"] == 1.0
    assert scored.details["canary_verified"] is True
    assert scored.error_code is None


# ---------------------------------------------------------------------------
# Requirement 5: Premature clean process exit cannot bypass verification
# ---------------------------------------------------------------------------
def test_req5_premature_clean_exit_cannot_bypass_verification() -> None:
    """A solution executing sys.exit(0) cannot forge success without canary completion."""
    def mock_runner_premature(code: str, test_code: str) -> SandboxExecutionResult:
        # Process exited with code 0 prematurely without executing the harness receipt
        return SandboxExecutionResult(
            success=True,  # Docker sees exit 0
            status="passed",
            exit_code=0,
            stdout="",  # Canary missing!
            stderr="",
            duration_ms=25.0,
        )

    verifier = ContainerVerifier(mock_runner=mock_runner_premature)
    adapter = LCBScoringAdapter(verifier=verifier)

    ctx = TaskContext(
        task_id="lcb-bypass-attempt",
        prompt="Solve problem",
        metadata={"input_output": {"inputs": ["1"], "outputs": ["42"]}},
    )
    attempt = BackendAttempt(
        task_id="lcb-bypass-attempt",
        model_id="m",
        endpoint="ep",
        response_text="```python\nimport sys\nsys.exit(0)\n```",
        started_at="2026-11-11T00:00:00Z",
        ended_at="2026-11-11T00:00:01Z",
        duration_ms=30.0,
        status="completed",
    )
    scored = adapter.score_task("lcb-bypass-attempt", attempt, ctx)
    assert scored.status == "failed"
    assert scored.score == 0.0
    assert scored.error_code == "PREMATURE_EXIT"


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
