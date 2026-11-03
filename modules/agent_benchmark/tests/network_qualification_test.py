from types import SimpleNamespace

import pytest

from agent_benchmark.network_qualification import (
    _egress_control_blocker,
    _probe_gates,
    _result_fields,
    main,
)


def test_harbor_exec_result_uses_return_code_field():
    result = SimpleNamespace(return_code=0, stdout='{"probe":"ok"}', stderr=None)

    assert _result_fields(result) == (0, '{"probe":"ok"}', "")


def test_unsupported_harbor_egress_control_fails_before_probe_container():
    assert _egress_control_blocker(False) == (
        "Harbor egress-control sidecar is not enabled; no probe container started"
    )
    assert _egress_control_blocker(True) is None


def test_network_qualification_defaults_to_nonexecuting_preview(capsys, monkeypatch):
    monkeypatch.setattr(
        "agent_benchmark.network_qualification._qualify",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("container execution is opt-in")),
    )

    assert main([]) == 0
    output = capsys.readouterr().out
    assert '"status": "UNKNOWN"' in output
    assert '"inference": "never"' in output
    assert '"benchmark_tasks": "never"' in output


def test_allowlisted_monitor_passes_while_external_dns_and_connections_are_denied():
    observed = {
        "local_monitor_gateway_route": {"reachable": True, "status": 405, "method": "OPTIONS"},
        "local_resolver_external_name_lookup": {"resolved": False, "error": "EAI_AGAIN"},
        "external_dns_direct": {"resolved": False, "error": "ECONNREFUSED"},
        "external_tcp_direct_ip": {"connected": False},
        "external_https_unlisted_sni": {"connected": False, "error": "ECONNRESET"},
        "external_https_direct_ip_no_sni": {"connected": False, "error": "ECONNRESET"},
        "proxy_environment_names": [],
    }
    effective_agent = {"network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]}

    assert set(_probe_gates(observed, effective_agent).values()) == {"PASS"}


def test_docker_resolver_external_name_lookup_fails_closed_even_when_direct_egress_is_blocked():
    observed = {
        "local_monitor_gateway_route": {"reachable": True, "status": 405, "method": "OPTIONS"},
        "local_resolver_external_name_lookup": {"resolved": True, "addresses": 2},
        "external_dns_direct": {"resolved": False, "error": "ECONNREFUSED"},
        "external_tcp_direct_ip": {"connected": False},
        "external_https_unlisted_sni": {"connected": False, "error": "ECONNRESET"},
        "external_https_direct_ip_no_sni": {"connected": False, "error": "ECONNRESET"},
        "proxy_environment_names": [],
    }
    effective_agent = {"network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]}

    gates = _probe_gates(observed, effective_agent)
    assert gates["local_monitor_gateway_route"] == "PASS"
    assert gates["external_https_unlisted_sni_denied"] == "PASS"
    assert gates["external_dns_name_lookup_denied"] == "FAIL"


def test_producer_binds_report_to_prepared_run_without_live_probe(tmp_path, monkeypatch, capsys):
    import json
    from datetime import datetime, timezone

    manifest = {
        "run_id": "synthetic-run",
        "prompt_policy": {"id": "synthetic"},
        "provenance": {"effective_base_url": "http://host.docker.internal:8788/v1"},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    import sys

    monkeypatch.setenv("HARBOR_025_PYTHON", sys.executable)
    runtime = {"image": "synthetic", "monitor_url": "http://host.docker.internal:8788/v1/chat/completions"}
    monkeypatch.setattr("agent_benchmark.network_receipt.runtime_fingerprint", lambda *_: runtime.copy())
    monkeypatch.setattr("agent_benchmark.network_receipt.snapshot_digest", lambda *_: "a" * 64)

    async def synthetic_probe(**_):
        return {
            "status": "PASS",
            "gates": {},
            "container_cleanup": "PASS",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    monkeypatch.setattr("agent_benchmark.network_qualification._qualify", synthetic_probe)

    def run_synthetic(coroutine):
        coroutine.close()
        return {
            "status": "PASS",
            "gates": {},
            "container_cleanup": "PASS",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    monkeypatch.setattr("agent_benchmark.network_qualification.asyncio.run", run_synthetic)
    assert main(["-x", "-r", str(tmp_path), "-i", "synthetic"]) == 1
    receipt = json.loads((tmp_path / "network-qualification.json").read_text(encoding="utf-8"))
    assert receipt["task_snapshot_sha256"] == "a" * 64
    assert receipt["runtime"] == runtime
    assert receipt["evidence"]["gates"] == {}
    from agent_benchmark.network_receipt import ReceiptRejected, validate_receipt
    import pytest

    with pytest.raises(ReceiptRejected, match="FAILED"):
        validate_receipt(tmp_path, manifest)
    capsys.readouterr()


def test_direct_tcp_success_cannot_pass_containment():
    observed = {
        "local_monitor_gateway_route": {"reachable": True, "status": 405, "method": "OPTIONS"},
        "local_resolver_external_name_lookup": {"resolved": False},
        "external_dns_direct": {"resolved": False},
        "external_https_unlisted_sni": {"connected": False},
        "external_https_direct_ip_no_sni": {"connected": False},
        "external_tcp_direct_ip": {"connected": True},
        "proxy_environment_names": [],
    }
    result = _probe_gates(observed, {"network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]})
    assert result.get("external_tcp_direct_ip_denied") == "FAIL"


def test_dns_negative_response_is_not_network_denial():
    observed = {
        "external_dns_direct": {"resolved": False, "error": "ENOTFOUND"},
        "local_resolver_external_name_lookup": {"resolved": False, "error": "ENOTFOUND"},
    }
    result = _probe_gates(observed, {})
    assert result["external_dns_direct_denied"] == "FAIL"
    assert result["external_dns_name_lookup_denied"] == "FAIL"


def test_producer_refuses_a_different_harbor_interpreter(tmp_path, monkeypatch, capsys):
    import sys
    from pathlib import Path

    other = tmp_path / "other-python"
    other.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("HARBOR_025_PYTHON", str(other))
    monkeypatch.setattr("agent_benchmark.network_qualification._qualify", lambda **_: pytest.fail("probe called"))
    assert Path(sys.executable).resolve() != other.resolve()
    assert main(["-x", "-r", str(tmp_path)]) == 1
    assert "interpreter used for dispatch" in capsys.readouterr().out
