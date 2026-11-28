from __future__ import annotations

import builtins
import json
import subprocess
import sys
import time
import tomllib
import types
from argparse import Namespace
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import agent_continuity.dispatcher_cli as dispatcher_cli
from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import (
    _exact_launched_provider_pid,
    _format_exit_summary,
    _native_argv,
    _open,
    _prompt_native_arguments,
    _read_launch_prompt,
    _run_reserved_provider_process,
    _validate_addressed_launch_prompt,
    build_parser,
    dispatch,
)
from agent_continuity.errors import ContinuityError
from agent_continuity.interactive import filter_items, format_timestamp, select_item
from agent_continuity.service import ContinuityService


def test_restore_startup_evidence_uses_exact_provider_pid_and_launch_ancestry():
    from types import SimpleNamespace

    from agent_continuity.runtime_discovery import (
        MatchStatus,
        ProcessAncestry,
        ProcessIdentity,
        ProcessLiveness,
        SessionIdentityState,
    )

    launched_wrapper = ProcessIdentity(100, 1_000_000_000)
    actual_provider = ProcessIdentity(200, 2_000_000_000)
    observation = SimpleNamespace(
        process_liveness=ProcessLiveness.RUNNING,
        process_session_match=MatchStatus.EXACT,
        session_identity_state=SessionIdentityState.EXACT,
        identity_conflict=False,
        evidence_conflict=False,
        processes=(SimpleNamespace(identity=actual_provider),),
        ancestry=(ProcessAncestry((launched_wrapper,), ("llmd.exe",), True, False),),
    )

    assert _exact_launched_provider_pid(observation, launched_wrapper_pid=100) == 200
    assert _exact_launched_provider_pid(observation, launched_wrapper_pid=999) is None
    conflicting = SimpleNamespace(
        process_liveness=observation.process_liveness,
        process_session_match=observation.process_session_match,
        session_identity_state=observation.session_identity_state,
        identity_conflict=False,
        evidence_conflict=True,
        processes=observation.processes,
        ancestry=observation.ancestry,
    )
    assert _exact_launched_provider_pid(conflicting, launched_wrapper_pid=100) is None


@pytest.mark.parametrize("exit_code", [0, 17])
def test_reserved_provider_runner_streams_harmless_child_and_reports_its_pid(monkeypatch, capfd, exit_code):
    from types import SimpleNamespace

    from agent_continuity.runtime_discovery import (
        MatchStatus,
        ProcessAncestry,
        ProcessIdentity,
        ProcessLiveness,
        SessionIdentityState,
    )

    real_popen = subprocess.Popen
    child = None
    observations = 0

    class Dispatcher:
        def observe_runtime_session(self, provider, environment_id, session_id):
            nonlocal observations
            observations += 1
            if observations < 3:
                return None
            if child is None or child.poll() is not None:
                return None
            identity = ProcessIdentity(child.pid, 2_000_000_000)
            return SimpleNamespace(
                process_liveness=ProcessLiveness.RUNNING,
                process_session_match=MatchStatus.EXACT,
                session_identity_state=SessionIdentityState.EXACT,
                identity_conflict=False,
                evidence_conflict=False,
                processes=(SimpleNamespace(identity=identity),),
                ancestry=(ProcessAncestry((), (), False, False),),
            )

    def spawn(*args, **kwargs):
        nonlocal child
        child = real_popen(*args, **kwargs)
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    acknowledged = []
    result = _run_reserved_provider_process(
        Dispatcher(),
        [
            sys.executable,
            "-c",
            f"import sys,time; print('guarded-stream-out',flush=True); "
            f"print('guarded-stream-err',file=sys.stderr,flush=True); "
            f"time.sleep(0.45); sys.exit({exit_code})",
        ],
        cwd=None,
        provider="codex",
        environment_id="local",
        session_id="guarded-session",
        on_provider_startup=acknowledged.append,
    )

    assert result.returncode == exit_code
    assert acknowledged == [child.pid]
    captured = capfd.readouterr()
    assert "guarded-stream-out" in captured.out
    assert "guarded-stream-err" in captured.err


def test_pane_run_consumes_and_acknowledges_exact_harmless_provider_child(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agent_continuity.dispatcher_cli import _run_pane
    from agent_continuity.runtime_discovery import (
        MatchStatus,
        ProcessAncestry,
        ProcessIdentity,
        ProcessLiveness,
        SessionIdentityState,
    )
    from agent_continuity.workspace_ownership import RestorationReservationStore

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("G", "A", provider="codex", session_id="native-session")
    slot = dispatcher.get_slot(gui="G", name="A")
    environment_id = slot["current"]["environment_id"]
    store = RestorationReservationStore(home)
    reservation = store.create_reservation(
        checkpoint_id="checkpoint-dispatcher",
        queue_entry_id="queue-dispatcher",
        attempt=3,
        slot_id=slot["slot_id"],
        provider="codex",
        native_session_id="native-session",
        environment_id=environment_id,
        operator_id="test",
    )
    launch_id, pane_id = "launch-dispatcher", "pane-dispatcher"
    reservation = store.bind_launch(reservation.reservation_id, launch_id=launch_id, pane_id=pane_id)

    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._native_argv",
        lambda *args, **kwargs: [sys.executable, "-c", "import time; time.sleep(0.35)"],
    )
    real_popen = subprocess.Popen
    child = None

    def spawn(*args, **kwargs):
        nonlocal child
        child = real_popen(*args, **kwargs)
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)

    def observe_runtime_session(provider, observed_environment, session_id):
        if child is None or child.poll() is not None:
            return None
        identity = ProcessIdentity(child.pid, max(1, time.time_ns()))
        return SimpleNamespace(
            process_liveness=ProcessLiveness.RUNNING,
            process_session_match=MatchStatus.EXACT,
            session_identity_state=SessionIdentityState.EXACT,
            identity_conflict=False,
            evidence_conflict=False,
            processes=(SimpleNamespace(identity=identity),),
            ancestry=(ProcessAncestry((), (), False, False),),
        )

    monkeypatch.setattr(dispatcher, "observe_runtime_session", observe_runtime_session)
    output = StringIO()
    assert _run_pane(
        dispatcher,
        slot_id=slot["slot_id"],
        launch_id=None,
        input_stream=StringIO("1\n"),
        output_stream=output,
        expected_session_identity=("codex", environment_id, "native-session"),
        reservation_id=reservation.reservation_id,
        reservation_token=reservation.reservation_token,
        checkpoint_id=reservation.checkpoint_id,
        queue_entry_id=reservation.queue_entry_id,
        attempt=reservation.attempt,
        reservation_launch_id=launch_id,
        pane_id=pane_id,
    ) == 0

    acknowledged = store.get_reservation(reservation.reservation_id)
    assert acknowledged.dispatcher_ownership_acknowledged is True
    assert acknowledged.provider_startup_confirmed is True
    assert acknowledged.exact_association_confirmed is True
    assert acknowledged.provider_pid == child.pid
    assert acknowledged.launch_id == launch_id
    assert acknowledged.pane_id == pane_id
    assert "LLMD exit summary - normal (exit 0)" in output.getvalue()
    assert "Native session: native-session" in output.getvalue()


def test_pane_run_reports_abnormal_exit_with_exact_reproducible_session(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import _run_pane

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Agent", provider="codex", session_id="exact-session")
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    output = StringIO()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *args, **kwargs: ["guarded-codex"])
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._run_provider_process",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 17),
    )

    assert _run_pane(
        dispatcher,
        slot_id=slot["slot_id"],
        launch_id=None,
        input_stream=StringIO(),
        output_stream=output,
        expected_session_identity=("codex", slot["current"]["environment_id"], "exact-session"),
    ) == 17
    summary = output.getvalue()
    assert "LLMD exit summary - abnormal (exit 17)" in summary
    assert "Native session: exact-session" in summary
    assert "llmd' 'continue" in summary


def test_pane_run_reports_handled_interrupt_without_claiming_safe_retry(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import _run_pane

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Agent", provider="codex", session_id="exact-session")
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    output = StringIO()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *args, **kwargs: ["guarded-codex"])
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._run_provider_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        _run_pane(
            dispatcher,
            slot_id=slot["slot_id"],
            launch_id=None,
            input_stream=StringIO(),
            output_stream=output,
            expected_session_identity=("codex", slot["current"]["environment_id"], "exact-session"),
        )
    summary = output.getvalue()
    assert "LLMD exit summary - interrupted (exit 130)" in summary
    assert "Native session: exact-session" in summary
    assert "llmd' 'continue" in summary


def test_prompt_flags_are_distinct_from_profile_and_native_provider_options():
    parser = build_parser()
    for command in ("start", "switch", "continue", "review", "return"):
        subparser = parser._subparsers._group_actions[0].choices[command]
        assert "-Q" in subparser._option_string_actions
        assert "-F" in subparser._option_string_actions
        assert "-M" in subparser._option_string_actions
        assert "-P" in subparser._option_string_actions

    args = parser.parse_args(["continue", "-g", "G", "-n", "A", "-Q"])
    assert args.clipboard_prompt is True
    assert args.profile is None


@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("resuming", [False, True])
def test_prompt_native_arguments_are_one_shot_and_interactive(provider, resuming):
    prompt = "Unicode ☃\r\nsecond line"
    assert _prompt_native_arguments(provider, prompt, resuming=resuming) == [prompt]


@pytest.mark.parametrize("resuming", [False, True])
def test_agy_prompt_native_arguments_fail_closed_for_managed_bootstrap_flow(resuming):
    with pytest.raises(ContinuityError, match="managed bootstrap flow"):
        _prompt_native_arguments("agy", "hello\n世界", resuming=resuming)


def test_prompt_file_read_preserves_multiline_unicode_and_does_not_echo(tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_bytes("To-Agent: Agent A\r\n\r\n雪\n".encode())
    prompt = _read_launch_prompt(prompt_file=prompt_file)
    assert prompt == "To-Agent: Agent A\r\n\r\n雪\n"


def test_clipboard_prompt_reader_preserves_unicode_and_never_logs_content(monkeypatch):
    prompt = "clipboard ☃\r\nsecond line"
    monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which", lambda name: "pwsh")
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=prompt.encode("utf-8")),
    )
    assert _read_launch_prompt(clipboard=True) == prompt


def test_prompt_source_errors_are_redacted_and_utf8_is_required(tmp_path, monkeypatch):
    malformed = tmp_path / "malformed.txt"
    malformed.write_bytes(b"\xff\xfe")
    with pytest.raises(ContinuityError, match="Cannot read UTF-8 prompt file"):
        _read_launch_prompt(prompt_file=malformed)

    monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which", lambda name: None)
    with pytest.raises(ContinuityError, match="No supported system clipboard reader"):
        _read_launch_prompt(clipboard=True)

    with pytest.raises(ContinuityError, match="Choose exactly one"):
        _read_launch_prompt(prompt="hidden-content", clipboard=True)


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_native_resume_command_delivers_prompt_once_to_guarded_child(tmp_path, monkeypatch, provider):
    from types import SimpleNamespace

    received = tmp_path / "received.json"
    code = f"import json,sys; open({str(received)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[-1], ensure_ascii=False))"

    class GuardedAdapter:
        def find_executable(self):
            return sys.executable

        def resolve_resume_command(self, session_id, **kwargs):
            return SimpleNamespace(argv=[sys.executable, "-c", code, provider, "resume", session_id])

    dispatcher = SimpleNamespace(continuity=SimpleNamespace(adapters={provider: GuardedAdapter()}))
    monkeypatch.setattr("agent_continuity.dispatcher_cli._resolve_environment",
                        lambda *args, **kwargs: SimpleNamespace(environment_id="local", runtime_kind="windows", distro=None))
    monkeypatch.setattr("agent_continuity.dispatcher_cli._validate_additional_directories", lambda *args, **kwargs: None)
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    token = dispatcher_cli._ONE_TIME_PROMPT.set("first line\r\nsecond line 雪")
    try:
        argv = _native_argv(dispatcher, provider, "session-exact", environment_id="local", cwd=None)
        assert dispatcher_cli._ONE_TIME_PROMPT.get() is None
        second_argv = _native_argv(dispatcher, provider, "session-exact", environment_id="local", cwd=None)
        completed = dispatcher_cli._run_provider_process(argv, check=False)
    finally:
        dispatcher_cli._ONE_TIME_PROMPT.reset(token)

    assert completed.returncode == 0
    assert json.loads(received.read_text(encoding="utf-8")) == "first line\r\nsecond line 雪"
    assert second_argv[-1] == "session-exact"


def test_uncertain_provider_spawn_does_not_replay_consumed_prompt(tmp_path, monkeypatch):
    from types import SimpleNamespace

    class GuardedAdapter:
        def find_executable(self):
            return sys.executable

        def resolve_resume_command(self, session_id, **kwargs):
            return SimpleNamespace(argv=[sys.executable, "-c", "pass", "codex", "resume", session_id])

    dispatcher = SimpleNamespace(continuity=SimpleNamespace(adapters={"codex": GuardedAdapter()}))
    monkeypatch.setattr("agent_continuity.dispatcher_cli._resolve_environment",
                        lambda *args, **kwargs: SimpleNamespace(environment_id="local", runtime_kind="windows", distro=None))
    monkeypatch.setattr("agent_continuity.dispatcher_cli._validate_additional_directories", lambda *args, **kwargs: None)
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    token = dispatcher_cli._ONE_TIME_PROMPT.set("do not replay")
    try:
        first = _native_argv(dispatcher, "codex", "session-exact", environment_id="local", cwd=None)
        monkeypatch.setattr(
            "agent_continuity.dispatcher_cli._run_provider_process",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("guarded spawn uncertainty")),
        )
        with pytest.raises(OSError, match="guarded spawn uncertainty"):
            dispatcher_cli._run_provider_process(first, check=False)
        retry = _native_argv(dispatcher, "codex", "session-exact", environment_id="local", cwd=None)
    finally:
        dispatcher_cli._ONE_TIME_PROMPT.reset(token)

    assert first[-1] == "do not replay"
    assert retry[-1] == "session-exact"


def test_dry_run_neither_reads_nor_exposes_prompt_content(tmp_path, monkeypatch):
    service = DispatcherService(home_dir=tmp_path / "registry")
    service.register("G", "A", provider="codex", session_id="session-a")
    parser = build_parser()
    output = StringIO()
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._read_launch_prompt",
        lambda **kwargs: pytest.fail("dry-run must not read prompt source"),
    )
    args = parser.parse_args(["-H", str(tmp_path / "registry"), "continue", "-g", "G", "-n", "A",
                              "--prompt", "never-print-this", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=output) == 0
    assert "never-print-this" not in output.getvalue()


def test_managed_agy_prompt_is_rejected_before_any_provider_subprocess(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "A", provider="agy", session_id="agy-session")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "continue", "-g", "G", "-n", "A", "-M", "send once"])
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._run_provider_process",
        lambda *args, **kwargs: pytest.fail("unsupported AGY prompt must fail before subprocess"),
    )
    with pytest.raises(ContinuityError, match="managed bootstrap flow"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())


def test_addressed_prompt_requires_exact_target_identity():
    slot = {"slot_id": "slot-a", "name": "Agent A", "agent_number": 7}
    _validate_addressed_launch_prompt("To-Agent: Agent A\nDo the task", slot=slot)
    _validate_addressed_launch_prompt("Agent: #7 — Agent A\nDo the task", slot=slot)
    with pytest.raises(ContinuityError, match="does not match the exact launch target"):
        _validate_addressed_launch_prompt("To-Agent: Agent B\nDo the task", slot=slot)
    with pytest.raises(ContinuityError, match="exact agent number cannot be verified"):
        _validate_addressed_launch_prompt("Agent: #7 — Agent A\nDo the task", slot={**slot, "agent_number": None})


class TTYInput(StringIO):
    def isatty(self):
        return True


class TTYOutput(StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("outcome", ["normal", "abnormal", "interrupted"])
def test_exit_summary_reproduces_exact_safe_context_without_unknown_values(outcome):
    slot = {
        "gui_alias": "GUI O'Neil",
        "name": "Agent #4",
        "agent_number": 4,
        "slot_id": "slot-exact-4",
    }
    summary = _format_exit_summary(
        slot=slot,
        provider="codex",
        environment_id="env-exact",
        session_id="session-exact",
        effective_cwd=r"C:\work tree\feature",
        native_args=("--sandbox", "read-only", "--model", "safe-model", "--add-dir",
                     r"C:\authorized context", "--future-secret", "do-not-print"),
        allow_native_unknown=True,
        outcome=outcome,
        exit_code=0 if outcome == "normal" else 17,
        shell="powershell",
    )

    assert f"LLMD exit summary - {outcome}" in summary
    assert "GUI: GUI O'Neil" in summary
    assert "Agent: Agent #4 (#4)" in summary
    assert "Native session: session-exact" in summary
    assert "Effective cwd: C:\\work tree\\feature" in summary
    assert "& 'llmd' 'continue'" in summary
    assert "'-S' 'slot-exact-4'" in summary
    assert "'GUI O''Neil'" in summary
    assert "'--sandbox' 'read-only'" in summary
    assert "'--add-dir' 'C:\\authorized context'" in summary
    assert "'do-not-print'" not in summary
    assert "sensitive native option" in summary
    assert "inherited process environment" in summary


def test_noninteractive_no_argument_call_shows_help_without_registry_mutation(tmp_path):
    parser = build_parser()
    output = StringIO()
    result = dispatch(parser.parse_args([]), parser, input_stream=StringIO(), output_stream=output)

    assert result == 2
    assert "usage: llmd" in output.getvalue()
    assert not (tmp_path / "index.sqlite").exists()


def test_no_argument_interactive_entry_can_exit_without_mutation(tmp_path):
    parser = build_parser()
    output = TTYOutput()
    service = DispatcherService(ContinuityService(tmp_path))
    before_guis = service.list_guis()
    before_events = service._rows("SELECT event_id, event_type FROM activity_events ORDER BY sequence")
    result = dispatch(parser.parse_args(["-H", str(tmp_path)]), parser, input_stream=TTYInput("\x03"), output_stream=output)

    assert result == 0
    assert "Select GUI Conversation" in output.getvalue()
    assert service.list_guis() == before_guis == []
    assert service._rows("SELECT event_id, event_type FROM activity_events ORDER BY sequence") == before_events == []


def test_selector_filters_case_insensitively_and_keeps_item_order():
    items = [
        {"name": "AgentNew", "activity": "2026-11-19T10:00:00Z"},
        {"name": "AgentOld", "activity": "2026-11-18T10:00:00Z"},
        {"name": "Other", "activity": None},
    ]
    assert [item["name"] for item in filter_items(items, "agent")] == ["AgentNew", "AgentOld"]
    actions = TTYInput("a\r")
    output = StringIO()
    action, selected = select_item(items, title="test", render_line=lambda item: item["name"],
                                   input_stream=actions, output_stream=output)
    assert action == "selected"
    assert selected["name"] == "AgentNew"


def test_timestamp_format_is_consistent_and_unknown_is_not_invented():
    assert format_timestamp(None) == "—"
    assert format_timestamp("bad timestamp") == "—"
    formatted = format_timestamp(datetime(2026, 11, 19, 19, 18, tzinfo=UTC).isoformat())
    assert len(formatted) == 16
    assert formatted[4] == "-" and formatted[10] == " "


def test_console_entry_points_are_aliases_and_flags_work_after_subcommand():
    module_dir = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((module_dir / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = metadata["project"]["scripts"]
    assert scripts["llmd"] == scripts["llm-dispatcher"] == "agent_continuity.dispatcher_cli:main"
    args = build_parser().parse_args(["open", "-g", "AgentImprovement", "-k", "4", "-t", "windows-terminal", "-w", "2", "-j"])
    assert args.json_output is True
    assert args.panes_per_tab == 4
    assert args.window == "2"


def test_public_help_hides_internal_pane_run_but_parser_keeps_it_callable():
    parser = build_parser()
    help_text = parser.format_help()
    assert "pane-run" not in help_text
    assert "Primary: start, continue, switch, review, return, save, restore, list, open, history." in help_text
    assert "Recovery and diagnostics" in help_text
    args = parser.parse_args(["pane-run", "-s", "slot-example"])
    assert args.command == "pane-run"
    assert args.slot_id == "slot-example"
    assert "--history-count" in parser._subparsers._group_actions[0].choices["list"].format_help()
    assert "--new" in parser._subparsers._group_actions[0].choices["start"].format_help()


def test_action_default_flags_resolve_and_reject_contradictions_before_registry_io(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["-H", str(tmp_path), "gui", "add", "-n", "G"])
    assert args.apply is False
    output = StringIO()
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=output) == 0
    assert DispatcherService(home_dir=tmp_path).list_guis()[0]["alias"] == "G"
    args = parser.parse_args(["-H", str(tmp_path), "slot", "create", "-g", "G", "-n", "A"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=tmp_path).get_slot(gui="G", name="A")["name"] == "A"

    second = tmp_path / "second"
    args = parser.parse_args(["-H", str(second), "gui", "add", "-n", "G", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=second).list_guis() == []

    third = tmp_path / "third"
    args = parser.parse_args(["-H", str(third), "gui", "add", "-n", "G", "-a", "-d"])
    with pytest.raises(Exception, match="Choose either --dry-run or --apply"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    assert not third.exists()


def test_continue_executes_by_default_and_dry_run_is_pure(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "A", provider="codex", session_id="native")
    calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: calls.append("run") or 0)
    parser = build_parser()
    assert dispatch(parser.parse_args(["-H", str(home), "continue", "-g", "G", "-n", "A"]), parser,
                    input_stream=StringIO(), output_stream=StringIO()) == 0
    assert calls == ["run"]
    calls.clear()
    assert dispatch(parser.parse_args(["-H", str(home), "continue", "-g", "G", "-n", "A", "-d"]), parser,
                    input_stream=StringIO(), output_stream=StringIO()) == 0
    assert calls == []


def test_default_launch_emits_early_redacted_progress_to_stderr_only(tmp_path, monkeypatch, capsys):
    import time

    home = tmp_path / "registry"
    DispatcherService(home_dir=home).register("G", "A", provider="codex", session_id="native")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)
    parser = build_parser()
    started = time.monotonic()
    assert dispatch(parser.parse_args(["-H", str(home), "continue", "-g", "G", "-n", "A"]), parser,
                    input_stream=StringIO(), output_stream=StringIO()) == 0
    elapsed = time.monotonic() - started
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("LLMD startup +")
    assert "registry synchronization" in captured.err
    assert "password" not in captured.err.casefold()
    assert elapsed < 5.0


def test_active_restoration_reservation_blocks_before_any_provider_process(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import _run_pane
    from agent_continuity.workspace_ownership import RestorationReservationStore

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("G", "A", provider="codex", session_id="native-session")
    slot = dispatcher.get_slot(gui="G", name="A")
    reservation = RestorationReservationStore(home).create_reservation(
        checkpoint_id="checkpoint-1", queue_entry_id="queue-1", attempt=1,
        slot_id=slot["slot_id"], provider="codex", native_session_id="native-session",
        environment_id=slot["current"]["environment_id"], operator_id="test",
    )
    provider_calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process",
                        lambda *args, **kwargs: provider_calls.append((args, kwargs)))
    with pytest.raises(ContinuityError, match="active restoration reservation"):
        _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                  input_stream=StringIO(), output_stream=StringIO())
    assert provider_calls == []
    assert RestorationReservationStore(home).get_reservation(reservation.reservation_id).state == "reserved"


def test_post_consumption_provider_spawn_failure_preserves_reservation_uncertainty(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import _run_pane
    from agent_continuity.workspace_ownership import RestorationReservationStore

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("G", "A", provider="codex", session_id="native-session")
    slot = dispatcher.get_slot(gui="G", name="A")
    identity = slot["current"]
    store = RestorationReservationStore(home)
    reservation = store.create_reservation(
        checkpoint_id="checkpoint-2", queue_entry_id="queue-2", attempt=1,
        slot_id=slot["slot_id"], provider="codex", native_session_id="native-session",
        environment_id=identity["environment_id"], operator_id="test",
    )
    launch_id, pane_id = "launch-test", "pane-test"
    reservation = store.bind_launch(reservation.reservation_id, launch_id=launch_id, pane_id=pane_id)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_reserved_provider_process",
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("guarded spawn failure")))
    with pytest.raises(ContinuityError, match="Failed to launch codex"):
        _run_pane(
            dispatcher, slot_id=slot["slot_id"], launch_id=None,
            input_stream=StringIO(), output_stream=StringIO(),
            expected_session_identity=("codex", identity["environment_id"], "native-session"),
            reservation_id=reservation.reservation_id, reservation_token=reservation.reservation_token,
            checkpoint_id=reservation.checkpoint_id, queue_entry_id=reservation.queue_entry_id,
            attempt=reservation.attempt, reservation_launch_id=launch_id, pane_id=pane_id,
        )
    assert store.get_reservation(reservation.reservation_id).state == "ambiguous"


def test_blocking_provider_progress_is_periodic_and_does_not_echo_argv(monkeypatch, capsys):
    import subprocess
    import time

    from agent_continuity import dispatcher_cli

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", lambda *a, **k: (time.sleep(0.035) or subprocess.CompletedProcess(a[0], 0)))
    enabled = dispatcher_cli._STARTUP_PROGRESS.set(True)
    started = dispatcher_cli._STARTUP_STARTED.set(time.monotonic())
    try:
        result = dispatcher_cli._run_provider_with_progress(
            ["codex", "--token", "private-value"], label="fake bootstrap", progress_interval=0.005
        )
    finally:
        dispatcher_cli._STARTUP_STARTED.reset(started)
        dispatcher_cli._STARTUP_PROGRESS.reset(enabled)
    assert result.returncode == 0
    captured = capsys.readouterr()
    assert "fake bootstrap still running" in captured.err
    assert "private-value" not in captured.err


def test_new_conversation_dry_run_never_bootstraps(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    parser = build_parser()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: pytest.fail("bootstrap must not run"))
    args = parser.parse_args(["-H", str(home), "start", "G", "A", "-p", "codex", "-N", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=home).list_guis() == []


def test_new_provider_switch_keeps_explicit_authorization_while_reuse_executes_by_default(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "A", provider="codex", session_id="codex-id")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "switch", "-g", "G", "-n", "A", "-p", "agy", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert service.get_slot(gui="G", name="A")["history"][-1]["native_session_id"] == "codex-id"
    assert service.list_pending_launches(gui="G") == []

    calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: calls.append(k) or 0)
    args = parser.parse_args(["-H", str(home), "switch", "-g", "G", "-n", "A", "-p", "codex", "-r"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert calls


def test_provider_switch_executes_by_default_and_preserves_prior_association(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "A", provider="codex", session_id="codex-original")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args(["-H", str(home), "switch", "-g", "G", "-n", "A", "-p", "agy"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    slot = service.get_slot(gui="G", name="A")
    pending = service.list_pending_launches(gui="G")
    assert [row["native_session_id"] for row in slot["history"]] == ["codex-original"]
    assert len(pending) == 1 and pending[0]["provider"] == "agy"
    assert launches == [pending[0]["launch_id"]]


def test_first_reviewer_session_initializes_by_default(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "Implementer", provider="codex", session_id="implementation")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args([
        "-H", str(home), "review", "-g", "G", "-n", "Implementer", "-R", "Review",
        "-p", "agy",
    ])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    original = service.get_slot(gui="G", name="Implementer")
    reviewer = service.get_slot(gui="G", name="Review")
    pending = service.list_pending_launches(gui="G")
    assert original["state"] == "active" and original["current"]["native_session_id"] == "implementation"
    assert reviewer["current"] is None and reviewer["state"] == "active"
    assert len(pending) == 1 and launches == [pending[0]["launch_id"]]
    assert service.open_review_cycle(slot_id=original["slot_id"])["status"] == "pending"


def test_review_new_flag_replaces_selected_reviewer_without_apply(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "Implementer", provider="codex", session_id="implementation")
    service.register("G", "Review", provider="agy", session_id="review-original")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args([
        "-H", str(home), "review", "-g", "G", "-n", "Implementer", "-R", "Review",
        "-p", "agy", "-N",
    ])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    reviewer = service.get_slot(gui="G", name="Review")
    pending = service.list_pending_launches(gui="G")
    assert [row["native_session_id"] for row in reviewer["history"]] == ["review-original"]
    assert len(pending) == 1 and pending[0]["provider"] == "agy"
    assert launches == [pending[0]["launch_id"]]


def test_start_first_session_concurrency_reserves_only_one_pending_launch(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from agent_continuity.errors import ContinuityError

    home = tmp_path / "registry"
    parser = build_parser()
    barrier = Barrier(2)
    launches = []

    def synchronized_preview(*args, **kwargs):
        barrier.wait(timeout=3)
        return {"environment": {"id": "local"}}

    monkeypatch.setattr("agent_continuity.dispatcher_cli._new_launch_preview", synchronized_preview)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)

    def start_once():
        args = parser.parse_args(["-H", str(home), "start", "G", "A", "-p", "codex"])
        try:
            return dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
        except ContinuityError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start_once(), range(2)))

    pending = DispatcherService(home_dir=home).list_pending_launches(gui="G")
    assert results.count(0) == 1 and results.count("rejected") == 1
    assert len(pending) == 1 and launches == [pending[0]["launch_id"]]


def test_last_resume_aliases_are_compatible_and_read_only_by_default():
    parser = build_parser()
    default = parser.parse_args(["last"])
    dry = parser.parse_args(["last", "-a"])
    resume = parser.parse_args(["last", "-r"])
    from agent_continuity.dispatcher_cli import _resolve_execution_mode
    _resolve_execution_mode(default)
    _resolve_execution_mode(dry)
    _resolve_execution_mode(resume)
    assert default.apply is False
    assert dry.apply is resume.apply is True


def test_open_creates_pane_specs_and_delegates_layout_and_launch(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="a-1", apply=True)

    @dataclass(frozen=True)
    class PaneSpec:
        title: str
        argv: tuple[str, ...]
        cwd: str | None = None

    class Backend:
        def preview(self, plan):
            return {"tab_count": len(plan["tabs"]), "titles": [tab["title"] for tab in plan["tabs"]]}

        def launch(self, plan):
            return {"launched": True}

    def group_panes(panes, *, panes_per_tab, target_window):
        return {"tabs": [{"title": pane.title, "panes": [pane]} for pane in panes],
                "panes_per_tab": panes_per_tab, "target_window": target_window}

    monkeypatch.setitem(sys.modules, "terminal_launcher", types.SimpleNamespace(
        PaneSpec=PaneSpec, WindowsTerminalBackend=Backend, group_panes=group_panes
    ))
    result = _open(dispatcher, Namespace(gui="AgentImprovement", terminal="windows-terminal",
                                         panes_per_tab=2, window="window-2", apply=True))

    assert result["preview"]["tab_count"] == 1
    assert result["preview"]["titles"] == ["AgentPerf"]
    assert result["launch"] == {"launched": True}
    pane_argv = result["request"]["panes"][0]["argv"]
    assert pane_argv[:4] == ["llmd", "pane-run", "--slot-id", dispatcher.list_slots(gui="AgentImprovement")[0]["slot_id"]]
    assert "--expected-provider" in pane_argv
    assert "--expected-environment" in pane_argv
    assert "--expected-session-id" in pane_argv
    assert UUID(pane_argv[pane_argv.index("-T") + 1])
    assert result["request"]["panes"][0]["provider_argv"] == ["agy", "--conversation", "a-1"]


def test_open_assigns_distinct_launcher_contexts_without_reusing_profile_terminal_id(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("GUI", apply=True)
    for name, session in (("One", "session-one"), ("Two", "session-two")):
        dispatcher.create_slot(gui="GUI", name=name, apply=True)
        dispatcher.attach_session(gui="GUI", name=name, provider="codex", session_id=session, apply=True)
    parent_terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", parent_terminal_id)

    @dataclass(frozen=True)
    class PaneSpec:
        title: str
        argv: tuple[str, ...]
        cwd: str | None = None

    class Backend:
        def preview(self, plan):
            return {"tab_count": len(plan["tabs"])}

        def launch(self, plan):
            return {"launched": True}

    def group_panes(panes, *, panes_per_tab, target_window):
        return {"tabs": [{"title": pane.title, "panes": [pane]} for pane in panes]}

    monkeypatch.setitem(sys.modules, "terminal_launcher", types.SimpleNamespace(
        PaneSpec=PaneSpec, WindowsTerminalBackend=Backend, group_panes=group_panes
    ))
    result = _open(dispatcher, Namespace(gui="GUI", terminal="windows-terminal", panes_per_tab=2,
                                         window=None, apply=True))

    pane_argv = [pane["argv"] for pane in result["request"]["panes"]]
    context_ids = [argv[argv.index("-T") + 1] for argv in pane_argv]
    assert len(context_ids) == 2
    assert len(set(context_ids)) == 2
    assert parent_terminal_id not in context_ids
    assert all(UUID(context_id) for context_id in context_ids)


def test_pane_run_accepts_launcher_owned_terminal_context():
    context_id = str(uuid4())
    args = build_parser().parse_args(["pane-run", "-s", "slot-example", "-T", context_id])

    assert args.launcher_terminal_context == context_id


def test_open_without_terminal_library_returns_pending_integration_preview(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("Empty", apply=True)
    import_fn = builtins.__import__

    def import_without_terminal(name, *args, **kwargs):
        if name == "terminal_launcher":
            raise ModuleNotFoundError("No module named 'terminal_launcher'", name="terminal_launcher")
        return import_fn(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_terminal)
    result = _open(dispatcher, Namespace(gui="Empty", terminal="windows-terminal", panes_per_tab=2, window=None, apply=False))
    assert result["terminal_launcher_available"] is False
    assert result["request"]["panes"] == []


def test_open_does_not_hide_internal_terminal_library_import_errors(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("Empty", apply=True)
    import_fn = builtins.__import__

    def import_with_broken_terminal_submodule(name, *args, **kwargs):
        if name == "terminal_launcher":
            raise ModuleNotFoundError("missing terminal_launcher.backend", name="terminal_launcher.backend")
        return import_fn(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_broken_terminal_submodule)
    with pytest.raises(ModuleNotFoundError, match="terminal_launcher.backend"):
        _open(dispatcher, Namespace(gui="Empty", terminal="windows-terminal", panes_per_tab=2, window=None, apply=False))


def test_profile_cli_create_assign_and_launch_preview_are_scoped(tmp_path):
    home = tmp_path / "registry"
    parser = build_parser()

    def invoke(argv):
        output = StringIO()
        result = dispatch(parser.parse_args(["-H", str(home), *argv]), parser,
                          input_stream=StringIO(), output_stream=output)
        return result, output.getvalue()

    code, _ = invoke(["gui", "add", "-n", "GUI"])
    assert code == 0
    code, output = invoke(["profile", "create", "safe", "-p", "codex", "--runtime", "windows",
                           "-C", str(tmp_path), "-s", 'sandbox="workspace-write"', "-s", 'model="gpt-test"'])
    assert code == 0
    assert "safe" in output
    code, _ = invoke(["slot", "create", "-g", "GUI", "-n", "Agent"])
    assert code == 0
    code, _ = invoke(["profile", "assign", "-g", "GUI", "-n", "Agent", "-P", "safe"])
    assert code == 0

    code, output = invoke(["start", "GUI", "Agent", "-p", "codex", "-d", "-j"])
    assert code == 0
    result = json.loads(output)
    assert result["launch_preview"]["profile"]["name"] == "safe"
    assert result["launch_preview"]["cwd"] == str(tmp_path)
    assert "--sandbox" in result["launch_preview"]["interactive_resume_argv_template"]
    assert "workspace-write" in result["launch_preview"]["interactive_resume_argv_template"]
    assert not DispatcherService(home_dir=home).get_slot(gui="GUI", name="Agent")["history"]


def test_invocation_settings_override_profile_without_cross_launch_persistence(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_profile(name="safe", provider="codex", settings={"sandbox": "workspace-write"})
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.assign_profile(gui="GUI", agent="Agent", profile="safe", apply=True)
    parser = build_parser()
    output = StringIO()
    result = dispatch(parser.parse_args(["-H", str(home), "start", "GUI", "Agent", "-p", "codex",
                                        "-d", "--", "--sandbox", "read-only"]),
                     parser, input_stream=StringIO(), output_stream=output)
    assert result == 0
    assert '"sandbox": "read-only"' in output.getvalue()
    assert '"profile": {' in output.getvalue()
    assert dispatcher.get_profile("safe")["settings"]["sandbox"] == "workspace-write"


def test_workflow_type_cli_is_default_apply_and_json_lists_identity_metadata(tmp_path):
    home = tmp_path / "registry"
    parser = build_parser()
    output = StringIO()
    created = dispatch(parser.parse_args(["-H", str(home), "gui", "add", "-n", "GUI"]), parser,
                       input_stream=StringIO(), output_stream=output)
    assert created == 0
    dispatch(parser.parse_args(["-H", str(home), "slot", "create", "-g", "GUI", "-n", "Agent"]), parser,
             input_stream=StringIO(), output_stream=StringIO())
    result = dispatch(parser.parse_args(["-H", str(home), "workflow-type", "GUI", "Agent", "handoff"]),
                      parser, input_stream=StringIO(), output_stream=StringIO())
    assert result == 0

    output = StringIO()
    result = dispatch(parser.parse_args(["-H", str(home), "list", "-g", "GUI", "-j"]), parser,
                      input_stream=StringIO(), output_stream=output)
    assert result == 0
    slot = json.loads(output.getvalue())["slots"][0]
    assert slot["workflow_type"] == "handoff"
    assert slot["agent_number"] == 1


def test_profile_no_profile_bypasses_assignment_and_profile_dry_run_is_pure(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_profile(name="safe", provider="codex", settings={"sandbox": "workspace-write"})
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.assign_profile(gui="GUI", agent="Agent", profile="safe", apply=True)
    parser = build_parser()
    output = StringIO()
    result = dispatch(parser.parse_args(["-H", str(home), "start", "GUI", "Agent", "-p", "codex",
                                        "-B", "-d", "-j"]), parser,
                      input_stream=StringIO(), output_stream=output)
    preview = json.loads(output.getvalue())["launch_preview"]
    assert result == 0
    assert preview["profile"]["source"] == "bypassed"
    assert "--sandbox" not in preview["interactive_resume_argv_template"]

    before = dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid")
    output = StringIO()
    result = dispatch(parser.parse_args(["-H", str(home), "profile", "create", "unused", "-p", "codex",
                                        "-d", "-s", "model=gpt-test", "-j"]), parser,
                      input_stream=StringIO(), output_stream=output)
    assert result == 0
    assert dispatcher.list_profiles() == [{**dispatcher.get_profile("safe")}]
    assert dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid") == before

def test_doctor_json_exposes_stable_identity_without_raw_profile_settings(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.register("GUI", "Agent")
    dispatcher.set_workflow_type(gui="GUI", agent="Agent", workflow_type="handoff")
    parser = build_parser()
    output = StringIO()
    result = dispatch(parser.parse_args(["-H", str(home), "doctor", "-j"]), parser,
                      input_stream=StringIO(), output_stream=output)
    assert result == 0
    report = json.loads(output.getvalue())
    agent = report["agents"][0]
    assert agent["gui_id"]
    assert agent["slot_id"]
    assert agent["agent_number"] == 1
    assert agent["workflow_type"] == "handoff"
    assert "profile_settings" not in agent


def test_continue_uses_assigned_profile_with_exact_session_and_provenance(tmp_path):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("GUI", "Agent", provider="codex", session_id="exact-native-session")
    dispatcher.create_profile(name="readonly", provider="codex", runtime_kind="windows",
                             settings={"sandbox": "read-only", "model": "gpt-test"})
    dispatcher.assign_profile(gui="GUI", agent="Agent", profile="readonly")
    parser = build_parser()
    output = StringIO()
    result = dispatch(parser.parse_args(["-H", str(home), "continue", "GUI", "Agent", "-d", "-j"]),
                      parser, input_stream=StringIO(), output_stream=output)
    assert result == 0
    preview = json.loads(output.getvalue())["launch_preview"]
    assert preview["selected_session"]["native_session_id"] == "exact-native-session"
    assert preview["profile"]["source"] == "assigned"
    assert preview["profile"]["revision"] == 1
    assert "--sandbox" in preview["argv"]
    assert preview["requested_settings"]["sandbox"] == "read-only"
    assert dispatcher.get_slot(gui="GUI", name="Agent")["history"][-1]["native_session_id"] == "exact-native-session"


def test_assigned_profile_reaches_fake_exact_session_handoff(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("GUI", "Agent", provider="codex", session_id="exact-native-session")
    dispatcher.create_profile(name="readonly", provider="codex",
                              settings={"sandbox": "read-only", "model": "gpt-test"})
    dispatcher.assign_profile(gui="GUI", agent="Agent", profile="readonly", apply=True)
    handoff = {}
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda *args, **kwargs: handoff.update(kwargs) or 0)
    parser = build_parser()
    result = dispatch(parser.parse_args(["-H", str(home), "continue", "GUI", "Agent", "-a"]), parser,
                      input_stream=StringIO(), output_stream=StringIO())

    assert result == 0
    assert handoff["native_args"] == ["--sandbox", "read-only", "--model", "gpt-test"]
    assert handoff["expected_session_identity"][2] == "exact-native-session"
    assert dispatcher.get_slot(gui="GUI", name="Agent")["history"][-1]["native_session_id"] == "exact-native-session"


def test_profile_mismatch_and_stale_cwd_fail_before_launch_or_registry_mutation(tmp_path, monkeypatch):
    from agent_continuity.errors import ContinuityError

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register("GUI", "Agent", provider="codex", session_id="exact")
    dispatcher.create_profile(name="agy-profile", provider="agy", settings={})
    stale_cwd = tmp_path / "profile-cwd"
    stale_cwd.mkdir()
    dispatcher.create_profile(name="cwd-profile", provider="codex", runtime_kind="windows", cwd=str(stale_cwd))
    dispatcher.assign_profile(gui="GUI", agent="Agent", profile="cwd-profile", apply=True)
    stale_cwd.rmdir()
    parser = build_parser()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda *a, **k: pytest.fail("profile validation must precede provider handoff"))

    before = dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid")
    with pytest.raises(ContinuityError, match="profile.*for agy"):
        dispatch(parser.parse_args(["-H", str(home), "continue", "GUI", "Agent", "-P", "agy-profile"]),
                 parser, input_stream=StringIO(), output_stream=StringIO())
    assert dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid") == before

    with pytest.raises(ContinuityError, match="does not exist"):
        dispatch(parser.parse_args(["-H", str(home), "continue", "GUI", "Agent", "-a"]),
                 parser, input_stream=StringIO(), output_stream=StringIO())
    assert dispatcher._rows("SELECT event_id FROM activity_events ORDER BY rowid") == before
