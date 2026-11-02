from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest

from llm_monitor.gateway import OpenAIInferenceGateway, RequestEventHub
from llm_monitor.inference_models import (
    InferenceRequest,
    ModelInventoryEntry,
)
from llm_monitor.live_store import LiveInferenceStore
from llm_monitor.providers import _normalize_v0_model, _normalize_v1_model


def test_model_inventory_entry_loaded_instance_ids_serialization():
    entry = ModelInventoryEntry(
        server_instance_id="server-1",
        provider_model_id="qwen38-27b-q4km",
        name="Qwen 2.5 27B Q4_K_M",
        state="loaded",
        model_instance_id="qwen38_23GB",
        loaded_instance_ids=("qwen38_23GB", "qwen38_alt"),
    )
    data = entry.to_dict()
    assert data["loaded_instance_ids"] == ("qwen38_23GB", "qwen38_alt")
    assert data["model_instance_id"] == "qwen38_23GB"

    reconstituted = ModelInventoryEntry.from_dict(data)
    assert reconstituted.loaded_instance_ids == ("qwen38_23GB", "qwen38_alt")
    assert reconstituted.model_instance_id == "qwen38_23GB"


def test_provider_v1_normalization_extracts_loaded_instance_ids():
    raw_v1 = {
        "id": "qwen38-27b-q4km",
        "display_name": "Qwen 2.5 27B Instruct",
        "format": "gguf",
        "loaded_instances": [
            {"id": "qwen38_23GB", "context_length": 32768},
            {"id": "qwen38_backup", "context_length": 8192},
        ],
    }
    normalized = _normalize_v1_model(raw_v1)
    assert normalized["state"] == "loaded"
    assert normalized["model_instance_id"] == "qwen38_23GB"
    assert normalized["loaded_instance_ids"] == ["qwen38_23GB", "qwen38_backup"]


def test_provider_v0_normalization_handles_loaded_instance():
    raw_v0 = {"id": "qwen38-27b-q4km", "state": "loaded"}
    normalized = _normalize_v0_model(raw_v0)
    assert normalized["state"] == "loaded"
    assert normalized["model_instance_id"] == "qwen38-27b-q4km"
    assert normalized["loaded_instance_ids"] == ["qwen38-27b-q4km"]


def test_inference_request_client_and_resolved_model_id_serialization():
    req = InferenceRequest(
        request_id="req-test-1",
        server_instance_id="server-1",
        source="gateway_openai_chat_completions",
        model_instance_id="qwen38_23GB",
        client_model_id="openai/qwen3.8_23GB",
        resolved_model_id="qwen38-27b-q4km",
        provider_model_id="qwen38_23GB",
        model_name="Qwen 2.5 27B Q4_K_M",
        state="active",
        started_at="2026-11-01T12:00:00Z",
    )
    data = req.to_dict()
    assert data["client_model_id"] == "openai/qwen3.8_23GB"
    assert data["resolved_model_id"] == "qwen38-27b-q4km"

    reconstituted = InferenceRequest.from_dict(data)
    assert reconstituted.client_model_id == "openai/qwen3.8_23GB"
    assert reconstituted.resolved_model_id == "qwen38-27b-q4km"


@pytest.mark.asyncio
async def test_gateway_dynamic_model_reconciliation():
    store = LiveInferenceStore(max_requests=10)
    events = RequestEventHub()

    server = {
        "id": "server-1",
        "name": "LM Studio Local",
        "endpoint": "http://127.0.0.1:1234",
        "connection_state": "connected",
    }
    model = ModelInventoryEntry(
        server_instance_id="server-1",
        provider_model_id="qwen38-27b-q4km",
        name="Qwen 2.5 27B Q4_K_M",
        state="loaded",
        model_instance_id="qwen38_23GB",
        loaded_instance_ids=("qwen38_23GB",),
    )
    store.replace_inventory(server, [model])

    gateway = OpenAIInferenceGateway(
        upstream="http://127.0.0.1:1234",
        store=store,
        events=events,
        server_instance_id="server-1",
    )

    initial_req = InferenceRequest(
        request_id="req-rec-1",
        server_instance_id="server-1",
        source="gateway_openai_chat_completions",
        model_instance_id="unknown-instance",
        client_model_id="openai/qwen3.8_23GB",
        resolved_model_id=None,
        provider_model_id="openai/qwen3.8_23GB",
        model_name="openai/qwen3.8_23GB",
        state="active",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    store.add_request(initial_req)

    received_events = []
    async def listener():
        async for ev in events.subscribe():
            received_events.append(ev)
            if ev.get("type") == "request.updated":
                break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.01)

    gateway._reconcile_model("req-rec-1", "qwen38_23GB")

    await asyncio.wait_for(task, timeout=1.0)

    updated = store.get_request("req-rec-1")
    assert updated is not None
    assert updated.resolved_model_id == "qwen38-27b-q4km"
    assert updated.model_name == "Qwen 2.5 27B Q4_K_M"
    assert updated.model_instance_id == "qwen38_23GB"

    update_ev = next(e for e in received_events if e["type"] == "request.updated")
    assert update_ev["payload"]["resolved_model_id"] == "qwen38-27b-q4km"
    assert update_ev["payload"]["model_name"] == "Qwen 2.5 27B Q4_K_M"
    assert update_ev["payload"]["model_instance_id"] == "qwen38_23GB"
