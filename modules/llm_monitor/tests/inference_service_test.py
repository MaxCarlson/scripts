from llm_monitor.inference_service import InferenceMonitoringService


class FakeLMStudioClient:
    def __init__(self, models=None, error=None):
        self.models = models or []
        self.error = error
        self.calls = 0

    def list_models(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.models


def test_inventory_refresh_is_cached_and_does_not_claim_request_capture():
    client = FakeLMStudioClient([{
        "id": "example/model-q4", "state": "loaded", "loaded_instance_count": 2,
        "loaded_context_lengths": [4096, 8192], "context_length": None,
        "max_context_length": 32768, "api_version": "v1",
    }])
    service = InferenceMonitoringService(client, endpoint="http://127.0.0.1:1234")

    refreshed = service.refresh()
    snapshot = service.snapshot()

    assert client.calls == 1
    assert refreshed["server"]["connection_state"] == "connected"
    assert refreshed["models"][0]["loaded_instance_count"] == 2
    assert refreshed["models"][0]["context_length"] is None
    assert refreshed["capabilities"]["reasoning_text"]["state"] == "unavailable"
    assert snapshot["requests"] == []


def test_inventory_failure_is_unavailable_and_does_not_expose_error_text():
    client = FakeLMStudioClient(error=RuntimeError("secret endpoint token"))
    service = InferenceMonitoringService(client, endpoint="http://127.0.0.1:1234")

    snapshot = service.refresh()

    assert snapshot["server"]["connection_state"] == "unavailable"
    assert snapshot["server"]["error_code"] == "RuntimeError"
    assert "secret" not in str(snapshot)
    assert snapshot["models"] == []
