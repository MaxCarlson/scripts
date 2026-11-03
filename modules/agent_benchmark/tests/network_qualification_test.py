from types import SimpleNamespace

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
        "local_monitor_gateway_route": {"reachable": True, "status": 405},
        "local_resolver_external_name_lookup": {"resolved": False, "error": "EAI_AGAIN"},
        "external_dns_direct": {"resolved": False, "error": "ECONNREFUSED"},
        "external_https_unlisted_sni": {"connected": False, "error": "ECONNRESET"},
        "external_https_direct_ip_no_sni": {"connected": False, "error": "ECONNRESET"},
        "proxy_environment_names": [],
    }
    effective_agent = {"network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]}

    assert set(_probe_gates(observed, effective_agent).values()) == {"PASS"}


def test_docker_resolver_external_name_lookup_fails_closed_even_when_direct_egress_is_blocked():
    observed = {
        "local_monitor_gateway_route": {"reachable": True, "status": 405},
        "local_resolver_external_name_lookup": {"resolved": True, "addresses": 2},
        "external_dns_direct": {"resolved": False, "error": "ECONNREFUSED"},
        "external_https_unlisted_sni": {"connected": False, "error": "ECONNRESET"},
        "external_https_direct_ip_no_sni": {"connected": False, "error": "ECONNRESET"},
        "proxy_environment_names": [],
    }
    effective_agent = {"network_mode": "allowlist", "allowed_hosts": ["host.docker.internal"]}

    gates = _probe_gates(observed, effective_agent)
    assert gates["local_monitor_gateway_route"] == "PASS"
    assert gates["external_https_unlisted_sni_denied"] == "PASS"
    assert gates["external_dns_name_lookup_denied"] == "FAIL"
