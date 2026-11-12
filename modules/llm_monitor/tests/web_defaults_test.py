"""Focused tests for persistent web defaults, CLI precedence, backward compatibility,
and protected coordinator route failure behavior.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from llm_monitor.cli import build_parser, main
from llm_monitor.gateway import OpenAIInferenceGateway, RequestEventHub
from llm_monitor.live_store import LiveInferenceStore


def test_web_parser_explicit_disabling_and_upstream_flags():
    parser = build_parser()

    # --no-gateway and -G explicitly disable gateway
    args_ng = parser.parse_args(["web", "--no-gateway"])
    assert args_ng.gateway is False

    args_g_short = parser.parse_args(["web", "-G"])
    assert args_g_short.gateway is False

    # --gateway and -g explicitly enable gateway
    args_g = parser.parse_args(["web", "--gateway"])
    assert args_g.gateway is True

    args_g_short_en = parser.parse_args(["web", "-g"])
    assert args_g_short_en.gateway is True

    # --browser and -b explicitly enable browser auto-open (no_browser=False)
    args_b = parser.parse_args(["web", "--browser"])
    assert args_b.no_browser is False

    args_b_short = parser.parse_args(["web", "-b"])
    assert args_b_short.no_browser is False

    # --no-browser and -n explicitly disable browser auto-open (no_browser=True)
    args_nb = parser.parse_args(["web", "--no-browser"])
    assert args_nb.no_browser is True

    args_n_short = parser.parse_args(["web", "-n"])
    assert args_n_short.no_browser is True

    # -N and --no-record-inferences explicitly disable recording
    args_nr = parser.parse_args(["web", "--no-record-inferences"])
    assert args_nr.record_inferences == "none"

    args_nr_short = parser.parse_args(["web", "-N"])
    assert args_nr_short.record_inferences == "none"

    args_r_none = parser.parse_args(["web", "-R", "none"])
    assert args_r_none.record_inferences == "none"

    args_r_off = parser.parse_args(["web", "-R", "off"])
    assert args_r_off.record_inferences == "off"

    # -u and --gateway-upstream
    args_u = parser.parse_args(["web", "-u", "http://127.0.0.1:1235"])
    assert args_u.gateway_upstream == "http://127.0.0.1:1235"

    args_u_long = parser.parse_args(["web", "--gateway-upstream", "http://127.0.0.1:1235"])
    assert args_u_long.gateway_upstream == "http://127.0.0.1:1235"

    # -c and --config
    args_c = parser.parse_args(["web", "-c", "custom_config.toml"])
    assert args_c.config == Path("custom_config.toml")


def test_web_cli_precedence_with_desired_windows_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[web]
port = 8788
endpoint = "http://127.0.0.1:1234"
gateway = true
gateway_upstream = "http://127.0.0.1:1235"
record_inferences = "metadata"
no_browser = true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MONITOR_CONFIG", str(config_file))

    called = {}

    def fake_run(**kwargs):
        called["run"] = kwargs
        return 0

    import llm_monitor.web as web_mod

    monkeypatch.setattr(web_mod, "run_web", fake_run)

    # 1. Default invocation uses user configuration
    assert main(["web"]) == 0
    run_opts = called["run"]
    assert run_opts["port"] == 8788
    assert run_opts["endpoint"] == "http://127.0.0.1:1234"
    assert run_opts["gateway_enabled"] is True
    assert run_opts["gateway_upstream"] == "http://127.0.0.1:1235"
    assert run_opts["record_inferences"] == "metadata"
    assert run_opts["no_browser"] is True
    assert run_opts["database"] is None

    # 2. Explicit port override
    assert main(["web", "-p", "9000"]) == 0
    assert called["run"]["port"] == 9000
    assert called["run"]["gateway_enabled"] is True

    # 3. Explicit gateway disabling with -G
    assert main(["web", "-G"]) == 0
    assert called["run"]["gateway_enabled"] is False
    assert called["run"]["record_inferences"] is None

    # 4. Explicit browser auto-open enable with -b
    assert main(["web", "-b"]) == 0
    assert called["run"]["no_browser"] is False

    # 5. Explicit recording disable with -N
    assert main(["web", "-N"]) == 0
    assert called["run"]["gateway_enabled"] is True
    assert called["run"]["record_inferences"] is None

    # 6. Explicit upstream override with -u
    assert main(["web", "-u", "http://127.0.0.1:1236"]) == 0
    assert called["run"]["gateway_upstream"] == "http://127.0.0.1:1236"


def test_web_cli_backward_compatibility_without_config(tmp_path, monkeypatch):
    nonexistent = tmp_path / "does_not_exist.toml"
    monkeypatch.setenv("LLM_MONITOR_CONFIG", str(nonexistent))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty_localappdata"))

    called = {}

    def fake_run(**kwargs):
        called["run"] = kwargs
        return 0

    import llm_monitor.web as web_mod

    monkeypatch.setattr(web_mod, "run_web", fake_run)

    assert main(["web"]) == 0
    run_opts = called["run"]
    assert run_opts["port"] == 8788
    assert run_opts["endpoint"] == "http://127.0.0.1:1234"
    assert run_opts["gateway_enabled"] is False
    assert run_opts["gateway_upstream"] == "http://127.0.0.1:1234"
    assert run_opts["record_inferences"] is None
    assert run_opts["no_browser"] is False
    assert run_opts["database"] is None


def test_web_status_and_stop_semantics_preserved(monkeypatch):
    called = {}

    def fake_status(port=None, host="127.0.0.1", state_dir=None, as_json=False):
        called["status"] = (port, as_json)
        return 0

    def fake_stop(port=None, host="127.0.0.1", execute=False, force=False, state_dir=None, timeout=5.0, as_json=False):
        called["stop"] = (port, execute, force, as_json)
        return 0

    import llm_monitor.server_lifecycle as slc

    monkeypatch.setattr(slc, "status_server", fake_status)
    monkeypatch.setattr(slc, "stop_server", fake_stop)

    # When no port is given, port passed is None to trigger descriptor auto-discovery
    assert main(["web", "status"]) == 0
    assert called["status"] == (None, False)

    assert main(["web", "stop"]) == 0
    assert called["stop"] == (None, False, False, False)

    # When port is explicitly given, it is preserved
    assert main(["web", "status", "-p", "8788"]) == 0
    assert called["status"] == (8788, False)


@pytest.mark.asyncio
async def test_gateway_upstream_protected_coordinator_no_silent_fallback():
    """Verify that when the configured protected Coordinator upstream (1235) is unavailable,
    the gateway fails with 502 and NEVER silently falls back to direct LM Studio (1234).
    """
    coordinator_url = "http://127.0.0.1:1235"
    dispatched_urls = []

    def mock_transport_handler(request: httpx.Request) -> httpx.Response:
        dispatched_urls.append(str(request.url))
        if request.url.host == "127.0.0.1" and request.url.port == 1235:
            # Simulate Coordinator connection failure
            raise httpx.ConnectError("Connection refused to Coordinator port 1235", request=request)
        if request.url.host == "127.0.0.1" and request.url.port == 1234:
            # Direct LM Studio should NOT be reached!
            return httpx.Response(200, json={"choices": [{"message": {"content": "direct_lm_studio"}}]})
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_transport_handler),
        follow_redirects=False,
        trust_env=False,
    )

    store = LiveInferenceStore()
    events = RequestEventHub()
    gateway = OpenAIInferenceGateway(
        upstream=coordinator_url,
        store=store,
        events=events,
        client=mock_client,
    )

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(gateway.router())

    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "model": "qwen2.5-coder-7b-instruct",
        "messages": [{"role": "user", "content": "hello"}],
    }
    response = client.post("/v1/chat/completions", json=payload)

    # Must return 502 Bad Gateway
    assert response.status_code == 502
    assert "Configured inference upstream is unavailable" in response.text

    # Verify requests went ONLY to the coordinator, NEVER to direct LM Studio
    assert len(dispatched_urls) == 1
    assert "127.0.0.1:1235" in dispatched_urls[0]
    assert not any("127.0.0.1:1234" in url for url in dispatched_urls)

    await gateway.close()
