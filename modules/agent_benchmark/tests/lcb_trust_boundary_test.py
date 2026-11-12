"""Trust-boundary, safe-deserialization, image-identity and parity qualification tests."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import pickle
import subprocess
import uuid
import zlib

import pytest

from agent_benchmark.benchmarks.adapters.ifeval import (
    IFEvalScoringAdapter,
    deterministic_ifeval_rng,
    load_ifeval_tasks,
)
from agent_benchmark.benchmarks.adapters.livecodebench import (
    CANARY_SUCCESS_MARKER,
    LCBProblem,
    LCBScoringAdapter,
    evaluate_problem,
)
from agent_benchmark.benchmarks.catalog import get_default_catalog
from agent_benchmark.benchmarks.loader import decode_test_cases, get_ifeval_data_path
from agent_benchmark.cli import main
from agent_benchmark.execution import (
    BackendAttempt,
    ContainerVerifier,
    SandboxConfig,
    SandboxUnavailableError,
    TaskContext,
)
from agent_benchmark.external_sources import manager as manager_mod
from agent_benchmark.external_sources.manager import SourceManager
from agent_benchmark.external_sources.specs import ResourceSpec
from agent_benchmark.sandbox_image import LCB_SANDBOX_IMAGE_DIGEST, LCB_SANDBOX_IMAGE_REF

from lcb_local_runner import run_candidate_locally


# Prompts whose upstream score depends on the global RNG (letter '#' is not a valid letter).
RNG_DEPENDENT_UPSTREAM_KEYS = frozenset({1122, 1129})


def _attempt(code: str) -> BackendAttempt:
    return BackendAttempt(
        task_id="t", model_id="m", endpoint="ep", response_text=f"```python\n{code}\n```",
        started_at="2026-11-11T00:00:00Z", ended_at="2026-11-11T00:00:01Z", duration_ms=1.0,
        status="completed",
    )


def _docker_ready() -> bool:
    v = ContainerVerifier()
    return v.is_sandbox_available() and v.is_image_available()


# --------------------------------------------------------------------------- adversarial
HIDDEN = f"HIDDEN_ANSWER_{uuid.uuid4().hex}"

SNOOP_STDIO = '''
import glob, os, sys
needle = sys.stdin.readline().strip()
hits = []
roots = {os.getcwd(), os.path.dirname(os.getcwd()), "/app", "/"}
for root in roots:
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) < 5_000_000 and needle.encode() in open(p, "rb").read():
                    hits.append(p)
            except Exception:
                pass
        if len(hits) > 5 or dirpath.count(os.sep) > 4:
            break
for k, v in os.environ.items():
    if needle in v:
        hits.append("env:" + k)
for name in ("runner.py", "../runner.py", "/app/runner.py", "expected.json"):
    if os.path.exists(name):
        hits.append("exists:" + name)
print("LEAK:" + ",".join(hits) if hits else "NOLEAK")
'''


def _snoop_problem() -> LCBProblem:
    return LCBProblem(
        question_id="adv", question_title="adv", difficulty="easy", contest_date="", prompt="p",
        starter_code="", task_id="adv",
        input_output={"inputs": [HIDDEN + "\n"], "outputs": [HIDDEN + "\n"], "fn_name": None},
    )


def _assert_no_leak(verifier: ContainerVerifier) -> None:
    # Give the contestant the secret as *input* so its filesystem scan can look for the expected
    # answer; the expected output is identical and only held by the host.
    res = verifier.run_candidate(SNOOP_STDIO, HIDDEN + "\n")
    assert res.status in ("passed", "failed")
    assert "LEAK:" not in res.stdout.replace("NOLEAK", ""), res.stdout
    assert res.stdout.strip() == "NOLEAK"

    verdict = evaluate_problem(verifier, SNOOP_STDIO, _snoop_problem())
    # Scanner prints NOLEAK, which differs from the hidden expected output => wrong answer.
    assert verdict.status == "failed" and verdict.error_code == "WRONG_ANSWER"
    assert HIDDEN not in verdict.stdout_preview


def test_adversarial_candidate_cannot_find_supervisor_or_hidden_answers_local_layout() -> None:
    _assert_no_leak(ContainerVerifier(mock_runner=run_candidate_locally))


@pytest.mark.skipif(not _docker_ready(), reason="Docker daemon and pinned verifier image not available")
def test_adversarial_candidate_isolated_in_real_docker_sandbox() -> None:
    """Qualified environment: real pinned container; skipped unless Docker + image already present."""
    verifier = ContainerVerifier()
    _assert_no_leak(verifier)
    adapter = LCBScoringAdapter(verifier=verifier)
    io = {"inputs": ["Alice\n"], "outputs": ["Hello, Alice!\n"], "fn_name": None}
    ctx = TaskContext(task_id="d", prompt="p", metadata={"input_output": io})
    ok = adapter.score_task("d", _attempt("print(f'Hello, {input().strip()}!')"), ctx)
    bad = adapter.score_task("d", _attempt("print('nope')"), ctx)
    forged = adapter.score_task("d", _attempt(f"import sys\nprint('{CANARY_SUCCESS_MARKER}')\nsys.exit(0)"), ctx)
    assert ok.status == "passed" and ok.score == 1.0
    assert bad.status == "failed" and forged.status == "failed"


def test_container_mount_contains_only_solution_and_worker_never_expected_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structural proof of the trust boundary on the exact docker command that would be executed."""
    from agent_benchmark.execution import container_verify as cv

    verifier = ContainerVerifier()
    monkeypatch.setattr(verifier, "is_sandbox_available", lambda: True)
    monkeypatch.setattr(verifier, "is_image_available", lambda: True)
    captured: list[dict] = []

    def fake_run(cmd, **kwargs):
        mount = cmd[cmd.index("-v") + 1]
        host_dir = Path(mount.rsplit(":/app:ro", 1)[0])
        files = {p.name: p.read_text(encoding="utf-8") for p in host_dir.iterdir()}
        captured.append({"cmd": cmd, "files": files, "input": kwargs.get("input")})
        return subprocess.CompletedProcess(cmd, 0, stdout="out\n", stderr="")

    monkeypatch.setattr(cv.subprocess, "run", fake_run)

    prob_io = {"inputs": ["in\n"], "outputs": [HIDDEN + "\n"], "fn_name": None}
    verdict = evaluate_problem(
        verifier, "print('out')",
        LCBProblem("q", "q", "easy", "", "p", "", prob_io, "q"),
    )
    assert verdict.status == "failed"  # host compared against private expected output

    fn_io = {"inputs": ["[1]\n"], "outputs": [HIDDEN], "fn_name": "f"}
    evaluate_problem(verifier, "def f(x): return x", LCBProblem("q", "q", "easy", "", "p", "", fn_io, "q"))

    assert len(captured) == 2
    assert set(captured[0]["files"]) == {"solution.py"}
    assert set(captured[1]["files"]) == {"solution.py", "worker.py"}
    for rec in captured:
        blob = json.dumps(rec["files"]) + json.dumps(rec["cmd"]) + str(rec["input"])
        assert HIDDEN not in blob
        assert "runner.py" not in rec["cmd"][-3:]
        cmd = rec["cmd"]
        assert cmd[cmd.index("--network") + 1] == "none"
        assert "--read-only" in cmd and ":/app:ro" in cmd[cmd.index("-v") + 1]
        assert cmd[cmd.index("--pull") + 1] == "never"
        assert LCB_SANDBOX_IMAGE_REF in cmd
        assert cmd[cmd.index("--cap-drop") + 1] == "ALL"


def test_stdout_forgery_and_premature_exit_cannot_pass_functional_problems() -> None:
    verifier = ContainerVerifier(mock_runner=run_candidate_locally)
    io = {"inputs": ["2\n3\n"], "outputs": ["5"], "fn_name": "add"}
    prob = LCBProblem("q", "q", "easy", "", "p", "", io, "q")
    good = evaluate_problem(verifier, "def add(a, b): return a + b", prob)
    wrong = evaluate_problem(verifier, "def add(a, b): return 0", prob)
    exit_early = evaluate_problem(verifier, "import sys\nsys.exit(0)\ndef add(a,b): return a+b", prob)
    boom = evaluate_problem(verifier, "def add(a, b): raise ValueError('x')", prob)
    assert good.status == "passed"
    assert wrong.error_code == "WRONG_ANSWER"
    assert exit_early.error_code == "PREMATURE_EXIT"
    assert boom.error_code == "RUNTIME_ERROR"
    # Success can only be earned by matching the private expected output held by the host.
    forged_wrong = evaluate_problem(
        verifier,
        'import os\nos.write(1, b\'{"result": 999}\\n\')\nos._exit(0)',
        prob,
    )
    assert forged_wrong.status == "failed"


def test_corrupt_test_data_is_infrastructure_invalid() -> None:
    verifier = ContainerVerifier(mock_runner=run_candidate_locally)
    for io, code in (
        ({"inputs": ["1\n"], "outputs": []}, "MISSING_BENCHMARK_DATA"),
        ({"inputs": ["1\n", "2\n"], "outputs": ["1\n"]}, "CORRUPT_BENCHMARK_DATA"),
    ):
        v = evaluate_problem(verifier, "print(1)", LCBProblem("q", "q", "e", "", "p", "", io, "q"))
        assert v.status == "infrastructure_invalid" and v.error_code == code


def test_sandbox_unavailable_is_infrastructure_not_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = ContainerVerifier()
    monkeypatch.setattr(verifier, "is_sandbox_available", lambda: True)
    monkeypatch.setattr(verifier, "is_image_available", lambda: False)
    with pytest.raises(SandboxUnavailableError, match="docker pull"):
        verifier.run_candidate("print(1)", "")


# --------------------------------------------------------------------------- deserialization
def _b64z(blob: bytes) -> str:
    return base64.b64encode(zlib.compress(blob)).decode()


def test_malicious_pickle_does_not_execute_on_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "pwned.txt"

    class Evil:
        def __reduce__(self):
            return (exec, (f"open({str(marker)!r}, 'w').write('pwned')",))

    # pickle.loads must never be reachable from the loader
    monkeypatch.setattr(pickle, "loads", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pickle.loads called")))

    for payload in (pickle.dumps(Evil()), pickle.dumps(Evil(), protocol=0), pickle.dumps(Evil(), protocol=2)):
        assert decode_test_cases(_b64z(payload)) == []
        assert not marker.exists()

    # Containers/objects other than a bare string are refused too (no object construction at all)
    assert decode_test_cases(_b64z(pickle.dumps([{"input": "1", "output": "2"}]))) == []


def test_legacy_livecodebench_pickled_json_string_still_decodes() -> None:
    cases = [{"input": "1\n", "output": "2\n", "testtype": "stdin"}]
    for proto in (0, 2, 4, 5):
        blob = pickle.dumps(json.dumps(cases), protocol=proto)
        assert decode_test_cases(_b64z(blob)) == cases
    assert decode_test_cases(_b64z(json.dumps(cases).encode())) == cases  # zlib+json variant


def test_decompression_bomb_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_benchmark.benchmarks import loader

    monkeypatch.setattr(loader, "_MAX_DECOMPRESSED_BYTES", 1024)
    assert decode_test_cases(_b64z(pickle.dumps("x" * 10_000))) == []


# --------------------------------------------------------------------------- image identity
class _FakeDocker:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls: list[list[str]] = []

    def run(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if self.mode == "present":
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f"sha256:abc|{json.dumps(['python@' + LCB_SANDBOX_IMAGE_DIGEST])}\n", stderr="",
            )
        if self.mode == "missing":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=f"Error: No such image: {cmd[3]}")
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="failed to connect to the docker API ... daemon running?",
        )


def _lcb_image_spec() -> ResourceSpec:
    bench = get_default_catalog().get_benchmark("livecodebench")
    decl = next(d for d in bench.resources if d.type == "container_image")
    return ResourceSpec.from_declaration("livecodebench", decl)


def test_image_identity_is_single_pinned_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _lcb_image_spec()
    assert spec.url == LCB_SANDBOX_IMAGE_REF == SandboxConfig().image
    assert "@sha256:" in LCB_SANDBOX_IMAGE_REF and LCB_SANDBOX_IMAGE_REF.endswith(LCB_SANDBOX_IMAGE_DIGEST)


@pytest.mark.parametrize(
    ("mode", "available", "verify_status", "state"),
    [("present", True, "verified", "available"), ("missing", False, "not_installed", "missing"),
     ("down", False, "unavailable", "unavailable")],
)
def test_setup_status_verify_install_agree_on_image_identity(
    mode: str, available: bool, verify_status: str, state: str, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _FakeDocker(mode)
    monkeypatch.setattr(manager_mod.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(manager_mod.subprocess, "run", fake.run)
    spec = _lcb_image_spec()
    mgr = SourceManager(tmp_path / "root")

    plan = mgr.plan_resource(spec)
    verify = mgr.verify_resource(spec)
    assert plan["installed"] is available
    assert verify["status"] == verify_status
    assert plan["image_reference"] == verify["image_reference"] == LCB_SANDBOX_IMAGE_REF

    rc = main(["setup", "status", "-d", "livecodebench", "-f", "json", "--resource-root", str(tmp_path / "root")])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)["resources"]
    img = next(r for r in rows if r["resource_type"] == "container_image")
    assert img["state"] == state and img["image_reference"] == LCB_SANDBOX_IMAGE_REF

    if available:
        receipt = mgr.install_resource(spec, execute=True)
        assert receipt.install_path == f"docker://{LCB_SANDBOX_IMAGE_REF}"
    else:
        with pytest.raises(RuntimeError):
            mgr.install_resource(spec, execute=True)
        assert mgr.plan_resource(spec)["installed"] is False

    # Every docker invocation inspected exactly the reference the verifier executes
    for call in fake.calls:
        assert call[:3] == ["docker", "image", "inspect"] and call[3] == LCB_SANDBOX_IMAGE_REF


# --------------------------------------------------------------------------- IFEval parity
def test_ifeval_adapter_matches_upstream_evaluator_per_task_for_all_541() -> None:
    from agent_benchmark.benchmarks.ifeval import evaluation_lib as upstream

    data_path = get_ifeval_data_path()
    assert data_path is not None
    resp_path = data_path.parent / "input_response_data.jsonl"
    tasks = load_ifeval_tasks(data_path)
    inputs = upstream.read_prompt_list(str(data_path))
    responses = upstream.read_prompt_to_response_dict(str(resp_path))
    assert len(inputs) == 541 and len(responses) == 541

    adapter = IFEvalScoringAdapter(task_cache=tasks)
    mismatches: list[str] = []
    for inp in inputs:
        task_id = f"ifeval-{inp.key}"
        task = tasks[task_id]
        assert task.prompt == inp.prompt
        if inp.key in RNG_DEPENDENT_UPSTREAM_KEYS:
            # Upstream draws from the global RNG for these prompts (invalid kwargs); compare under the
            # adapter's documented per-task seeding.
            with deterministic_ifeval_rng(task_id):
                up_strict = upstream.test_instruction_following_strict(inp, responses)
            with deterministic_ifeval_rng(task_id):
                up_loose = upstream.test_instruction_following_loose(inp, responses)
        else:
            up_strict = upstream.test_instruction_following_strict(inp, responses)
            up_loose = upstream.test_instruction_following_loose(inp, responses)
        att = BackendAttempt(
            task_id=task_id, model_id="m", endpoint="ep", response_text=responses[inp.prompt],
            started_at="2026-11-11T00:00:00Z", ended_at="2026-11-11T00:00:01Z", duration_ms=1.0,
            status="completed",
        )
        scored = adapter.score_task(task_id, att, TaskContext(task_id=task_id, prompt=inp.prompt, metadata={}))
        m = scored.metrics
        expected = {
            "ifeval.strict_prompt": float(bool(up_strict.follow_all_instructions)),
            "ifeval.loose_prompt": float(bool(up_loose.follow_all_instructions)),
            "ifeval.strict_instructions_passed": sum(up_strict.follow_instruction_list),
            "ifeval.loose_instructions_passed": sum(up_loose.follow_instruction_list),
            "ifeval.instructions_total": len(inp.instruction_id_list),
        }
        for k, v in expected.items():
            if m[k] != v:
                mismatches.append(f"{task_id}:{k}: adapter={m[k]} upstream={v}")
    assert not mismatches, mismatches[:10]
