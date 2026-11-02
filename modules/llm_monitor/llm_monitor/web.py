"""Standalone local browser host lifecycle."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import inspect
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import urlsplit
import webbrowser

import psutil

from .gateway import OpenAIInferenceGateway, RequestEventHub, validate_gateway_upstream
from .inference_recording import InferenceRecorder
from .inference_service import InferenceMonitoringService
from .inference_web import create_inference_web_app
from .providers import LMStudioClient
from .server_lifecycle import (
    ServerDescriptor,
    bind_loopback_socket,
    descriptor_path,
    is_port_in_use,
    is_process_alive,
    mount_control_routes,
    read_descriptor,
    remove_descriptor,
    verify_running_instance,
    write_descriptor,
)
from .storage import TelemetryStore, default_database_path


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
    record_inferences: str | None = None,
    database: str | None = None,
    state_dir: Path | str | None = None,
) -> int:
    """Serve the authenticated overview on loopback. This does not open telemetry storage unless requested."""
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if refresh_interval <= 0:
        raise ValueError("refresh_interval must be greater than zero")
    if gateway_timing and not gateway_enabled:
        raise ValueError("--gateway-timing requires --gateway")
    if record_inferences and record_inferences not in {"metadata", "content"}:
        raise ValueError("record_inferences must be 'metadata' or 'content'")
    if record_inferences and not gateway_enabled:
        raise ValueError("--record-inferences requires --gateway")

    safe_endpoint = validate_endpoint(endpoint)
    try:
        from web_ui_tools import create_server
    except ImportError as error:
        raise RuntimeError("Install llm-monitor[web] to use the browser dashboard.") from error

    desc_path = descriptor_path(port, "127.0.0.1", state_dir=state_dir)
    url = f"http://127.0.0.1:{port}"

    # Step 1: Check if an instance is already registered for this host and port
    existing = read_descriptor(desc_path)
    if (
        existing is not None
        and is_process_alive(existing.pid, existing.process_create_time)
        and verify_running_instance(existing)
    ):
        print("LLM Monitor Web UI")
        print("Status: Already running")
        print(f"URL:    {url}")
        print(f"PID:    {existing.pid}\n")
        print("The existing server was left running.")
        return 0

    if existing is not None:
        remove_descriptor(desc_path)

    # Step 2: Check if the port is in use
    if is_port_in_use("127.0.0.1", port):
        deadline = time.time() + 1.5
        while time.time() < deadline:
            time.sleep(0.1)
            cand = read_descriptor(desc_path)
            if (
                cand is not None
                and is_process_alive(cand.pid, cand.process_create_time)
                and verify_running_instance(cand)
            ):
                print("LLM Monitor Web UI")
                print("Status: Already running")
                print(f"URL:    {url}")
                print(f"PID:    {cand.pid}\n")
                print("The existing server was left running.")
                return 0

        print(
            f"llm-monitor: web: Port {port} is already in use by an unmanaged service or unresponsive process.",
            file=sys.stderr,
        )
        return 1

    try:
        sock = bind_loopback_socket("127.0.0.1", port)
    except OSError as err:
        print(f"llm-monitor: web: Port {port} could not be bound exclusively: {err}", file=sys.stderr)
        return 1

    # Step 3: Initialize store, recorder, service, gateway, and app
    store = None
    recorder = None
    if record_inferences:
        db_path = database or str(default_database_path())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        store = TelemetryStore(db_path)
        recorder = InferenceRecorder(store, mode=record_inferences)
    elif database:
        store = TelemetryStore(database, readonly=True)

    login_code = secrets.token_urlsafe(24)
    control_token = secrets.token_urlsafe(32)
    instance_id = secrets.token_hex(16)
    my_pid = os.getpid()
    try:
        my_create_time = psutil.Process(my_pid).create_time()
    except Exception:
        my_create_time = None

    service = InferenceMonitoringService(
        LMStudioClient(safe_endpoint),
        endpoint=safe_endpoint,
        refresh_interval_seconds=refresh_interval,
        recorder=recorder,
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
        gateway = OpenAIInferenceGateway(
            validate_gateway_upstream(gateway_upstream or safe_endpoint),
            service.store,
            event_hub,
            server_instance_id=service.server_instance_id,
            timing_sink=timing_sink,
            recorder=recorder,
        )

    descriptor = ServerDescriptor(
        instance_id=instance_id,
        version=1,
        protocol="llm_monitor_web_v1",
        host="127.0.0.1",
        port=port,
        pid=my_pid,
        process_create_time=my_create_time,
        started_at=datetime.now(timezone.utc).isoformat(),
        control_token=control_token,
        gateway_enabled=gateway_enabled,
        recording_mode=record_inferences,
        database_path=str(store.path) if store is not None else None,
    )

    try:
        write_descriptor(desc_path, descriptor)
    except Exception as err:
        sock.close()
        print(f"llm-monitor: web: failed to write instance descriptor: {err}", file=sys.stderr)
        return 1

    try:
        app = create_inference_web_app(
            service,
            login_code=login_code,
            gateway=gateway,
            event_hub=event_hub,
            recorder=recorder,
            history_store=store,
        )
    except Exception as err:
        sock.close()
        remove_descriptor(desc_path, expected_instance_id=instance_id)
        print(f"llm-monitor: web: application initialization failed: {err}", file=sys.stderr)
        return 1

    shutdown_event = threading.Event()
    mount_control_routes(
        app,
        descriptor,
        shutdown_event,
        recorder=recorder,
        live_store=service.store,
    )

    try:
        server = create_server(app, host="127.0.0.1", port=port)
    except Exception as err:
        sock.close()
        remove_descriptor(desc_path, expected_instance_id=instance_id)
        print(f"llm-monitor: web: failed to create server: {err}", file=sys.stderr)
        return 1

    app.state.server = server

    print(f"LLM Monitor is listening at {url}")
    if gateway is not None:
        print(f"Opt-in inference gateway: {url}/v1/chat/completions -> {gateway.upstream}")
    if recorder is not None and store is not None:
        print(f"Inference recording enabled: {record_inferences} mode ({store.path})")
    print(f"Enter this local startup login code in the browser: {login_code}")
    print(f"PID: {my_pid}")

    if not no_browser:
        threading.Timer(0.75, webbrowser.open, args=(url,)).start()

    try:
        params = inspect.signature(server.run).parameters
        if "sockets" in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            server.run(sockets=[sock])
        else:
            sock.close()
            server.run()
    except KeyboardInterrupt:
        return 130
    finally:
        with contextlib.suppress(OSError):
            sock.close()
        remove_descriptor(desc_path, expected_instance_id=instance_id)

    return 0
