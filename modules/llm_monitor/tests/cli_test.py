import json
from argparse import Namespace

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
