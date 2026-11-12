from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace

from resource_coordinator import cli


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class _Client:
    def __init__(self, state, post_result=None):
        self.state = state
        self.post_result = post_result or _Response({"status": "released", "session_id": "session-1",
                                                    "disposition": {"operation_id": "op-1",
                                                                    "session_id": "session-1",
                                                                    "operator": "test-operator",
                                                                    "miner_restart_eligible": True,
                                                                    "restoration": {"operator_override": True,
                                                                                    "independently_verified": False}}})
        self.gets = []
        self.posts = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url):
        self.gets.append(url)
        if url.endswith("/maintenance/status"):
            return _Response(self.state)
        return _Response({"service_state": "ready"})

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.post_result


def test_maintenance_reconcile_is_read_only_by_default(monkeypatch, capsys):
    client = _Client({"state": "recovery_required", "operation_id": "op-1", "session_id": "session-1",
                      "owner": "optimizer", "registered_process_count": 1,
                      "recovery_required_reason": "process state uncertain"})
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: client)
    args = cli.parse_args(["maintenance", "reconcile", "-j"])
    assert cli.cmd_maintenance(args) == 2
    assert len(client.gets) == 2
    assert client.posts == []
    output = json.loads(capsys.readouterr().out)
    assert output["classification"] == "operator_required"
    assert output["maintenance"]["operation_id"] == "op-1"


def test_maintenance_force_reconcile_resolves_identity_and_sends_audited_payload(monkeypatch, capsys):
    client = _Client({"state": "recovery_required", "operation_id": "op-1", "session_id": "session-1"})
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(cli, "_operator_token", lambda: "test-secret")
    monkeypatch.setattr(cli.getpass, "getuser", lambda: "test-operator")
    args = cli.parse_args(["maintenance", "reconcile", "-f", "-r", "operator verified", "--no-resume-miner", "-j"])
    assert cli.cmd_maintenance(args) == 0
    url, kwargs = client.posts[0]
    assert url.endswith("/_coordinator/maintenance/release")
    assert kwargs["headers"]["Authorization"] == "Bearer test-secret"
    assert kwargs["json"] == {
        "operator": "test-operator", "operation_id": "op-1", "session_id": "session-1",
        "restoration_verified": False, "resume_miner": False, "operator_override": True,
        "override_reason": "operator verified", "restoration_evidence": {},
    }
    output = capsys.readouterr().out
    assert "test-secret" not in output
    assert json.loads(output)["status"] == "released"


def test_maintenance_force_rejects_stale_identity_without_release(monkeypatch):
    client = _Client({"state": "recovery_required", "operation_id": "op-1", "session_id": "session-1"})
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: client)
    args = cli.parse_args(["maintenance", "reconcile", "-f", "-r", "reviewed", "-o", "old-op", "-j"])
    assert cli.cmd_maintenance(args) == 2
    assert client.posts == []


def test_maintenance_force_does_not_release_when_status_read_is_not_successful(monkeypatch, capsys):
    client = _Client({"state": "recovery_required", "operation_id": "op-1", "session_id": "session-1"})
    original_get = client.get

    def unavailable_get(url):
        response = original_get(url)
        response.status_code = 503
        return response

    client.get = unavailable_get
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(cli, "_operator_token", lambda: "test-secret")
    args = cli.parse_args(["maintenance", "reconcile", "-f", "-r", "reviewed", "-j"])

    assert cli.cmd_maintenance(args) == 2
    assert client.posts == []
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_maintenance_force_rejects_weak_release_disposition(monkeypatch, capsys):
    weak_ack = _Response({"status": "released", "session_id": "session-1",
                         "disposition": {"operation_id": "other-op", "session_id": "session-1"}})
    client = _Client({"state": "recovery_required", "operation_id": "op-1", "session_id": "session-1"},
                     post_result=weak_ack)
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(cli, "_operator_token", lambda: "test-secret")
    args = cli.parse_args(["maintenance", "reconcile", "-f", "-r", "reviewed", "-j"])

    assert cli.cmd_maintenance(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_recover_apply_calls_authenticated_automatic_recovery_endpoint(monkeypatch, capsys):
    class Response:
        status_code = 200
        content = b'{"status":"reconciled"}'
        text = content.decode()

        @staticmethod
        def json():
            return {"status": "reconciled", "classification": "auto_recovered"}

    class Client:
        def __init__(self, **_kwargs):
            self.posts = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return Response()

    client = Client()
    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(cli, "load_token", lambda **_kwargs: "safe-test-token")
    args = cli.parse_args(["recover", "-a", "-j"])
    assert cli.cmd_recover(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "reconciled"
    url, kwargs = client.posts[0]
    assert url.endswith("/_coordinator/recovery/auto")
    assert kwargs["headers"]["Authorization"] == "Bearer safe-test-token"
    assert kwargs["json"] == {}


def test_recover_maintenance_alias_delegates_to_dedicated_handler(monkeypatch):
    observed = []
    monkeypatch.setattr(cli, "cmd_maintenance", lambda args: observed.append(args) or 7)
    args = cli.parse_args(["recover", "--maintenance", "-f", "-n", "reviewed"])
    assert cli.cmd_recover(args) == 7
    assert observed[0].maintenance_command == "reconcile"
    assert observed[0].force is True
    assert observed[0].reason == "reviewed"


def _stub_telemetry(monkeypatch, cli_module, *, gateway_response=None, gateway_error=None, local_system=None):
    from resource_coordinator.monitors import cpu, gpu

    monkeypatch.setattr(cli_module, "load_config", lambda _path: SimpleNamespace(processes={"krig_miner": object()}))
    monkeypatch.setattr(cpu, "CpuMonitor", lambda: SimpleNamespace(sample=lambda: 11.0))
    monkeypatch.setattr(gpu, "NvidiaGpuMonitor", lambda: SimpleNamespace(get_metrics=lambda: _empty_metrics()))
    if local_system is not None:
        monkeypatch.setattr(cli_module, "build_system", lambda _config: local_system)

    class AsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _url):
            if gateway_error:
                raise gateway_error
            return SimpleNamespace(status_code=200, json=lambda: gateway_response)

    monkeypatch.setattr(cli_module.httpx, "AsyncClient", AsyncClient)


async def _empty_metrics():
    return []


def test_offline_recovery_assessment_reports_upgrade_receipt_without_sensitive_fields(monkeypatch, tmp_path):
    from resource_coordinator import installation

    receipt = tmp_path / "upgrade-receipt.json"
    receipt.write_text(json.dumps({"phase": "RECOVERY_REQUIRED", "operation_id": "upgrade-123",
                                   "token": "must-not-leak", "command": "secret command"}), encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", lambda _path: SimpleNamespace(
        service=SimpleNamespace(state_persistence_path="")))
    monkeypatch.setattr(installation.InstallationPaths, "discover", lambda: SimpleNamespace(upgrade_receipt=receipt))

    result = cli._offline_recovery_assessment("http://offline", "ConnectError")

    assert result["classification"] == "blocked"
    assert result["assessment_mode"] == "offline_diagnostic_only"
    assert result["upgrade_receipt"] == {"status": "recovery_required", "phase": "RECOVERY_REQUIRED",
                                         "operation_id": "upgrade-123"}
    assert result["upgrade_recovery_command"] == "rc system recovery status"
    assert "must-not-leak" not in json.dumps(result)
    assert "secret command" not in json.dumps(result)


def test_telemetry_uses_coordinator_process_ownership_when_online(monkeypatch, capsys):
    payload = {"processes": {"krig_miner": {"state": "running", "pid": 456,
                                                "is_coordinator_owned": True,
                                                "lifecycle_owner": "coordinator"}}}
    _stub_telemetry(monkeypatch, cli, gateway_response=payload)
    assert asyncio.run(cli._async_diagnose(None, "http://gateway", True)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["managed_miner"]["pid"] == 456
    assert data["managed_miner"]["ownership_verified"] is True
    assert data["managed_miner"]["ownership_provenance"] == "running_coordinator_status"


def test_offline_telemetry_marks_local_process_ownership_unverifiable_and_closes_gateway(monkeypatch, capsys):
    class Gateway:
        closed = False

        async def close(self):
            self.closed = True

    gateway = Gateway()

    class Adapter:
        async def status(self):
            return SimpleNamespace(to_dict=lambda: {"state": "running", "pid": 99,
                                                     "lifecycle_owner": "unmanaged"})

    system = SimpleNamespace(gateway=gateway, miner_adapter=Adapter())
    import httpx
    _stub_telemetry(monkeypatch, cli, gateway_error=httpx.ConnectError("offline"), local_system=system)
    assert asyncio.run(cli._async_diagnose(None, "http://gateway", True)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["managed_miner"]["ownership_verified"] is False
    assert data["managed_miner"]["ownership_note"].startswith("ownership_unverifiable_offline")
    assert gateway.closed is True
