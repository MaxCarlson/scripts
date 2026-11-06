from types import SimpleNamespace

from starlette.requests import Request

from resource_coordinator.config import CoordinatorConfig, ProcessConfig, build_system


def _request(process_name: str, *, token: str | None = None) -> Request:
    headers = [] if token is None else [(b"authorization", f"Bearer {token}".encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/_coordinator/logs/{process_name}",
            "headers": headers,
            "query_string": b"",
            "path_params": {"process_name": process_name},
        }
    )


def _run_synchronous_coroutine(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("handler unexpectedly performed asynchronous I/O")


def test_miner_log_alias_and_unknown_process_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "unit-test-token")
    log_path = tmp_path / "krig_miner.log"
    log_path.write_bytes(b"miner output\n")
    config = CoordinatorConfig(
        processes={
            "krig_miner": ProcessConfig(
                name="krig_miner", backend="fake", stdout_log_path=str(log_path)
            )
        }
    )
    system = build_system(config, use_fake_processes=True)
    system.gateway.admission_controller.service = SimpleNamespace(system=system)
    system.supervisors["krig_miner"].backend.stdout_log_path = str(log_path)

    alias_response = _run_synchronous_coroutine(
        system.gateway.handle_coordinator_logs(_request("miner", token="unit-test-token"))
    )
    unknown_response = _run_synchronous_coroutine(
        system.gateway.handle_coordinator_logs(_request("not-a-process", token="unit-test-token"))
    )
    denied_response = _run_synchronous_coroutine(system.gateway.handle_coordinator_logs(_request("miner")))

    assert alias_response.status_code == 200
    assert alias_response.body == b"miner output\n"
    assert unknown_response.status_code == 404
    assert unknown_response.body == b'{"error":"Unknown configured process: not-a-process"}'
    assert denied_response.status_code == 403
