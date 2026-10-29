from llm_monitor.providers import LMStudioClient, extract_opencode_model_limits, extract_opencode_model_configuration
from llm_monitor.opencode import ApiResult


def test_opencode_limits_are_selected_by_exact_model_and_provider_identity():
    payload = {"providers": [
        {"id": "lmstudio", "models": {"model-a": {"limit": {"context": 65536, "output": 8192}}}},
        {"id": "other", "models": {"model-a": {"limit": {"context": 4096, "output": 512}}}},
    ]}

    result = extract_opencode_model_limits(payload, "model-a", provider_id="lmstudio")

    assert result == {"provider_id": "lmstudio", "model_id": "model-a", "context": 65536,
                      "output": 8192, "source": "opencode_config_providers"}


def test_opencode_model_configuration_is_exact_and_excludes_credentials():
    payload = {"providers": [{"id": "lmstudio", "models": {"qwen": {
        "limit": {"context": 32768, "output": 8192}, "options": {"reasoning_effort": "medium",
            "apiKey": "private-value"}, "variants": {}}}}]}

    result = extract_opencode_model_configuration(payload, "qwen", provider_id="lmstudio")

    assert result == {"provider_id": "lmstudio", "model_id": "qwen", "limit": {"context": 32768, "output": 8192},
                      "options": {"reasoning_effort": "medium"}, "variants": {}}
    assert extract_opencode_model_configuration(payload, "qwen", provider_id="other") is None


def test_lmstudio_v1_loaded_context_is_separate_from_model_maximum(monkeypatch):
    client = LMStudioClient("http://lmstudio")
    monkeypatch.setattr(client, "get_json", lambda path: ApiResult(data={"models": [{
        "key": "model-a", "max_context_length": 131072, "reasoning_choices": ["off", "on"],
        "loaded_instances": [
            {"id": "instance-1", "config": {"context_length": 65536}},
        ],
    }]}) if path.endswith("/api/v1/models") else ApiResult(error="HTTP 404", status_code=404))

    models = client.list_models()

    assert models[0]["id"] == "model-a"
    assert models[0]["state"] == "loaded"
    assert models[0]["context_length"] == 65536
    assert models[0]["max_context_length"] == 131072
    assert models[0]["reasoning_capabilities"] == ["off", "on"]


def test_lmstudio_v0_maximum_does_not_claim_loaded_context(monkeypatch):
    client = LMStudioClient("http://lmstudio")
    monkeypatch.setattr(client, "get_json", lambda path: ApiResult(error="HTTP 404", status_code=404)
                        if path.endswith("/api/v1/models") else ApiResult(data={"data": [{
                            "id": "model-a", "state": "loaded", "max_context_length": 32768,
                        }]}))

    models = client.list_models()

    assert models[0]["context_length"] is None
    assert models[0]["max_context_length"] == 32768
    assert models[0]["context_source"] == "model_maximum_only"
