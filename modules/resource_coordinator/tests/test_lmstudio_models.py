import httpx
import pytest

from resource_coordinator.adapters.lmstudio.models import NativeModelController


@pytest.mark.asyncio
async def test_model_controller_snapshots_unloads_and_restores_loaded_instances():
    loaded = [{"type": "llm", "key": "publisher/model", "loaded_instances": [
        {"id": "model-instance", "config": {"context_length": 8192, "flash_attention": True}}
    ]}]
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path, request.content))
        if request.method == "GET":
            return httpx.Response(200, json={"models": loaded})
        body = __import__("json").loads(request.content or b"{}")
        if request.url.path.endswith("/unload"):
            loaded[0]["loaded_instances"] = []
            return httpx.Response(200, json={"instance_id": body["instance_id"]})
        loaded[0]["loaded_instances"] = [{"id": "restored-instance", "config": body}]
        return httpx.Response(200, json={"status": "loaded", "instance_id": "restored-instance"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://lmstudio") as client:
        controller = NativeModelController(client)
        snapshot = await controller.unload_all()
        assert snapshot == [{"model": "publisher/model", "type": "llm", "config": {
            "context_length": 8192, "flash_attention": True,
        }}]
        assert loaded[0]["loaded_instances"] == []
        await controller.restore(snapshot)
        assert loaded[0]["loaded_instances"][0]["config"]["context_length"] == 8192
    assert [call[1] for call in calls].count("/api/v1/models/unload") == 1
    assert [call[1] for call in calls].count("/api/v1/models/load") == 1
