import json
from pathlib import Path

from llm_monitor.inference_models import CaptureCapabilities, InferenceRequest


def test_passive_capabilities_do_not_claim_request_or_reasoning_capture():
    capabilities = CaptureCapabilities.passive_inventory().to_dict()

    assert capabilities["model_inventory"]["state"] == "available"
    assert capabilities["request_lifecycle"]["state"] == "unavailable"
    assert capabilities["structured_input"]["state"] == "unavailable"
    assert capabilities["reasoning_text"]["state"] == "unavailable"
    assert capabilities["output_text"]["state"] == "unavailable"


def test_synthetic_request_fixture_preserves_typed_content_order():
    fixture_path = Path(__file__).parent / "fixtures" / "synthetic_request_v1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = InferenceRequest.from_dict(payload)

    assert [segment.kind for segment in request.content] == ["system", "user", "reasoning", "assistant"]
    assert request.input_tokens is None
    assert request.reasoning_tokens is None
    assert request.to_dict()["coverage"]["token_usage"] == "unavailable"
