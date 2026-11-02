from llm_monitor.inference_models import InferenceRequest
from llm_monitor.live_store import LiveInferenceStore


def test_live_store_bounds_request_count_and_marks_content_truncation():
    store = LiveInferenceStore(max_requests=1, max_content_bytes=12)
    first = InferenceRequest.from_dict({
        "request_id": "req-1", "server_instance_id": "srv-1", "source": "synthetic_fixture",
        "state": "completed", "content": [{"kind": "user", "text": "first"}],
    })
    second = InferenceRequest.from_dict({
        "request_id": "req-2", "server_instance_id": "srv-1", "source": "synthetic_fixture",
        "state": "completed", "content": [{"kind": "assistant", "text": "this is too long"}],
    })

    store.add_request(first)
    store.add_request(second)
    requests = store.requests()

    assert [item.request_id for item in requests] == ["req-2"]
    assert requests[0].content[0].truncated is True
    assert len(requests[0].content[0].text.encode("utf-8")) <= 12
