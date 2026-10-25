import json
from argparse import Namespace
from pathlib import Path

from llm_monitor.cli import _analyze_session, build_parser
from llm_monitor.events import events_from_messages
from llm_monitor.opencode import ApiResult, HistoryCoverage, HistoryResult


def test_watch_accepts_session_json_and_interval_options():
    args = build_parser().parse_args(
        ["watch", "--session", "ses-1", "--format", "json", "--interval", "0.5"]
    )

    assert args.command == "watch"
    assert args.session == "ses-1"
    assert args.format == "json"
    assert args.interval == 0.5


def test_diagnose_and_report_accept_session_format_and_source_overrides():
    parser = build_parser()
    diagnose = parser.parse_args(
        ["diagnose", "--session", "ses-1", "--format", "json", "--lmstudio-url", "http://lms:1234"]
    )
    report = parser.parse_args(["report", "-s", "ses-1", "-f", "text"])

    assert diagnose.command == "diagnose"
    assert diagnose.session == "ses-1"
    assert diagnose.lmstudio_url == "http://lms:1234"
    assert report.command == "report"
    assert report.session == "ses-1"


def test_diagnose_json_and_report_text_use_same_evidence_without_live_services(monkeypatch, capsys):
    events = events_from_messages("ses-1", [{"info": {"id": "a1", "role": "assistant", "finish": "stop",
        "time": {"created": 1000, "completed": 2000}, "tokens": {"input": 40, "output": 10}}, "parts": []}])
    history = HistoryResult(events, HistoryCoverage("partial", "legacy", 1, 100, reason="bounded"))

    class Client:
        def __init__(self, *_args):
            pass

        def collect_history(self, *_args):
            return history

        def get_json(self, path, _directory=None):
            if path.startswith("/session/ses-1"):
                return ApiResult({"id": "ses-1", "directory": "C:/work", "model": {"id": "model-a"}})
            if path == "/session/status":
                return ApiResult({"ses-1": {"type": "idle"}})
            return ApiResult({})

    class LMStudio:
        def __init__(self, *_args):
            pass

        def list_models(self):
            return []

    monkeypatch.setattr("llm_monitor.cli.OpenCodeClient", Client)
    monkeypatch.setattr("llm_monitor.cli.LMStudioClient", LMStudio)
    base = dict(session="ses-1", directory=None, lmstudio_url="http://unused", mcp_jobs=None, format="json")

    assert _analyze_session(Client(), Namespace(**base), report=False) == 0
    json_result = json.loads(capsys.readouterr().out)
    assert "timeline" not in json_result
    assert json_result["analysis"]["inference"]["latest_completed"]["input_tokens"] == 40
    assert any(item["code"] == "coverage.partial_history" for item in json_result["findings"])

    report_args = Namespace(**{**base, "format": "text"})
    assert _analyze_session(Client(), report_args, report=True) == 0
    text_result = capsys.readouterr().out
    assert "Inference: 1/1 completed" in text_result
    assert "Timeline:" in text_result


def test_watch_cancellation_returns_clean_interrupt_code(monkeypatch):
    from llm_monitor import cli

    class Client:
        def __init__(self, *_args):
            pass

        def poll(self, *_args):
            return {"session_id": "ses-1"}

    monkeypatch.setattr(cli, "OpenCodeClient", Client)
    monkeypatch.setattr(cli.time, "sleep", lambda _interval: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert cli.main(["watch", "-s", "ses-1", "-i", "0.1", "-f", "json"]) == 130


def test_persistent_commands_parse_database_and_recording_options():
    parser = build_parser()
    record = parser.parse_args(["record", "-s", "ses-1", "-i", "3", "-d", "data.sqlite3", "-f", "json"])
    all_sessions = parser.parse_args(["record", "--all", "-g"])
    history = parser.parse_args(["history", "-s", "ses-1", "-d", "data.sqlite3"])
    prune = parser.parse_args(["db", "prune", "-d", "data.sqlite3", "-r", "30", "-w"])
    report = parser.parse_args(["report", "-s", "ses-1", "-H", "-D", "data.sqlite3"])

    assert record.command == "record" and record.session == "ses-1" and record.interval == 3
    assert all_sessions.all is True and all_sessions.hardware is True
    assert history.command == "history" and history.database == Path("data.sqlite3")
    assert prune.db_command == "prune" and prune.write is True and prune.older_than_days == 30
    assert report.history is True and report.database == Path("data.sqlite3")


def test_database_commands_and_historical_report_work_offline(tmp_path, capsys):
    from llm_monitor.cli import main
    from llm_monitor.storage import TelemetryStore

    database = tmp_path / "history.sqlite3"
    session_id = "offline-session"
    messages = [{"info": {"id": "assistant-1", "role": "assistant", "finish": "stop",
                           "time": {"created": 1000, "completed": 2000},
                           "tokens": {"input": 600, "output": 40, "reasoning": 12}}, "parts": []}]
    events = events_from_messages(session_id, messages, observed_at="2026-01-01T00:00:03+00:00")
    snapshot = {"polled_at": "2026-01-01T00:00:03+00:00", "normalized_state": "idle",
                "session_info": {"model": "model-a", "agent": "worker"},
                "history_coverage": {"status": "partial", "source": "legacy", "pages": 1, "limit": 100,
                                     "reason": "bounded history window"}, "errors": {}}
    with TelemetryStore(database) as store:
        store.ingest_poll("opencode", "http://127.0.0.1:4096", session_id, snapshot, events)

    assert main(["db", "info", "-d", str(database), "-f", "json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["counts"]["sessions"] == 1
    assert main(["db", "check", "-d", str(database), "-f", "json"]) == 0
    check = json.loads(capsys.readouterr().out)
    assert check["ok"] is True

    assert main(["report", "-s", session_id, "-H", "-D", str(database), "-f", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"] == "persisted_telemetry"
    assert report["analysis"]["inference"]["latest_completed"]["input_tokens"] == 600
    assert report["analysis"]["observed_token_totals"]["input"] == 600
    assert report["analysis"]["context"]["utilization_percent"] is None
    assert report["session"]["task_acceptance"] == "unverified"
    assert report["history_coverage"]["status"] == "partial"


def test_database_prune_cli_is_dry_run_without_write(tmp_path, capsys):
    from llm_monitor.cli import main
    from llm_monitor.storage import TelemetryStore

    database = tmp_path / "prune.sqlite3"
    event = events_from_messages("ses-prune", [{"info": {"id": "m1", "role": "assistant"}, "parts": []}],
                                 observed_at="2000-01-01T00:00:00+00:00")
    snapshot = {"polled_at": "2000-01-01T00:00:01+00:00", "normalized_state": "idle",
                "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 10}}
    with TelemetryStore(database) as store:
        store.ingest_poll("opencode", "http://127.0.0.1:4096", "ses-prune", snapshot, event)

    assert main(["db", "prune", "-d", str(database), "-r", "1", "-f", "json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["written"] is False
    with TelemetryStore(database, readonly=True) as store:
        assert store.database_info()["counts"]["events"] == len(event) + 1


def test_record_command_commits_before_clean_interrupt(tmp_path, monkeypatch, capsys):
    from llm_monitor import cli
    from llm_monitor.opencode import ApiResult, HistoryCoverage, HistoryResult
    from llm_monitor.storage import TelemetryStore

    database = tmp_path / "record-cli.sqlite3"
    events = events_from_messages("recorded-session", [{"info": {"id": "m1", "role": "assistant",
        "finish": "stop", "time": {"created": 1000, "completed": 2000}}, "parts": []}],
        observed_at="2026-01-01T00:00:00+00:00")

    class Client:
        def __init__(self, *_args):
            pass

        def collect_history(self, session_id, _directory=None):
            return HistoryResult(events, HistoryCoverage("complete", "cursor", 1, 100))

        def poll(self, session_id, _directory=None):
            return {"session_id": session_id, "polled_at": "2026-01-01T00:00:02+00:00",
                    "normalized_state": "idle", "session_info": {"model": "model-a", "agent": "worker"},
                    "history_coverage": {"status": "complete", "source": "cursor", "pages": 1, "limit": 100},
                    "errors": {}}

        def events_for_session(self, _session_id):
            return events

        def get_json(self, *_args):
            return ApiResult({})

    class LMStudio:
        def __init__(self, *_args):
            pass

        def list_models(self):
            return []

    monkeypatch.setattr(cli, "OpenCodeClient", Client)
    monkeypatch.setattr(cli, "LMStudioClient", LMStudio)
    monkeypatch.setattr(cli.time, "sleep", lambda _interval: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert cli.main(["record", "-s", "recorded-session", "-d", str(database), "-i", "0.1"]) == 130
    assert "new=" in capsys.readouterr().out
    with TelemetryStore(database, readonly=True) as store:
        bundle = store.history_bundle("recorded-session", endpoint="http://127.0.0.1:4096")
    assert len([event for event in bundle["analysis_events"] if event.category == "inference"]) == 1
