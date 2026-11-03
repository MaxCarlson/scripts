from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from agent_benchmark.harbor.runner import PreflightCheckError, execute_harbor_run
from agent_benchmark.network_receipt import REQUIRED_GATES, canonical_sha256, make_receipt
from agent_benchmark.study_network_policy import NETWORK_POLICY


class Dispatched(Exception):
    pass


@pytest.fixture
def study(tmp_path, monkeypatch):
    runtime = {"image": "synthetic", "monitor_url": "http://host.docker.internal:8788/v1/chat/completions"}
    manifest = {
        "prompt_policy": {"id": "sv0-unmodified-v1"},
        "provenance": {"effective_base_url": "http://host.docker.internal:8788/v1"},
    }
    monkeypatch.setattr("agent_benchmark.network_receipt.snapshot_digest", lambda *_: "a" * 64)
    monkeypatch.setattr("agent_benchmark.network_receipt.runtime_fingerprint", lambda *_: runtime.copy())
    report = {
        "status": "PASS",
        "container_cleanup": "PASS",
        "inference": "never",
        "benchmark_tasks": "never",
        "container_created": True,
        "egress_sidecar_enabled": True,
        "policy_id": "sv-network-policy-v1",
        "network_policy": NETWORK_POLICY,
        "docker_image": "synthetic",
        "effective_agent_policy": {"network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]},
        "gates": {gate: "PASS" for gate in REQUIRED_GATES},
        "probes": {
            "agent_phase_exit_code": 0,
            "verifier_no_network_exit_code": 0,
            "local_monitor_gateway_route": {"reachable": True},
            "external_dns_direct": {"resolved": False},
            "local_resolver_external_name_lookup": {"resolved": False},
            "external_https_unlisted_sni": {"connected": False},
            "external_https_direct_ip_no_sni": {"connected": False},
            "proxy_environment_names": [],
        },
    }
    receipt = make_receipt(report, manifest, tmp_path, image="synthetic", monitor_url=runtime["monitor_url"])
    path = tmp_path / "network-qualification.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    plan = SimpleNamespace(
        readiness=SimpleNamespace(is_runnable=True),
        selected_tasks=["task"],
        agent="opencode",
        base_url=manifest["provenance"]["effective_base_url"],
    )
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_docker_readiness", lambda: (True, "ok"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.check_harbor_readiness", lambda: (True, "ok"))
    monkeypatch.setattr("agent_benchmark.harbor.runner.command_lock", lambda _: nullcontext())
    monkeypatch.setattr("agent_benchmark.harbor.runner.build_harbor_command", lambda *a, **k: ["harbor", "run"])
    snapshot = tmp_path / "task"
    snapshot.mkdir()
    row = {"source_git_url": "url", "source_revision": "revision", "network_policy": NETWORK_POLICY}
    monkeypatch.setattr(
        "agent_benchmark.study_network_policy.verify_study_network_manifest", lambda *_: (snapshot, row)
    )
    registry = tmp_path / "registry" / "registry.json"
    registry.parent.mkdir()
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("agent_benchmark.suite_revision.verify_saved_registry_snapshot", lambda *_: registry.resolve())
    monkeypatch.setattr("agent_benchmark.study_task_integrity.verify_study_task_trees", lambda *_: None)
    calls = []

    def dispatch(*args, **kwargs):
        calls.append(args)
        raise Dispatched()

    monkeypatch.setattr("agent_benchmark.harbor.runner.subprocess.run", dispatch)

    def run():
        return execute_harbor_run(
            plan,
            execute=True,
            output_dir=tmp_path / "out",
            jobs_dir=tmp_path / "jobs",
            state_dir=tmp_path / "state",
            study_adapter=True,
            study_run_dir=tmp_path,
            study_manifest=manifest,
            study_policy=manifest["prompt_policy"],
            registry_path=registry,
        )

    return path, receipt, calls, run


def test_valid_synthetic_receipt_reaches_harbor_once(study):
    _, _, calls, run = study
    with pytest.raises(RuntimeError, match="Harbor run interrupted"):
        run()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "expired",
        "altered",
        "mismatch",
        "incomplete",
        "dns",
        "egress",
        "verifier",
        "cleanup",
        "failed",
        "malformed",
        "runtime",
        "policy",
        "evidence",
    ],
)
def test_invalid_synthetic_receipt_never_reaches_harbor(study, failure):
    path, receipt, calls, run = study
    if failure == "missing":
        path.unlink()
    elif failure == "malformed":
        path.write_text("{", encoding="utf-8")
    else:
        if failure == "expired":
            receipt["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            receipt["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        elif failure == "altered":
            receipt["status"] = "FAIL"
        elif failure == "mismatch":
            receipt["task_snapshot_sha256"] = "b" * 64
        elif failure == "incomplete":
            del receipt["gates"]["policy"]
        elif failure == "dns":
            receipt["gates"]["external_dns_name_lookup_denied"] = "FAIL"
        elif failure == "egress":
            receipt["gates"]["external_https_direct_ip_no_sni_denied"] = "FAIL"
        elif failure == "verifier":
            receipt["gates"]["verifier_no_network_denies_monitor"] = "FAIL"
        elif failure == "cleanup":
            receipt["container_cleanup"] = "FAIL"
        elif failure == "runtime":
            receipt["runtime"]["image"] = "different"
        elif failure == "policy":
            receipt["study_policy_sha256"] = "c" * 64
        elif failure == "evidence":
            receipt["evidence"]["probes"]["external_dns_direct"]["resolved"] = True
        elif failure == "failed":
            receipt["status"] = "FAIL"
        if failure != "altered":
            receipt["sha256"] = canonical_sha256({k: v for k, v in receipt.items() if k != "sha256"})
        path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(PreflightCheckError, match="NETWORK_QUALIFICATION_"):
        run()
    assert calls == []
