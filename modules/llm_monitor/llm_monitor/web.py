"""Standalone local browser host lifecycle."""

from __future__ import annotations

import json
import logging
import secrets
import threading
import webbrowser
from urllib.parse import urlsplit

from .inference_service import InferenceMonitoringService
from .inference_web import create_inference_web_app
from .providers import LMStudioClient
from .gateway import OpenAIInferenceGateway, RequestEventHub, validate_gateway_upstream


def validate_endpoint(endpoint: str) -> str:
    """Validate an explicitly configured HTTP(S) provider base URL without credentials."""
    try:
        parts = urlsplit(endpoint)
        valid = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
        )
        if not valid:
            raise ValueError
        _ = parts.port
    except (TypeError, ValueError) as error:
        raise ValueError("endpoint must be an HTTP(S) URL without credentials, query, or fragment") from error
    return endpoint.rstrip("/")


def run_web(
    *,
    endpoint: str = "http://127.0.0.1:1234",
    port: int = 8788,
    no_browser: bool = False,
    refresh_interval: float = 2.0,
    gateway_enabled: bool = False,
    gateway_upstream: str | None = None,
    gateway_timing: bool = False,
) -> int:
    """Serve the authenticated overview on loopback. This does not open telemetry storage."""
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if refresh_interval <= 0:
        raise ValueError("refresh_interval must be greater than zero")
    if gateway_timing and not gateway_enabled:
        raise ValueError("--gateway-timing requires --gateway")
    safe_endpoint = validate_endpoint(endpoint)
    try:
        from web_ui_tools import create_server
    except ImportError as error:
        raise RuntimeError("Install llm-monitor[web] to use the browser dashboard.") from error

    login_code = secrets.token_urlsafe(24)
    service = InferenceMonitoringService(
        LMStudioClient(safe_endpoint),
        endpoint=safe_endpoint,
        refresh_interval_seconds=refresh_interval,
    )
    gateway = None
    event_hub = RequestEventHub()
    if gateway_enabled:
        timing_sink = None
        if gateway_timing:
            logging.basicConfig(level=logging.INFO, format="%(message)s")

            def timing_sink(record: dict[str, object]) -> None:
                logging.getLogger("llm_monitor.gateway.timing").info(
                    "gateway_timing %s", json.dumps(record, separators=(",", ":"))
                )
        gateway = OpenAIInferenceGateway(validate_gateway_upstream(gateway_upstream or safe_endpoint), service.store, event_hub, server_instance_id=service.server_instance_id, timing_sink=timing_sink)
    app = create_inference_web_app(service, login_code=login_code, gateway=gateway, event_hub=event_hub)
    server = create_server(app, host="127.0.0.1", port=port)
    url = f"http://127.0.0.1:{port}"
    print(f"LLM Monitor is listening at {url}")
    if gateway is not None:
        print(f"Opt-in inference gateway: {url}/v1/chat/completions -> {gateway.upstream}")
    print(f"Enter this local startup login code in the browser: {login_code}")
    if not no_browser:
        threading.Timer(0.75, webbrowser.open, args=(url,)).start()
    try:
        server.run()
    except KeyboardInterrupt:
        return 130
    return 0
