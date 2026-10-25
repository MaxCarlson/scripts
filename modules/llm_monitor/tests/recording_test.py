from llm_monitor.events import events_from_messages
from llm_monitor.opencode import HistoryCoverage, HistoryResult
from llm_monitor.recording import Recorder
from llm_monitor.storage import TelemetryStore


class FakeClient:
    def __init__(self):
        self.history_calls = []
        self.poll_calls = []
        self.current_events = {}
        self.poll_counter = 0

    def collect_history(self, session_id, _directory=None):
        self.history_calls.append(session_id)
        events = events_from_messages(session_id, [{"info": {"id": f"a-{session_id}", "role": "assistant",
            "finish": "stop", "time": {"created": 1000, "completed": 2000}}, "parts": []}],
            observed_at="2026-01-01T00:00:00+00:00")
        self.current_events[session_id] = events
        return HistoryResult(events, HistoryCoverage("complete", "cursor", 1, 100))

    def poll(self, session_id, _directory=None):
        self.poll_calls.append(session_id)
        self.poll_counter += 1
        return {"session_id": session_id, "polled_at": f"2026-01-01T00:00:{self.poll_counter * 2:02d}+00:00",
                "normalized_state": "idle", "session_info": {"model": "model-a", "agent": "worker"},
                "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 100},
                "errors": {}}

    def events_for_session(self, session_id):
        return self.current_events.get(session_id, [])


def test_recorder_seeds_once_then_replays_idempotently_and_marks_restart_gap(tmp_path):
    path = tmp_path / "record.sqlite3"
    client = FakeClient()
    with TelemetryStore(path) as store:
        recorder = Recorder(client, store, endpoint="http://localhost:4096", interval=2)
        first = recorder.collect_cycle(["ses-1"])
        second = recorder.collect_cycle(["ses-1"])

    assert client.history_calls == ["ses-1"]
    assert first["inserted"] > 0
    assert second["inserted"] == 1  # a new state sample; provider events are deduplicated
    assert second["duplicates"] > 0

    with TelemetryStore(path) as store:
        restarted = Recorder(client, store, endpoint="http://localhost:4096", interval=2)
        restarted.collect_cycle(["ses-1"])
        bundle = store.history_bundle("ses-1", provider_type="opencode")

    assert client.history_calls == ["ses-1"]
    assert any(gap["category"] == "monitor_offline" for gap in bundle["gaps"])
    assert len([event for event in bundle["analysis_events"] if event.category == "inference"]) == 1


def test_recorder_continues_after_one_session_poll_failure(tmp_path):
    class PartialClient(FakeClient):
        def poll(self, session_id, directory=None):
            if session_id == "bad":
                return {"session_id": "bad", "polled_at": "2026-01-01T00:00:02+00:00",
                        "normalized_state": None, "history_coverage": {"status": "unavailable", "source": "legacy",
                        "pages": 0, "limit": 100, "reason": "unavailable"}, "errors": {"messages": "unavailable"}}
            return super().poll(session_id, directory)

    client = PartialClient()
    with TelemetryStore(tmp_path / "record.sqlite3") as store:
        recorder = Recorder(client, store, endpoint="http://localhost:4096", interval=2)
        result = recorder.collect_cycle(["bad", "good"])

    assert result["sessions"] == 2
    assert client.poll_calls == ["good"]
    assert result["unavailable"] == 1
