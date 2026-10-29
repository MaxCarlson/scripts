from __future__ import annotations

from io import BytesIO
import json
from urllib.error import HTTPError, URLError

from llm_monitor.live import (
    LiveSessionState,
    OpenCodeSSEClient,
    build_reasoning_provenance,
    correlate_request_evidence,
    diagnose_live_attempt,
    iter_sse_events,
    normalize_opencode_event,
    observe_session,
    SSEEvent,
)


def test_sse_parser_handles_multiple_frames_comments_and_multiline_data():
    stream = BytesIO(
        b": heartbeat\n"
        b"event: message.part.delta\n"
        b"id: 7\n"
        b"data: {\"type\":\n"
        b"data: \"message.part.delta\"}\n\n"
        b"data: second\n\n"
    )

    events = list(iter_sse_events(stream))

    assert [(event.event, event.event_id, event.data) for event in events] == [
        ("message.part.delta", "7", '{"type":\n"message.part.delta"}'),
        (None, None, "second"),
    ]


def test_sse_parser_discards_oversized_frame_and_keeps_following_frame():
    events = list(iter_sse_events(BytesIO(b"data: 123456789\n\ndata: ok\n\n"), max_event_bytes=10))

    assert [(event.error, event.data) for event in events] == [("oversized_event", ""), (None, "ok")]


def test_sse_transport_sends_exact_project_scope_and_optional_basic_auth(monkeypatch):
    import base64
    import llm_monitor.live as live_module

    seen = {}

    def fail_auth(request, timeout):
        seen["request"] = request
        raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(live_module, "urlopen", fail_auth)
    stream = OpenCodeSSEClient("http://127.0.0.1:4096", r"C:\pilot", username="opencode", password="secret")

    frames = list(stream.events(0.5))

    request = seen["request"]
    assert "directory=C%3A%5Cpilot" in request.full_url
    assert request.get_header("Authorization") == "Basic " + base64.b64encode(b"opencode:secret").decode()
    assert all("secret" not in str(frame) for frame in frames)


def test_sse_transport_bounds_retries_and_marks_connection_gaps(monkeypatch):
    import llm_monitor.live as live_module

    def disconnected(_request, timeout):
        raise URLError("connection reset")

    monkeypatch.setattr(live_module, "urlopen", disconnected)
    stream = OpenCodeSSEClient("http://127.0.0.1:4096", r"C:\pilot", timeout=0.1, max_reconnects=1)

    frames = list(stream.events(0.5))

    assert [frame.error for frame in frames] == ["connection_failed", "connection_failed", "stream_unavailable"]
    assert stream.reconnection_gaps == 2


def test_sse_reconciliation_discards_other_sessions_and_marks_malformed_delivery_incomplete():
    from llm_monitor.live import SSEEvent, observe_session

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def poll(self, _session, _directory):
            self.calls += 1
            return {"session_id": "ses-1", "session_state": {"type": "idle"},
                    "last_assistant_id": "msg-1", "last_assistant_created": "2026-10-29T12:00:00Z",
                    "last_assistant_finish": "length", "last_assistant_is_complete": True,
                    "last_assistant_tokens": {"reasoning": 8192, "output": 0},
                    "session_info": {"model": "qwen38_23GB", "variant": "medium"},
                    "history_coverage": {"status": "complete"}}

        def events_for_session(self, _session):
            return []

        def get_json(self, _path, _directory):
            from llm_monitor.opencode import ApiResult

            return ApiResult(data={"providers": [{"id": "lmstudio", "models": {
                "qwen38_23GB": {"limit": {"output": 8192}, "variants": {}}}}]})

    class FakeStream:
        connected = True
        reconnection_gaps = 0
        server_origin = "http://127.0.0.1:4096"

        def events(self, _seconds):
            yield SSEEvent(event="__connected__")
            yield SSEEvent(data="not json")
            yield SSEEvent(data=json.dumps({"type": "message.part.delta", "properties": {
                "sessionID": "ses-other", "messageID": "msg-other", "partID": "prt-other",
                "field": "reasoning", "delta": "must-not-leak"}}))

    snapshot = observe_session(FakeClient(), FakeStream(), session_id="ses-1", project_directory=r"C:\pilot",
                               observe_seconds=1)

    assert snapshot["stream_capability"] == "completion_only"
    assert snapshot["stream_connection"] == "connected"
    assert snapshot["sse_frames_received"] == 2
    assert snapshot["matching_session_events"] == 0
    assert snapshot["filtered_events"] == 1
    assert snapshot["malformed_events"] == 1
    assert snapshot["reasoning_configuration"]["session_recorded_variant"]["value"] == "medium"
    assert snapshot["reasoning_configuration"]["output_limits"]["value"] == {"output": 8192}
    assert "telemetry_incomplete" in snapshot["warnings"]
    assert "must-not-leak" not in json.dumps(snapshot)


def test_installed_opencode_global_event_shape_joins_part_update_by_schema_ids():
    raw = {"directory": r"C:\pilot", "payload": {"id": "evt_1", "type": "message.part.updated",
        "properties": {"sessionID": "ses-1", "time": 1000, "part": {
            "id": "prt-1", "sessionID": "ses-1", "messageID": "msg-1", "type": "reasoning",
            "text": "thought", "time": {"start": 1000}}}}}

    event = normalize_opencode_event(raw, project_directory=r"C:\pilot", session_id="ses-1", raw_event_id="evt_1")
    state = LiveSessionState("ses-1", r"C:\pilot", include_reasoning=True)
    state.ingest(event, now=1.0)

    assert (event.message_id, event.part_id, event.part_type) == ("msg-1", "prt-1", "reasoning")
    assert state.snapshot(now=1.0)["current_reasoning_text"] == "thought"


def test_session_status_schema_object_preserves_busy_activity():
    event = normalize_opencode_event({"directory": r"C:\pilot", "payload": {
        "id": "evt_status", "type": "session.status", "properties": {
            "sessionID": "ses-1", "status": {"type": "busy"}}}},
        project_directory=r"C:\pilot", session_id="ses-1")
    state = LiveSessionState("ses-1", r"C:\pilot")

    state.ingest(event, now=1.0)

    assert state.snapshot(now=1.0)["activity"] == "working"


def test_normalizer_unwraps_global_envelope_and_enforces_project_and_session_scope():
    raw = {
        "directory": r"C:\pilot",
        "payload": {
            "type": "message.part.delta",
            "properties": {"sessionID": "ses-1", "messageID": "msg-1", "partID": "prt-1",
                           "field": "reasoning", "delta": "think"},
        },
    }

    event = normalize_opencode_event(raw, project_directory=r"C:\pilot", session_id="ses-1")

    assert event is not None
    assert (event.event_type, event.session_id, event.message_id, event.part_id, event.field) == (
        "message.part.delta", "ses-1", "msg-1", "prt-1", "reasoning"
    )
    assert normalize_opencode_event(raw, project_directory=r"C:\other", session_id="ses-1") is None
    assert normalize_opencode_event(raw, project_directory=r"C:\pilot", session_id="ses-2") is None


def test_delta_before_update_is_retained_and_duplicate_full_updates_do_not_duplicate_text():
    state = LiveSessionState("ses-1", r"C:\pilot", include_reasoning=True)
    delta = {"type": "message.part.delta", "properties": {"sessionID": "ses-1", "messageID": "msg-1",
             "partID": "prt-1", "field": "reasoning", "delta": " more"}}
    update = {"type": "message.part.updated", "properties": {"sessionID": "ses-1", "messageID": "msg-1",
              "part": {"id": "prt-1", "type": "reasoning", "text": "start"}}}

    state.ingest(normalize_opencode_event(delta, project_directory=r"C:\pilot", session_id="ses-1"), now=1.0)
    state.ingest(normalize_opencode_event(update, project_directory=r"C:\pilot", session_id="ses-1"), now=2.0)
    state.ingest(normalize_opencode_event(update, project_directory=r"C:\pilot", session_id="ses-1"), now=3.0)

    assert state.snapshot(now=3.0)["current_reasoning_text"] == "start more"
    assert state.snapshot(now=3.0)["activity"] == "reasoning"


def test_snapshot_reports_bounded_metadata_timeline_and_duplicate_delivery_without_reasoning_text():
    payload = {"id": "evt-duplicate", "type": "message.part.delta", "properties": {
        "sessionID": "ses-timeline", "messageID": "msg-timeline", "partID": "prt-thought",
        "field": "reasoning", "delta": "private reasoning sentinel"}}

    class Client:
        def poll(self, _session_id, _project_directory):
            return {"session_id": "ses-timeline", "session_state": {"type": "busy"},
                    "history_coverage": {"status": "unavailable"}}

    class Stream:
        connected = True
        reconnection_gaps = 0
        server_origin = "http://127.0.0.1:4096"

        def events(self, _observe_seconds):
            yield SSEEvent(event="__connected__")
            frame = SSEEvent(data=json.dumps(payload))
            yield frame
            yield frame

    snapshot = observe_session(
        Client(), Stream(), session_id="ses-timeline", project_directory=r"C:\pilot",
        observe_seconds=1,
    )

    assert snapshot["duplicate_events"] == 1
    assert snapshot["reasoning_delta_events"] == 1
    assert snapshot["reasoning_parts_observed"] == 1
    assert snapshot["first_reasoning_delta_at"]
    assert snapshot["last_reasoning_delta_at"]
    assert snapshot["observer_started_at"]
    assert snapshot["stream_connected_at"]
    assert snapshot["connection_attempts"] == 1
    assert snapshot["connection_timeline"][0]["state"] == "connected"
    assert len(snapshot["event_timeline"]) == 2
    assert [item["duplicate"] for item in snapshot["event_timeline"]] == [False, True]
    assert "current_reasoning_text" not in snapshot
    assert "private reasoning sentinel" not in json.dumps(snapshot)


def test_event_timeline_is_bounded_and_reports_truncation():
    state = LiveSessionState("ses-timeline", r"C:\pilot")
    for index in range(300):
        event = normalize_opencode_event(
            {"id": f"evt-{index}", "type": "session.status", "properties": {
                "sessionID": "ses-timeline", "status": {"type": "busy"}}},
            project_directory=r"C:\pilot", session_id="ses-timeline", raw_event_id=f"evt-{index}",
        )
        state.ingest(event, now=float(index))

    snapshot = state.snapshot(now=300.0)

    assert len(snapshot["event_timeline"]) == 256
    assert snapshot["event_timeline_truncated"] is True
    assert snapshot["event_timeline"][0]["event_id"] == "evt-44"


def test_reconnection_preserves_partial_reasoning_and_marks_timeline_gap():
    first = {"id": "evt-before-gap", "type": "message.part.delta", "properties": {
        "sessionID": "ses-gap", "messageID": "msg-gap", "partID": "prt-gap",
        "field": "reasoning", "delta": "first"}}
    second = {"id": "evt-after-gap", "type": "message.part.delta", "properties": {
        "sessionID": "ses-gap", "messageID": "msg-gap", "partID": "prt-gap",
        "field": "reasoning", "delta": " second"}}

    class Client:
        def poll(self, _session_id, _project_directory):
            return {"session_id": "ses-gap", "session_state": {"type": "busy"},
                    "history_coverage": {"status": "unavailable"}}

    class Stream:
        connected = True
        connection_attempts = 2
        reconnection_gaps = 1
        server_origin = "http://127.0.0.1:4096"

        def events(self, _observe_seconds):
            yield SSEEvent(event="__connected__")
            yield SSEEvent(data=json.dumps(first))
            yield SSEEvent(error="connection_failed")
            yield SSEEvent(event="__connected__")
            yield SSEEvent(data=json.dumps(second))

    updates = []
    snapshot = observe_session(
        Client(), Stream(), session_id="ses-gap", project_directory=r"C:\pilot",
        observe_seconds=5, include_reasoning=True, trial_id="trial-gap", on_update=updates.append,
    )

    assert snapshot["trial_id"] == "trial-gap"
    assert updates and all(update["trial_id"] == "trial-gap" for update in updates)
    assert snapshot["current_reasoning_text"] == "first second"
    assert snapshot["reasoning_delta_events"] == 2
    assert snapshot["connection_attempts"] == 2
    assert snapshot["reconnection_attempts"] == 1
    assert snapshot["reconnection_gaps"] == 1
    assert [item["state"] for item in snapshot["connection_timeline"]] == [
        "connected", "interrupted", "reconnected",
    ]
    assert snapshot["coverage"] == "incomplete"


def test_snapshot_keeps_live_token_count_unknown_and_reports_completion_metadata():
    state = LiveSessionState("ses-1", r"C:\pilot")
    completion = {"type": "message.updated", "properties": {"sessionID": "ses-1", "info": {
        "id": "msg-1", "role": "assistant", "finish": "length", "tokens": {"reasoning": 8192}}}}

    state.ingest(normalize_opencode_event(completion, project_directory=r"C:\pilot", session_id="ses-1"), now=10.0)
    snapshot = state.snapshot(now=11.0)

    assert snapshot["current_reasoning_tokens"] is None
    assert snapshot["last_completed_reasoning_tokens"] == 8192
    assert snapshot["last_completed_finish_reason"] == "length"
    assert snapshot["stream_capability"] == "completion_only"
    assert "length_finish" in snapshot["warnings"]


def test_tool_activity_and_length_finish_without_file_writes_are_observed():
    state = LiveSessionState("ses-1", r"C:\pilot")
    tool = {"type": "message.part.updated", "properties": {"sessionID": "ses-1", "messageID": "msg-1",
             "part": {"id": "prt-read", "type": "tool", "tool": "read", "state": {"status": "completed"}}}}
    for index in range(3):
        state.ingest(normalize_opencode_event(tool, project_directory=r"C:\pilot", session_id="ses-1"), now=10 + index)

    snapshot = state.snapshot(now=13.0)

    assert snapshot["last_tool"] == "read"
    assert snapshot["tool_calls"] == 1
    assert snapshot["file_writes_observed"] == 0


def test_malformed_and_oversized_json_events_are_reported_without_exposing_payload():
    state = LiveSessionState("ses-1", r"C:\pilot")
    state.note_telemetry_error("malformed_event")
    state.note_telemetry_error("oversized_event")

    snapshot = state.snapshot(now=1.0)

    assert "telemetry_incomplete" in snapshot["warnings"]
    assert "credential-shaped-private-value" not in json.dumps(snapshot)


def test_part_updated_full_snapshots_are_streaming_only_when_content_advances():
    state = LiveSessionState("ses-1", r"C:\pilot")

    def update(text):
        return normalize_opencode_event({"type": "message.part.updated", "properties": {
            "sessionID": "ses-1", "messageID": "msg-1", "part": {
                "id": "prt-1", "type": "reasoning", "text": text, "state": {"status": "running"}}}},
            project_directory=r"C:\pilot", session_id="ses-1")

    state.ingest(update("thought"), now=1.0)
    assert state.snapshot(now=1.0)["stream_capability"] == "completion_only"
    state.ingest(update("thought continues"), now=2.0)
    state.ingest(update("thought continues"), now=3.0)

    assert state.snapshot(now=3.0)["stream_capability"] == "streaming"
    assert state.snapshot(now=3.0)["activity"] == "reasoning"


def test_healthy_busy_session_without_content_is_activity_only_and_incomplete():
    state = LiveSessionState("ses-1", r"C:\pilot")
    state.mark_connected()
    state.reconcile({"session_state": {"type": "busy"}}, now=1.0)

    snapshot = state.snapshot(now=31.0)

    assert snapshot["stream_capability"] == "activity_only"
    assert snapshot["current_reasoning_tokens"] is None
    assert {"telemetry_incomplete", "no_recent_events"}.issubset(snapshot["warnings"])
    assert "possible_stall" not in snapshot["warnings"]


def test_diagnostics_report_discovery_repetition_and_missing_successful_edits():
    state = LiveSessionState("ses-1", r"C:\pilot")
    for index, name in enumerate(("read", "read", "grep", "read", "read", "read")):
        event = normalize_opencode_event({"type": "message.part.updated", "properties": {
            "sessionID": "ses-1", "messageID": "msg-1", "part": {
                "id": f"prt-{index}", "type": "tool", "tool": name,
                "state": {"status": "completed"}}}}, project_directory=r"C:\pilot", session_id="ses-1")
        state.ingest(event, now=float(index + 1))
    state.last_completed_finish_reason = "length"
    state.has_completed_content = True
    state.reconcile({"history_coverage": {"status": "complete"}}, now=9.0)

    codes = {item["code"] for item in diagnose_live_attempt(state.snapshot(now=9.0), tool_names=[
        "read", "read", "grep", "read", "read", "read"], history_coverage="complete")}

    assert {"long_source_discovery", "repeated_tool_calls", "no_successful_file_edits", "length_finish"} <= codes


def test_tool_state_transition_counts_a_successful_file_write_once():
    state = LiveSessionState("ses-1", r"C:\pilot")
    for status in ("running", "completed"):
        event = normalize_opencode_event({"type": "message.part.updated", "properties": {
            "sessionID": "ses-1", "messageID": "msg-1", "part": {
                "id": "prt-write", "type": "tool", "tool": "edit", "state": {"status": status}}}},
            project_directory=r"C:\pilot", session_id="ses-1")
        state.ingest(event, now=1.0 if status == "running" else 2.0)

    snapshot = state.snapshot(now=2.0)
    assert snapshot["file_writes_observed"] == 1
    assert snapshot["successful_file_edits"] == 1
    assert snapshot["tool_calls"] == 1


def test_history_reconciliation_populates_last_tool_and_call_count():
    from llm_monitor.events import NormalizedEvent

    state = LiveSessionState("ses-1", r"C:\pilot")
    events = [NormalizedEvent(event_id="tool-1", timestamp=None, observed_at=None, source="test", category="tool",
        subtype="invocation", session_id="ses-1", tool_name="read", outcome="succeeded", provider_id="msg-1",
        part_id="prt-1")]

    state.reconcile_history(events, "complete")

    assert state.snapshot(now=1.0)["last_tool"] == "read"
    assert state.snapshot(now=1.0)["tool_calls"] == 1


def test_text_delta_sets_ordinary_output_activity():
    state = LiveSessionState("ses-1", r"C:\pilot")
    update = normalize_opencode_event({"type": "message.part.updated", "properties": {
        "sessionID": "ses-1", "part": {"id": "prt-1", "sessionID": "ses-1", "messageID": "msg-1",
            "type": "text", "text": ""}}}, project_directory=r"C:\pilot", session_id="ses-1")
    event = normalize_opencode_event({"type": "message.part.delta", "properties": {
        "sessionID": "ses-1", "messageID": "msg-1", "partID": "prt-1", "field": "text", "delta": "answer"}},
        project_directory=r"C:\pilot", session_id="ses-1")

    state.ingest(update, now=0.5)
    state.ingest(event, now=1.0)

    assert state.snapshot(now=1.0)["activity"] == "output"
    assert state.snapshot(now=1.0)["streamed_text_characters"] == 6


def test_text_field_delta_waits_for_associated_reasoning_part_type():
    state = LiveSessionState("ses-1", r"C:\pilot")
    delta = normalize_opencode_event({"type": "message.part.delta", "properties": {
        "sessionID": "ses-1", "messageID": "msg-1", "partID": "prt-1", "field": "text", "delta": "think"}},
        project_directory=r"C:\pilot", session_id="ses-1")
    update = normalize_opencode_event({"type": "message.part.updated", "properties": {
        "sessionID": "ses-1", "part": {"id": "prt-1", "sessionID": "ses-1", "messageID": "msg-1",
            "type": "reasoning", "text": "think", "state": {"status": "running"}}}},
        project_directory=r"C:\pilot", session_id="ses-1")

    state.ingest(delta, now=1.0)
    state.ingest(update, now=2.0)
    snapshot = state.snapshot(now=2.0)

    assert snapshot["activity"] == "reasoning"
    assert snapshot["streamed_reasoning_characters"] == 5
    assert snapshot["streamed_text_characters"] == 0


def test_explicit_reasoning_snapshot_is_bounded_across_parts():
    state = LiveSessionState("ses-1", r"C:\pilot", include_reasoning=True)
    for index in range(5):
        event = normalize_opencode_event({"type": "message.part.updated", "properties": {
            "sessionID": "ses-1", "part": {"id": f"prt-{index}", "sessionID": "ses-1",
                "messageID": "msg-1", "type": "reasoning", "text": "x" * 4096,
                "state": {"status": "running"}}}}, project_directory=r"C:\pilot", session_id="ses-1")
        state.ingest(event, now=float(index))

    text = state.snapshot(now=5.0)["current_reasoning_text"]
    assert len(text) <= 16 * 1024


def test_reasoning_provenance_does_not_infer_outbound_parameters_from_session_variant():
    provenance = build_reasoning_provenance({"session_id": "ses-1", "session_info": {
        "variant": "medium", "model": "qwen38_23GB"}})

    assert provenance["session_recorded_variant"] == {
        "value": "medium", "source": "opencode_session", "verification_status": "reported"}
    assert provenance["requested_variant"]["verification_status"] == "unavailable"
    assert provenance["observed_outbound_provider_parameters"]["value"] is None
    assert provenance["observed_outbound_provider_parameters"]["verification_status"] == "unavailable"


def test_request_evidence_requires_exact_session_message_and_timestamp_and_allowlists_parameters():
    summary = {"session_id": "ses-1", "last_assistant_id": "msg-1",
               "last_assistant_created": "2026-10-29T12:00:00Z"}
    evidence = {"schema_version": 1, "records": [{
        "session_id": "ses-1", "message_id": "msg-1", "message_created_at": "2026-10-29T12:00:00+00:00",
        "request_observed_at": "2026-10-29T12:00:01Z", "provider": "lmstudio", "model": "qwen38_23GB",
        "parameters": {"reasoning_effort": "medium", "max_tokens": 8192, "api_key": "must-not-leak"}}]}

    correlated = correlate_request_evidence(evidence, summary)

    assert correlated["verification_status"] == "verified"
    assert correlated["value"] == {"provider": "lmstudio", "model": "qwen38_23GB",
                                   "parameters": {"reasoning_effort": "medium", "max_tokens": 8192}}
    evidence["records"][0]["message_id"] = "msg-other"
    assert correlate_request_evidence(evidence, summary)["verification_status"] == "unavailable"


def test_reasoning_exhaustion_fixtures_report_8k_and_16k_without_claiming_request_parameters():
    from pathlib import Path

    fixture_directory = Path(__file__).parent / "fixtures"
    for filename, limit in (("reasoning_exhaustion_8k.json", 8192), ("reasoning_exhaustion_16k.json", 16384)):
        fixture = json.loads((fixture_directory / filename).read_text(encoding="utf-8"))
        limit = fixture["snapshot"]["output_limits"]["output"]
        provenance = build_reasoning_provenance(fixture["session"], model_configuration={
            "limit": {"output": limit}, "options": {}, "variants": {}}, lmstudio_model={
                "id": "qwen38_23GB", "state": "loaded",
                "reasoning_capabilities": fixture["expected_reasoning_capabilities"]})
        fixture["snapshot"]["reasoning_configuration"] = provenance
        diagnostic_codes = {item["code"] for item in diagnose_live_attempt(
            fixture["snapshot"], tool_names=fixture["tool_names"], history_coverage="complete")}
        assert fixture["snapshot"]["last_completed_reasoning_tokens"] == limit
        assert fixture["snapshot"]["last_completed_finish_reason"] == "length"
        assert "reasoning_exhausted_allowance" in diagnostic_codes
        assert "no_successful_file_edits" in diagnostic_codes
        assert provenance["observed_outbound_provider_parameters"]["verification_status"] == "unavailable"
        assert provenance["lm_studio_reasoning_capabilities"]["value"] == ["off", "on"]
        assert provenance["lm_studio_reasoning_capabilities"]["verification_status"] == "reported"
        assert provenance["session_recorded_variant"]["value"] == "medium"
        assert provenance["requested_variant"]["verification_status"] == "unavailable"


def test_request_evidence_loader_rejects_oversized_files_without_echoing_content(tmp_path):
    from llm_monitor.live import load_request_evidence

    evidence = tmp_path / "request.json"
    evidence.write_bytes(b"x" * (128 * 1024 + 1))

    try:
        load_request_evidence(evidence)
    except ValueError as exc:
        assert "128 KiB" in str(exc)
    else:
        raise AssertionError("oversized request evidence must be rejected")


class _FakeSSEServer:
    def __init__(self, handler_callback):
        import socket
        import threading

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.sock.listen(5)
        self.stop_event = threading.Event()
        self.client_closed = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(handler_callback,))
        self.thread.daemon = True
        self.thread.start()

    def _run(self, handler_callback):
        import socket

        self.sock.settimeout(0.5)
        while not self.stop_event.is_set():
            try:
                conn, _ = self.sock.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                break
            try:
                conn.recv(2048)
                handler_callback(conn, self.stop_event, self.client_closed)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def close(self):
        self.stop_event.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.thread.join(timeout=1.0)


def test_idle_connected_sse_stream_respects_observe_seconds_deadline_and_closes():
    import socket
    import time
    from llm_monitor.live import OpenCodeSSEClient, observe_session

    def idle_handler(conn, stop_event, client_closed):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
        conn.settimeout(0.05)
        while not stop_event.is_set():
            try:
                data = conn.recv(1024)
                if not data:
                    client_closed.set()
                    break
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                client_closed.set()
                break

    server = _FakeSSEServer(idle_handler)
    try:
        class FakeClient:
            def poll(self, _session, _directory):
                return {"session_id": "ses-idle", "session_state": {"type": "busy"}}

        stream = OpenCodeSSEClient(server.url, r"C:\project", timeout=5.0)
        t0 = time.monotonic()
        snapshot = observe_session(FakeClient(), stream, session_id="ses-idle", project_directory=r"C:\project",
                                   observe_seconds=0.4)
        elapsed = time.monotonic() - t0

        assert 0.35 <= elapsed <= 0.7, f"Elapsed {elapsed:.3f}s was not bounded near 0.4s"
        assert server.client_closed.wait(timeout=1.0), "Client did not close the connection upon deadline expiration"
        assert snapshot["stream_connection"] == "connected"
        assert snapshot["observation_deadline_limited"] is True
        assert "observation_deadline_limited" in snapshot["warnings"]
        assert snapshot["coverage"] == "incomplete"
        assert snapshot["matching_session_events"] == 0
        assert snapshot["reconnection_gaps"] == 0
    finally:
        server.close()


def test_sse_stream_with_periodic_comments_respects_observe_seconds_deadline():
    import socket
    import time
    from llm_monitor.live import OpenCodeSSEClient, observe_session

    def comment_handler(conn, stop_event, client_closed):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
        conn.settimeout(0.05)
        while not stop_event.is_set():
            try:
                data = conn.recv(1024)
                if not data:
                    client_closed.set()
                    break
            except (TimeoutError, socket.timeout):
                pass
            except OSError:
                client_closed.set()
                break
            try:
                conn.sendall(b": keep-alive\n\n")
            except OSError:
                client_closed.set()
                break
            time.sleep(0.08)

    server = _FakeSSEServer(comment_handler)
    try:
        class FakeClient:
            def poll(self, _session, _directory):
                return {"session_id": "ses-comments", "session_state": {"type": "busy"}}

        stream = OpenCodeSSEClient(server.url, r"C:\project", timeout=5.0)
        t0 = time.monotonic()
        snapshot = observe_session(FakeClient(), stream, session_id="ses-comments", project_directory=r"C:\project",
                                   observe_seconds=0.4)
        elapsed = time.monotonic() - t0

        assert 0.35 <= elapsed <= 0.75, f"Elapsed {elapsed:.3f}s was not bounded near 0.4s"
        assert server.client_closed.wait(timeout=1.0), "Client did not close the connection upon deadline expiration"
        assert snapshot["observation_deadline_limited"] is True
        assert "observation_deadline_limited" in snapshot["warnings"]
        assert snapshot["coverage"] == "incomplete"
        assert snapshot["reconnection_gaps"] == 0
    finally:
        server.close()


def test_sse_stream_with_intermittent_events_respects_deadline_and_preserves_partials():
    import json
    import socket
    import time
    from llm_monitor.live import OpenCodeSSEClient, observe_session

    def delta_handler(conn, stop_event, client_closed):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
        # Send 2 delta events with slight delays, then stay idle
        events = [
            {"id": "evt-1", "type": "message.part.delta", "properties": {
                "sessionID": "ses-deltas", "messageID": "msg-1", "partID": "prt-1",
                "field": "reasoning", "delta": "step 1 "}},
            {"id": "evt-2", "type": "message.part.delta", "properties": {
                "sessionID": "ses-deltas", "messageID": "msg-1", "partID": "prt-1",
                "field": "reasoning", "delta": "step 2"}},
        ]
        time.sleep(0.1)
        for evt in events:
            payload = f"id: {evt['id']}\nevent: message.part.delta\ndata: {json.dumps(evt)}\n\n".encode("utf-8")
            try:
                conn.sendall(payload)
            except OSError:
                client_closed.set()
                return
            time.sleep(0.1)
        # Now stay idle until client closes
        conn.settimeout(0.05)
        while not stop_event.is_set():
            try:
                data = conn.recv(1024)
                if not data:
                    client_closed.set()
                    break
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                client_closed.set()
                break

    server = _FakeSSEServer(delta_handler)
    try:
        class FakeClient:
            def poll(self, _session, _directory):
                return {"session_id": "ses-deltas", "session_state": {"type": "busy"}}

        stream = OpenCodeSSEClient(server.url, r"C:\project", timeout=5.0)
        t0 = time.monotonic()
        snapshot = observe_session(FakeClient(), stream, session_id="ses-deltas", project_directory=r"C:\project",
                                   observe_seconds=0.5, include_reasoning=True)
        elapsed = time.monotonic() - t0

        assert 0.45 <= elapsed <= 0.85, f"Elapsed {elapsed:.3f}s was not bounded near 0.5s"
        assert server.client_closed.wait(timeout=1.0), "Client did not close the connection upon deadline expiration"
        assert snapshot["stream_connection"] == "connected"
        assert snapshot["stream_capability"] == "streaming"
        assert snapshot["reasoning_delta_events"] == 2
        assert snapshot["matching_session_events"] == 2
        assert snapshot["current_reasoning_text"] == "step 1 step 2"
        assert snapshot["current_reasoning_tokens"] is None
        assert snapshot["observation_deadline_limited"] is True
        assert "observation_deadline_limited" in snapshot["warnings"]
        assert snapshot["coverage"] == "incomplete"
        assert snapshot["reconnection_gaps"] == 0
    finally:
        server.close()


def test_sse_stream_disconnection_before_deadline_records_gap_and_reconnects():
    import socket
    import threading
    import time
    from llm_monitor.live import OpenCodeSSEClient, observe_session

    connection_count = 0
    lock = threading.Lock()

    def disconnect_handler(conn, stop_event, client_closed):
        nonlocal connection_count
        with lock:
            connection_count += 1
            current = connection_count
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
        if current == 1:
            # First connection: send nothing, immediately close to trigger disconnect
            time.sleep(0.05)
            conn.close()
            return
        # Second connection: hold until deadline
        conn.settimeout(0.05)
        while not stop_event.is_set():
            try:
                data = conn.recv(1024)
                if not data:
                    client_closed.set()
                    break
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                client_closed.set()
                break

    server = _FakeSSEServer(disconnect_handler)
    try:
        class FakeClient:
            def poll(self, _session, _directory):
                return {"session_id": "ses-reconnect", "session_state": {"type": "busy"}}

        stream = OpenCodeSSEClient(server.url, r"C:\project", timeout=5.0, max_reconnects=2)
        t0 = time.monotonic()
        snapshot = observe_session(FakeClient(), stream, session_id="ses-reconnect", project_directory=r"C:\project",
                                   observe_seconds=0.6)
        elapsed = time.monotonic() - t0

        assert 0.5 <= elapsed <= 1.0, f"Elapsed {elapsed:.3f}s was not bounded near 0.6s"
        assert snapshot["connection_attempts"] >= 2
        assert snapshot["reconnection_gaps"] >= 1
        assert "reconnection_gap" in snapshot["warnings"]
        assert snapshot["coverage"] == "incomplete"
    finally:
        server.close()


def test_sse_stream_disconnect_at_deadline_exits_cleanly_without_reconnect():
    import threading
    import time
    from llm_monitor.live import OpenCodeSSEClient, observe_session

    connection_count = 0
    lock = threading.Lock()

    def disconnect_at_deadline_handler(conn, stop_event, client_closed):
        nonlocal connection_count
        with lock:
            connection_count += 1
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
        # Hold connection until close to deadline, then close socket
        time.sleep(0.35)
        conn.close()

    server = _FakeSSEServer(disconnect_at_deadline_handler)
    try:
        class FakeClient:
            def poll(self, _session, _directory):
                return {"session_id": "ses-disc-deadline", "session_state": {"type": "busy"}}

        stream = OpenCodeSSEClient(server.url, r"C:\project", timeout=5.0, max_reconnects=2)
        t0 = time.monotonic()
        snapshot = observe_session(FakeClient(), stream, session_id="ses-disc-deadline", project_directory=r"C:\project",
                                   observe_seconds=0.35)
        elapsed = time.monotonic() - t0

        assert 0.3 <= elapsed <= 0.7, f"Elapsed {elapsed:.3f}s was not bounded near 0.35s"
        # Should not attempt reconnect because deadline was reached
        assert connection_count == 1
        assert snapshot["observation_deadline_limited"] is True
    finally:
        server.close()
