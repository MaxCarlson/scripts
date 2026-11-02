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


def test_live_accepts_trial_identity_for_cross_artifact_correlation():
    args = build_parser().parse_args([
        "live", "--trial-id", "EXP-20261029-01", "--project-directory", "C:/trial",
        "--session", "ses-1", "--observe-seconds", "5", "--format", "json",
    ])

    assert args.command == "live"
    assert args.trial_id == "EXP-20261029-01"


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


def test_web_command_parses_local_host_options_without_database_flags():
    args = build_parser().parse_args([
        "web", "-p", "8788", "-e", "http://127.0.0.1:1234", "-n", "--refresh-interval", "3",
    ])

    assert args.command == "web"
    assert args.port == 8788
    assert args.endpoint == "http://127.0.0.1:1234"
    assert args.no_browser is True
    assert args.refresh_interval == 3



def test_web_command_parses_recording_options():
    args = build_parser().parse_args([
        "web", "--gateway", "-R", "metadata", "-d", "custom_telemetry.db"
    ])
    assert args.command == "web"
    assert args.gateway is True
    assert args.record_inferences == "metadata"
    assert args.database == Path("custom_telemetry.db")

    args_content = build_parser().parse_args([
        "web", "--gateway", "-R", "content"
    ])
    assert args_content.record_inferences == "content"
    assert args_content.database is None


def test_web_command_rejects_recording_without_gateway():
    import pytest
    from llm_monitor.web import run_web

    with pytest.raises(ValueError, match="--record-inferences requires --gateway"):
        run_web(record_inferences="metadata", gateway_enabled=False)


def test_web_command_database_without_recording_is_readonly(tmp_path, monkeypatch):
    import pytest
    from llm_monitor.storage import TelemetryStore, TelemetryStoreError
    from llm_monitor.web import run_web

    test_port = 58788
    nonexistent = tmp_path / "never_created.db"
    with pytest.raises(TelemetryStoreError, match="telemetry database does not exist"):
        run_web(port=test_port, database=str(nonexistent), no_browser=True)
    assert not nonexistent.exists()

    existing = tmp_path / "existing.db"
    with TelemetryStore(existing) as init_store:
        init_store.database_info()
    assert existing.is_file()

    fake_server_created = []
    class FakeServer:
        def run(self):
            pass

    def fake_create_server(app, host, port):
        assert app.state.inference_history_store is not None
        assert app.state.inference_history_store.readonly is True
        assert app.state.inference_recorder is None
        fake_server_created.append(True)
        return FakeServer()

    monkeypatch.setattr("web_ui_tools.create_server", fake_create_server)
    exit_code = run_web(port=test_port, database=str(existing), no_browser=True)
    assert exit_code == 0
    assert fake_server_created == [True]


def test_web_command_gateway_alone_never_creates_database(tmp_path, monkeypatch):
    from llm_monitor.web import run_web

    test_port = 58788
    fake_server_created = []
    class FakeServer:
        def run(self):
            pass

    def fake_create_server(app, host, port):
        assert app.state.inference_history_store is None
        assert app.state.inference_recorder is None
        fake_server_created.append(True)
        return FakeServer()

    monkeypatch.setattr("web_ui_tools.create_server", fake_create_server)
    exit_code = run_web(port=test_port, gateway_enabled=True, no_browser=True)
    assert exit_code == 0
    assert fake_server_created == [True]
    assert list(tmp_path.glob("*.db*")) == []


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
        assert store.database_info()["counts"]["events"] == len(event) + 2


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

        def sessions(self, directory=None):
            assert directory == "C:/isolated/project"
            return ApiResult([{"id": "recorded-session"}])

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

    assert cli.main([
        "record", "--all", "--project-directory", "C:/isolated/project",
        "--url", "http://user:secret@127.0.0.1:4096/api?token=hidden",
        "-d", str(database), "-i", "0.1",
    ]) == 130
    output = capsys.readouterr().out
    assert "new=" in output
    assert "project=C:/isolated/project" in output
    assert "http://127.0.0.1:4096" in output
    assert "secret" not in output
    assert "hidden" not in output
    with TelemetryStore(database, readonly=True) as store:
        bundle = store.history_bundle("recorded-session", endpoint="http://127.0.0.1:4096")
    assert len([event for event in bundle["analysis_events"] if event.category == "inference"]) == 1


def test_record_all_help_explains_project_scoped_discovery():
    from llm_monitor.cli import build_parser

    record_help = build_parser()._subparsers._group_actions[0].choices["record"].format_help()
    assert "selected OpenCode project" in " ".join(record_help.split())
    assert "--project-directory" in record_help


def test_tui_and_alert_commands_parse_existing_style_flags():
    parser = build_parser()
    tui = parser.parse_args(["tui", "-s", "session-a", "-d", "telemetry.sqlite3", "-i", "1.5", "-P"])
    all_sessions = parser.parse_args(["tui", "-a"])
    alert_test = parser.parse_args(["alerts", "test", "-s", "session-a", "-d", "telemetry.sqlite3"])
    alert_ack = parser.parse_args(["alerts", "acknowledge", "-i", "alert-id", "-d", "telemetry.sqlite3"])

    assert (tui.command, tui.session, tui.interval, tui.persist_alerts) == ("tui", "session-a", 1.5, True)
    assert all_sessions.all is True
    assert alert_test.alert_command == "test"
    assert alert_ack.alert_command == "acknowledge"


def test_live_command_requires_project_session_and_supports_bounded_json():
    from llm_monitor.cli import build_parser

    args = build_parser().parse_args([
        "live", "--url", "http://127.0.0.1:4096", "--project-directory", r"C:\pilot",
        "--session", "ses-1", "--observe-seconds", "5", "--format", "json",
    ])

    assert (args.command, args.session, args.observe_seconds, args.format) == ("live", "ses-1", 5.0, "json")
    assert args.show_reasoning is False


def test_live_json_requires_a_bounded_observation_window(capsys):
    from llm_monitor.cli import main

    assert main(["live", "-p", r"C:\pilot", "-s", "ses-1", "-f", "json"]) == 2
    assert "--observe-seconds" in capsys.readouterr().err


def test_live_json_outputs_snapshot_without_reasoning_by_default(monkeypatch, capsys):
    from llm_monitor import cli
    from llm_monitor.live import SSEEvent

    class FakeOpenCodeClient:
        def __init__(self, _url, **_kwargs):
            pass

        def poll(self, _session, _directory):
            return {"session_state": {"type": "busy"}, "last_assistant_is_complete": False}

    class FakeStream:
        connected = True
        reconnection_gaps = 0
        server_origin = "http://127.0.0.1:4096"

        def __init__(self, *_args, **_kwargs):
            pass

        def events(self, _seconds):
            yield SSEEvent(event="__connected__")
            yield SSEEvent(data=json.dumps({"type": "message.part.delta", "properties": {
                "sessionID": "ses-1", "messageID": "msg-1", "partID": "prt-1",
                "field": "reasoning", "delta": "private reasoning"}}))

    monkeypatch.setattr(cli, "OpenCodeClient", FakeOpenCodeClient)
    monkeypatch.setattr(cli, "OpenCodeSSEClient", FakeStream)

    assert cli.main(["live", "-p", r"C:\pilot", "-s", "ses-1", "-t", "1", "-f", "json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["activity"] == "reasoning"
    assert output["current_reasoning_tokens"] is None
    assert "current_reasoning_text" not in output
    assert "private reasoning" not in json.dumps(output)

    assert cli.main(["live", "-p", r"C:\pilot", "-s", "ses-1", "-t", "1", "-f", "json",
                     "--show-reasoning"]) == 0
    raw_opt_in = json.loads(capsys.readouterr().out)
    assert raw_opt_in["current_reasoning_text"] == "private reasoning"


def test_alert_rules_cli_is_offline_and_json(capsys):
    from llm_monitor.cli import main

    assert main(["alerts", "rules", "-f", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == 1
    assert "blocker.permission" in {item["rule_id"] for item in result["rules"]}


def test_tui_cli_reports_noninteractive_terminal_without_creating_database(tmp_path, capsys):
    from llm_monitor.cli import main

    database = tmp_path / "must-not-be-created.sqlite3"
    assert main(["tui", "--interval", "1", "--persist-alerts", "--database", str(database)]) == 1
    assert "interactive terminal" in capsys.readouterr().err
    assert not database.exists()


def test_web_parser_startup_syntax_and_options():
    parser = build_parser()

    # Legacy startup syntax without explicit action
    args1 = parser.parse_args(["web", "-p", "8788", "--gateway", "-R", "content"])
    assert args1.command == "web"
    assert args1.action == "start"
    assert args1.port == 8788
    assert args1.gateway is True
    assert args1.record_inferences == "content"

    # Status action
    args2 = parser.parse_args(["web", "status", "-p", "8788"])
    assert args2.command == "web"
    assert args2.action == "status"
    assert args2.port == 8788

    # Stop preview
    args3 = parser.parse_args(["web", "stop", "-p", "8788"])
    assert args3.command == "web"
    assert args3.action == "stop"
    assert args3.port == 8788
    assert args3.execute is False

    # Stop execute
    args4 = parser.parse_args(["web", "stop", "-p", "8788", "-x"])
    assert args4.command == "web"
    assert args4.action == "stop"
    assert args4.port == 8788
    assert args4.execute is True
    assert args4.force is False

    # Stop execute with force
    args5 = parser.parse_args(["web", "stop", "-p", "8788", "-x", "--force"])
    assert args5.command == "web"
    assert args5.action == "stop"
    assert args5.execute is True
    assert args5.force is True


def test_web_stop_force_without_execute_rejected(capsys):
    from llm_monitor.cli import main

    rc = main(["web", "stop", "-p", "8788", "--force"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--force requires -x/--execute" in err


def test_web_cli_routing(monkeypatch):
    from llm_monitor.cli import main
    import llm_monitor.server_lifecycle as slc
    import llm_monitor.web as web_mod

    called = {}

    def fake_status(port=None, host="127.0.0.1", state_dir=None, as_json=False):
        called["status"] = (port, as_json)
        return 0

    def fake_stop(port=None, host="127.0.0.1", execute=False, force=False, state_dir=None, timeout=5.0, as_json=False):
        called["stop"] = (port, execute, force, as_json)
        return 0

    def fake_run(**kwargs):
        called["run"] = kwargs
        return 0

    monkeypatch.setattr(slc, "status_server", fake_status)
    monkeypatch.setattr(slc, "stop_server", fake_stop)
    monkeypatch.setattr(web_mod, "run_web", fake_run)

    assert main(["web", "status", "-p", "8788"]) == 0
    assert called.get("status") == (8788, False)

    assert main(["web", "status", "-p", "8788", "-F", "json"]) == 0
    assert called.get("status") == (8788, True)

    assert main(["web", "stop", "-p", "8788", "-x", "-f", "--format", "json"]) == 0
    assert called.get("stop") == (8788, True, True, True)

    assert main(["web", "-p", "8788", "--gateway", "-R", "content"]) == 0
    assert called.get("run", {}).get("port") == 8788
    assert called.get("run", {}).get("gateway_enabled") is True
    assert called.get("run", {}).get("record_inferences") == "content"

