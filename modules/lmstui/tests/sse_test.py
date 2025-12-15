from lmstui.sse import SseEvent, extract_delta_text, iter_openai_stream_chunks, parse_sse_events


def test_parse_sse_events_basic():
    lines = iter(
        [
            "data: {\"a\": 1}",
            "",
            "data: [DONE]",
            "",
        ]
    )
    evs = list(parse_sse_events(lines))
    assert evs[0].data == "{\"a\": 1}"
    assert evs[1].data == "[DONE]"


def test_iter_openai_stream_chunks_stops_on_done():
    lines = iter(
        [
            "data: {\"choices\": [{\"delta\": {\"content\": \"hi\"}}]}",
            "",
            "data: [DONE]",
            "",
            "data: {\"choices\": [{\"delta\": {\"content\": \"NO\"}}]}",
            "",
        ]
    )
    chunks = list(iter_openai_stream_chunks(lines))
    assert len(chunks) == 1
    assert extract_delta_text(chunks[0]) == "hi"


def test_extract_delta_text_handles_missing():
    assert extract_delta_text({}) == ""
    assert extract_delta_text({"choices": []}) == ""
