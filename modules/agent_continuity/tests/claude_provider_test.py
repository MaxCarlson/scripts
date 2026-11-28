from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from agent_continuity.cli import build_parser as build_agents_parser
from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import (
    _new_launch_preview,
    _return,
    _review,
    _run_pane,
    _switch_after_exit,
    _validated_native_args,
    build_parser,
)
from agent_continuity.errors import ContinuityError, ErrorCode
from agent_continuity.models import EnvironmentInfo, EventEnvelope, EventType, Provider
from agent_continuity.providers import ClaudeAdapter, default_adapters
from agent_continuity.runtime_discovery import ManagementState, MatchStatus, ProcessLiveness


def test_claude_is_registered_as_a_first_class_provider():
    assert Provider.CLAUDE.value == "claude"
    assert "claude" in default_adapters()
    assert isinstance(default_adapters()["claude"], ClaudeAdapter)
    parser = build_parser()
    start_parser = parser._subparsers._group_actions[0].choices["start"]
    provider_action = next(action for action in start_parser._actions if action.dest == "provider")
    assert "claude" in provider_action.choices
    for command_name in ("register", "attach", "switch", "continue", "review"):
        command = parser._subparsers._group_actions[0].choices[command_name]
        provider_action = next(action for action in command._actions if action.dest == "provider")
        assert "claude" in provider_action.choices

    legacy_parser = build_agents_parser()
    hooks_parser = legacy_parser._subparsers._group_actions[0].choices["hooks"]
    hooks_status = hooks_parser._subparsers._group_actions[0].choices["status"]
    hook_provider = next(action for action in hooks_status._actions if action.dest == "provider")
    assert hook_provider.choices == ["codex", "agy"]


def test_claude_exact_attachment_is_visible_in_dispatcher_history(tmp_path: Path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Reviewer", apply=True)
    session_id = str(uuid.uuid4())

    dispatcher.attach_session(gui="GUI", name="Reviewer", provider="claude",
                              session_id=session_id, apply=True)

    slot = dispatcher.get_slot(gui="GUI", name="Reviewer")
    assert slot["current"]["provider"] == "claude"
    assert slot["current"]["native_session_id"] == session_id
    assert slot["history"][-1]["native_session_id"] == session_id


def test_claude_exact_resume_and_new_session_argv(tmp_path: Path):
    adapter = ClaudeAdapter(which_fn=lambda _name: str(tmp_path / "claude.exe"), home_dir=tmp_path)
    session_id = str(uuid.uuid4())
    resumed = adapter.resolve_resume_command(session_id, cwd=str(tmp_path / "repo"))
    assert resumed.argv == ["claude", "--resume", session_id]
    assert resumed.cwd == str(tmp_path / "repo")
    assert "--continue" not in resumed.argv

    created = adapter.resolve_new_session_command(session_id, cwd=str(tmp_path / "repo"))
    assert created.argv == ["claude", "--session-id", session_id]
    assert created.supported
    with pytest.raises(ValueError, match="valid session UUID"):
        adapter.resolve_resume_command("ambiguous-session-name")


def test_claude_installation_discovery_handles_missing_and_fake_cli(tmp_path: Path, fake_provider_bin: Path):
    missing = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path).detect_installation()
    assert missing.installed is False
    assert missing.runnable is False
    installed = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"),
                              home_dir=tmp_path).detect_installation()
    assert installed.installed is True
    assert installed.runnable is True
    assert installed.version == "fake-provider 0.0"


def test_claude_does_not_claim_unqualified_broad_history_discovery():
    adapter = ClaudeAdapter(which_fn=lambda _name: None)
    assert adapter.get_capabilities().session_discovery is False
    assert adapter.discover_sessions(limit=3) == []


def test_claude_new_session_id_must_be_uuid_and_must_not_already_exist(tmp_path: Path):
    adapter = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path)
    with pytest.raises(ValueError, match="UUID"):
        adapter.resolve_new_session_command("not-a-uuid")
    session_id = str(uuid.uuid4())
    transcript = tmp_path / ".claude" / "projects" / "repo" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        adapter.resolve_new_session_command(session_id)


def test_claude_session_metadata_requires_a_nonempty_exact_transcript(tmp_path: Path):
    session_id = str(uuid.uuid4())
    adapter = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path)
    assert adapter.get_session_metadata(session_id) is None
    transcript = tmp_path / ".claude" / "projects" / "repo" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    metadata = adapter.get_session_metadata(session_id)
    assert metadata == {
        "provider": "claude",
        "native_session_id": session_id,
        "transcript_reference": str(transcript),
        "metadata_source": "claude_transcript_presence",
    }


@pytest.mark.parametrize("content", ["not-json\n", "\xff".encode("latin-1"), "", "[]\n"])
def test_claude_transcript_evidence_fails_closed_for_invalid_content(tmp_path: Path, content):
    session_id = str(uuid.uuid4())
    transcript = tmp_path / ".claude" / "projects" / "repo" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    adapter = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path)

    with pytest.raises(ContinuityError) as caught:
        adapter.get_session_metadata(session_id)

    assert caught.value.code == ErrorCode.METADATA_INACCESSIBLE
    assert "evidence" in caught.value.message.casefold()


def test_claude_transcript_evidence_rejects_contradictory_identity_and_duplicate_files(tmp_path: Path):
    session_id = str(uuid.uuid4())
    projects = tmp_path / ".claude" / "projects"
    transcript = projects / "repo" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"sessionId": str(uuid.uuid4())}) + "\n", encoding="utf-8")
    adapter = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path)

    with pytest.raises(ContinuityError, match="contradict"):
        adapter.get_session_metadata(session_id)

    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    duplicate = projects / "another-repo" / f"{session_id}.jsonl"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text('{"type":"user"}\n', encoding="utf-8")
    with pytest.raises(ContinuityError, match="multiple"):
        adapter.get_session_metadata(session_id)


def test_claude_transcript_scan_failure_is_not_reported_as_absence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import agent_continuity.providers.claude as claude_module

    projects = tmp_path / ".claude" / "projects"
    projects.mkdir(parents=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path)

    def denied_walk(_path, *, onerror):
        onerror(PermissionError("access denied"))
        return iter(())

    monkeypatch.setattr(claude_module.os, "walk", denied_walk)
    with pytest.raises(ContinuityError) as caught:
        adapter.get_session_metadata(str(uuid.uuid4()))
    assert caught.value.code == ErrorCode.METADATA_INACCESSIBLE
    assert "could not be fully scanned" in caught.value.message


def test_claude_matching_transcript_open_failure_is_not_reported_as_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    session_id = str(uuid.uuid4())
    transcript = tmp_path / ".claude" / "projects" / "repo" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    adapter = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path)
    original_open = Path.open

    def denied_open(path: Path, *args, **kwargs):
        if path == transcript:
            raise PermissionError("access denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    with pytest.raises(ContinuityError) as caught:
        adapter.get_session_metadata(session_id)
    assert caught.value.code == ErrorCode.METADATA_INACCESSIBLE
    assert "evidence is inaccessible" in caught.value.message


@pytest.mark.parametrize(
    "args",
    [
        ["--session-id", str(uuid.uuid4())],
        ["--resume", str(uuid.uuid4())],
        ["--fork-session"],
        ["--cloud"],
        ["--environment", "cloud-env"],
        ["--remote-control"],
        ["--teleport"],
        ["--tmux"],
        ["--from-pr", "123"],
        ["-w"],
        ["-wbranch"],
        ["-v"],
        ["--dangerously-skip-permissions"],
        ["--permission-mode", "bypassPermissions"],
        ["--continue"],
        ["-p"],
    ],
)
def test_claude_rejects_identity_execution_and_permission_bypass_options(args):
    with pytest.raises(ContinuityError):
        _validated_native_args("claude", args)


def test_claude_managed_native_options_and_permission_modes():
    args = ["--model", "sonnet", "--effort", "high", "--permission-mode", "plan",
            "--add-dir", "C:/shared"]
    assert _validated_native_args("claude", args) == args
    with pytest.raises(ContinuityError, match="permission"):
        _validated_native_args("claude", ["--permission-mode", "bypassPermissions"])
    with pytest.raises(ContinuityError, match="effort"):
        _validated_native_args("claude", ["--effort", "turbo"])


def test_claude_execution_modes_remain_forbidden_with_generic_unknown_authorization():
    with pytest.raises(ContinuityError):
        _validated_native_args("claude", ["--cloud"], allow_unknown=True)


@pytest.mark.parametrize("args", [
    ["--bare"], ["--dangerously-skip-permissions"], ["--allow-dangerously-skip-permissions"],
    ["--permission-mode=bypassPermissions"], ["--permission-control-extra"],
    ["--session-id=" + str(uuid.uuid4())],
    ["--resume=" + str(uuid.uuid4())], ["--tools", "Bash"], ["--setting-sources", "user"],
    ["-pvalue"], ["-w/other"], ["--", "--permission-mode", "dontAsk"],
])
def test_claude_native_unknown_authorization_never_waives_identity_or_permission_guards(args):
    with pytest.raises(ContinuityError):
        _validated_native_args("claude", args, allow_unknown=True)


@pytest.mark.parametrize(("departing", "selected", "expected"), [
    ("codex", "3", "claude"), ("agy", "1", "codex"), ("claude", "2", "agy"),
])
def test_exit_provider_picker_selects_all_three_native_providers(departing, selected, expected):
    from agent_continuity.dispatcher_cli import _choose_exit_switch_provider

    default = "agy" if departing == "codex" else "codex"
    provider, replay = _choose_exit_switch_provider(StringIO(selected + "\n"), StringIO(), default_provider=default)
    assert provider == expected
    assert replay.readline() == ""


@pytest.mark.parametrize(("departing", "destination"), [
    (left, right) for left in ("codex", "agy", "claude")
    for right in ("codex", "agy", "claude") if left != right
])
def test_post_exit_provider_picker_resumes_exact_session_across_all_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, departing: str, destination: str,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    target_id = str(uuid.uuid4()) if destination == "claude" else f"{destination}-exact"
    departing_id = str(uuid.uuid4()) if departing == "claude" else f"{departing}-current"
    dispatcher.attach_session(gui="GUI", name="Agent", provider=destination,
                              session_id=target_id, apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider=departing,
                              session_id=departing_id, apply=True)
    calls = []

    def fake_argv(_dispatcher, provider, session_id, **_kwargs):
        return [provider, session_id]

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", fake_argv)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    selected = {"codex": "1", "agy": "2", "claude": "3"}[destination]
    assert _run_pane(dispatcher, slot_id=dispatcher.get_slot(gui="GUI", name="Agent")["slot_id"],
                     launch_id=None, input_stream=StringIO(f"4\n{selected}\nr\n"),
                     output_stream=StringIO()) == 0

    assert calls == [[departing, departing_id], [destination, target_id]]
    current = dispatcher.get_slot(gui="GUI", name="Agent")["current"]
    assert (current["provider"], current["native_session_id"]) == (destination, target_id)


def test_claude_new_launch_preview_matches_session_id_and_managed_arg_order(
    tmp_path: Path, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    executable = str(fake_provider_bin / "claude.exe")
    dispatcher.continuity.adapters["claude"] = ClaudeAdapter(
        which_fn=lambda _name: executable, home_dir=tmp_path,
    )

    preview = _new_launch_preview(dispatcher, "claude", "local", str(tmp_path),
                                  ["--permission-mode", "plan", "--model", "sonnet"])

    assert preview["bootstrap_argv"] is None
    assert preview["interactive_resume_argv_template"] == [
        executable, "--session-id", "<UUID reserved when applied>",
        "--permission-mode", "plan", "--model", "sonnet",
    ]


def test_claude_start_uses_direct_uuid_session_and_resolves_only_with_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    observed = []
    created_ids = set()
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    def fake_run(argv, **kwargs):
        observed.append((argv, kwargs))
        created_ids.add(argv[2])
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    monkeypatch.setattr(adapter, "get_session_metadata", lambda session_id: {
        "provider": "claude", "native_session_id": session_id,
        "transcript_reference": "fake-transcript.jsonl", "metadata_source": "test_fixture",
    } if session_id in created_ids else None)

    result = _run_pane(dispatcher, slot_id=launch["details"]["slot_id"],
                       launch_id=launch["details"]["launch_id"], input_stream=StringIO("1\n"),
                       output_stream=StringIO(),
                       native_args=["--permission-mode", "plan", "--model", "sonnet"])

    assert result == 0
    argv = observed[0][0]
    assert argv[0] == str(fake_provider_bin / "claude.exe")
    assert argv[1] == "--session-id"
    session_id = argv[2]
    assert argv[3:] == ["--permission-mode", "plan", "--model", "sonnet"]
    assert str(uuid.UUID(session_id)) == session_id
    assert "--resume" not in argv and "--continue" not in argv
    current = dispatcher.get_slot(gui="GUI", name="Agent")["current"]
    assert current["provider"] == "claude"
    assert current["native_session_id"] == session_id
    assert dispatcher._row("SELECT 1 FROM dispatcher_pending_launches WHERE provider = 'claude' AND status = 'pending'") is None
    rebuilt = DispatcherService(home_dir=dispatcher.home_dir)
    assert rebuilt.get_slot(gui="GUI", name="Agent")["current"]["native_session_id"] == session_id


def test_claude_start_keeps_pending_when_transcript_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process",
                        lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    metadata_lookup = adapter.get_session_metadata
    monkeypatch.setattr(adapter, "get_session_metadata", lambda _session_id: None)

    result = _run_pane(dispatcher, slot_id=launch["details"]["slot_id"],
                       launch_id=launch["details"]["launch_id"], input_stream=StringIO(),
                       output_stream=StringIO())

    assert result == 1
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    assert slot["current"] is None
    launch_row = dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?",
                                 (launch["details"]["launch_id"],))
    pending = dispatcher._with_captured_bootstrap_id(launch_row)
    assert pending["status"] == "pending"
    reserved = pending["reserved_session_id"]
    assert str(uuid.UUID(reserved)) == reserved
    assert pending["failure_detail"] is None
    outcomes = dispatcher._rows(
        "SELECT payload_json FROM activity_events WHERE event_type = ? AND json_extract(payload_json, '$.launch_id') = ?",
        (EventType.DISPATCHER_PROCESS_OBSERVED.value, launch["details"]["launch_id"]),
    )
    assert any(json.loads(row["payload_json"]).get("outcome") == "normal_exit" for row in outcomes)

    transcript = tmp_path / ".claude" / "projects" / "repo" / f"{reserved}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    monkeypatch.setattr(adapter, "get_session_metadata", metadata_lookup)
    recovered = dispatcher.recover_captured_launch(gui="GUI", name="Agent", apply=True)
    assert recovered["status"] == "recovered"
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"]["native_session_id"] == reserved


def test_claude_pending_launch_recovers_only_after_exact_transcript_evidence(tmp_path: Path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    session_id = str(uuid.uuid4())
    adapter = ClaudeAdapter(which_fn=lambda _name: None, home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    dispatcher.record_process_observation(
        slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
        return_code=0, outcome="claude_session_id_reserved", native_session_id=session_id,
        detail="UUID reserved; provider has not yet confirmed session creation.",
    )
    adapter.get_session_metadata = lambda candidate: ({"native_session_id": candidate}
                                                       if candidate == session_id else None)

    preview = dispatcher.recover_captured_launch(gui="GUI", name="Agent", apply=False)
    assert preview["status"] == "preview"
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"] is None
    recovered = dispatcher.recover_captured_launch(gui="GUI", name="Agent", apply=True)
    assert recovered["status"] == "recovered"
    current = dispatcher.get_slot(gui="GUI", name="Agent")["current"]
    assert current["provider"] == "claude"
    assert current["native_session_id"] == session_id


def test_claude_native_allocation_is_durable_and_bound_to_effective_cwd(tmp_path: Path) -> None:
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", cwd=str(tmp_path), apply=True)
    launch_id = launch["details"]["launch_id"]
    slot_id = launch["details"]["slot_id"]

    session_id = dispatcher.reserve_claude_session_id(launch_id=launch_id, slot_id=slot_id, cwd=str(tmp_path))
    assert dispatcher.reserve_claude_session_id(
        launch_id=launch_id, slot_id=slot_id, cwd=str(tmp_path.resolve()),
    ) == session_id
    pending = dispatcher.get_pending_launch(launch_id)
    assert pending["reserved_session_id"] == session_id
    assert pending["reserved_effective_cwds"] == [str(tmp_path.resolve())]
    event = dispatcher._row(
        """SELECT payload_json FROM activity_events WHERE event_type = ?
           AND json_extract(payload_json, '$.launch_id') = ?
           AND json_extract(payload_json, '$.outcome') = 'claude_session_id_reserved'""",
        (EventType.DISPATCHER_PROCESS_OBSERVED.value, launch_id),
    )
    payload = json.loads(event["payload_json"])
    assert payload["allocation_mechanism"] == "deterministic_uuidv4_cli_flag"
    assert payload["provider_persistence_confirmed"] is False
    assert payload["provider_resumability_confirmed"] is False
    assert payload["effective_cwd"] == str(tmp_path.resolve())

    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    with pytest.raises(ContinuityError, match="effective-cwd evidence"):
        dispatcher.reserve_claude_session_id(launch_id=launch_id, slot_id=slot_id, cwd=str(other_cwd))


def test_interrupted_claude_initialization_keeps_uuid_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")

    def interrupt_launch(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", interrupt_launch)
    with pytest.raises(KeyboardInterrupt):
        _run_pane(dispatcher, slot_id=launch["details"]["slot_id"],
                  launch_id=launch["details"]["launch_id"], input_stream=StringIO(), output_stream=StringIO())

    pending = dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?",
                              (launch["details"]["launch_id"],))
    candidate = dispatcher._with_captured_bootstrap_id(pending)
    session_id = candidate["reserved_session_id"]
    assert candidate["status"] == "pending"
    assert str(uuid.UUID(session_id)) == session_id
    assert candidate["reserved_effective_cwds"] == [str(Path.cwd().resolve())]

    # A pending launch is one-shot. Recovery may inspect the same ID, but must
    # never spawn another interactive process for the same launch token.
    dispatcher = DispatcherService(home_dir=dispatcher.home_dir)
    dispatcher.continuity.adapters["claude"] = adapter
    restored = dispatcher._with_captured_bootstrap_id(
        dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?",
                        (launch["details"]["launch_id"],))
    )
    assert restored["reserved_session_id"] == session_id
    assert restored["claude_launch_attempted"] is True
    with pytest.raises(ContinuityError, match="already been attempted"):
        _run_pane(dispatcher, slot_id=launch["details"]["slot_id"],
                  launch_id=launch["details"]["launch_id"], input_stream=StringIO(), output_stream=StringIO())

    transcript = tmp_path / ".claude" / "projects" / "repo" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    recovered = dispatcher.recover_captured_launch(gui="GUI", name="Agent", apply=True)
    assert recovered["status"] == "recovered"
    current = dispatcher.get_slot(gui="GUI", name="Agent")["current"]
    assert current["native_session_id"] == session_id


def test_repeated_claude_pending_launch_cannot_spawn_a_second_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    calls = []

    def interrupted(argv, **_kwargs):
        calls.append(argv)
        raise KeyboardInterrupt

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", interrupted)
    for _ in range(2):
        try:
            _run_pane(dispatcher, slot_id=launch["details"]["slot_id"],
                      launch_id=launch["details"]["launch_id"], input_stream=StringIO(), output_stream=StringIO())
        except KeyboardInterrupt:
            pass
        except ContinuityError:
            pass

    assert len(calls) == 1
    pending = dispatcher._with_captured_bootstrap_id(
        dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?",
                        (launch["details"]["launch_id"],))
    )
    assert pending["status"] == "pending"
    assert calls[0][2] == pending["reserved_session_id"]


def test_concurrent_claude_pending_launch_has_single_claim_and_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    entered = Event()
    release = Event()
    calls = []

    def wait_in_provider(argv, **_kwargs):
        calls.append(argv)
        entered.set()
        release.wait(timeout=5)
        raise KeyboardInterrupt

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", wait_in_provider)
    errors = []

    def execute():
        try:
            _run_pane(dispatcher, slot_id=launch["details"]["slot_id"],
                      launch_id=launch["details"]["launch_id"], input_stream=StringIO(), output_stream=StringIO())
        except BaseException as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute)
        assert entered.wait(timeout=15)
        second = pool.submit(execute)
        second.result(timeout=15)
        release.set()
        first.result(timeout=15)

    assert len(calls) == 1
    assert any(isinstance(exc, ContinuityError) for exc in errors)
    pending = dispatcher._with_captured_bootstrap_id(
        dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?",
                        (launch["details"]["launch_id"],))
    )
    assert calls[0][2] == pending["reserved_session_id"]


def test_new_claude_wsl_start_is_rejected_before_slot_or_pending_launch(tmp_path: Path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    timestamp = "2026-11-27T00:00:00Z"
    environment = EnvironmentInfo("env_wsl_test", "wsl", "Ubuntu", "host", "test WSL", timestamp, timestamp)
    event = EventEnvelope(
        event_id="evt-wsl-test", event_schema_version=1, event_type=EventType.ENVIRONMENT_REGISTERED.value,
        provider=None, environment_id=environment.environment_id, native_session_id=None,
        source_timestamp=timestamp, observed_timestamp=timestamp, source_adapter_version="test",
        payload=environment.to_dict(),
    )
    dispatcher.continuity._emit_and_materialize([event])
    with pytest.raises(ContinuityError, match="New Claude sessions in WSL are not qualified"):
        dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude",
                                 environment_selector=environment.environment_id, apply=True)
    assert dispatcher.list_guis(active_only=False) == []
    assert dispatcher._row("SELECT 1 FROM dispatcher_pending_launches WHERE status = 'pending'") is None


def test_claude_can_be_new_provider_destination_and_preserves_old_session(tmp_path: Path,
                                                                           monkeypatch: pytest.MonkeyPatch,
                                                                           fake_provider_bin: Path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="codex-exact", apply=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    started = set()

    def fake_run(argv, **_kwargs):
        if Path(argv[0]).name.casefold() == "claude.exe":
            started.add(argv[2])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    monkeypatch.setattr(adapter, "get_session_metadata", lambda session_id: {"native_session_id": session_id}
                        if session_id in started else None)

    result = _switch_after_exit(dispatcher, dispatcher.get_slot(gui="GUI", name="Agent"), "claude",
                                input_stream=StringIO("y\n1\n"), output_stream=StringIO())

    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    assert result == 0
    assert slot["current"]["provider"] == "claude"
    assert slot["history"][0]["native_session_id"] == "codex-exact"
    assert slot["history"][-1]["native_session_id"] in started


def test_claude_reviewer_creation_and_return_round_trip_preserve_codex_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Original", apply=True)
    dispatcher.attach_session(gui="GUI", name="Original", provider="codex", session_id="original-exact", apply=True)
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    started = set()

    def fake_run(argv, **_kwargs):
        if Path(argv[0]).name.casefold() == "claude.exe":
            started.add(argv[2])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    monkeypatch.setattr(adapter, "get_session_metadata", lambda session_id: {"native_session_id": session_id}
                        if session_id in started else None)
    parser = build_parser()
    review_args = parser.parse_args(["-H", str(dispatcher.home_dir), "review", "-g", "GUI", "-n", "Original",
                                     "-R", "Reviewer", "-p", "claude"])
    review_args.apply = True

    assert _review(dispatcher, review_args, StringIO("1\n"), StringIO()) == 0
    slots = dispatcher.list_slots(gui="GUI", active_only=False)
    assert len(slots) == 2, [slot["name"] for slot in slots]
    reviewer = dispatcher.get_slot(gui="GUI", name="Reviewer")
    original = dispatcher.get_slot(gui="GUI", name="Original")
    reviewer_id = reviewer["current"]["native_session_id"]
    assert reviewer["current"]["provider"] == "claude"
    assert original["state"] == "inactive"
    assert original["current"]["native_session_id"] == "original-exact"
    assert dispatcher.active_review_cycle(slot_id=original["slot_id"])["reviewer_session_id"] == reviewer_id

    return_args = parser.parse_args(["-H", str(dispatcher.home_dir), "return", "-g", "GUI", "-n", "Original"])
    return_args.apply = True
    assert _return(dispatcher, return_args, StringIO("1\n"), StringIO()) == 0
    returned_original = dispatcher.get_slot(gui="GUI", name="Original")
    returned_reviewer = dispatcher.get_slot(gui="GUI", name="Reviewer")
    assert returned_original["state"] == "active"
    assert returned_original["current"]["provider"] == "codex"
    assert returned_original["current"]["native_session_id"] == "original-exact"
    assert returned_reviewer["state"] == "inactive"


def test_slot_wide_exclusion_blocks_concurrent_resume_attach_switch_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="hist-1", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="agy", session_id="curr-1", apply=True)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    monkeypatch.setattr(
        dispatcher,
        "observe_runtime_session",
        lambda *_args, **_kwargs: SimpleNamespace(
            management=ManagementState.MANAGED,
            process_liveness=ProcessLiveness.RUNNING,
            process_session_match=MatchStatus.EXACT,
        ),
    )

    entered = Event()
    release = Event()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-provider"])

    def wait_in_provider(*_args, **_kwargs):
        entered.set()
        release.wait(timeout=5)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", wait_in_provider)
    results: dict[str, object] = {}

    def run_primary():
        results["primary"] = _run_pane(
            dispatcher, slot_id=slot["slot_id"], launch_id=None,
            input_stream=StringIO("1\n"), output_stream=StringIO(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(run_primary)
        assert entered.wait(timeout=5)
        with pytest.raises(ContinuityError, match="active or launching session"):
            _run_pane(
                dispatcher, slot_id=slot["slot_id"], launch_id=None,
                input_stream=StringIO(), output_stream=StringIO(),
            )
        with pytest.raises(ContinuityError, match="active provider session"):
            dispatcher.attach_session(
                gui="GUI", name="Agent", provider="codex", session_id="hist-1", apply=True,
            )
        with pytest.raises(ContinuityError, match="active or launching session"):
            dispatcher.begin_launch(gui="GUI", name="Agent", provider="claude", apply=True)
        open_req = dispatcher.open_request(gui="GUI")
        assert open_req["panes"] == []
        assert open_req["unresolved"] == [{
            "slot_id": slot["slot_id"],
            "agent_name": "Agent",
            "reason": "slot or selected session is already in use",
        }]
        release.set()
        future.result(timeout=5)

    assert results["primary"] == 0


def test_live_claude_recovery_and_eventual_wrapper_exit_are_compatible_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_provider_bin: Path,
):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    slot_id = launch["details"]["slot_id"]
    launch_id = launch["details"]["launch_id"]
    adapter = ClaudeAdapter(which_fn=lambda _name: str(fake_provider_bin / "claude.exe"), home_dir=tmp_path)
    dispatcher.continuity.adapters["claude"] = adapter
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")

    entered = Event()
    release = Event()
    observed_uuid: list[str] = []

    def fake_run(argv, **_kwargs):
        observed_uuid.append(argv[2])
        entered.set()
        release.wait(timeout=15)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)

    def fake_observe(_provider, _env_id, session_id):
        if observed_uuid and session_id == observed_uuid[0]:
            return SimpleNamespace(
                process_session_match=SimpleNamespace(value="exact"),
                process_liveness=SimpleNamespace(value="running"),
                session_identity_state=SimpleNamespace(value="reserved"),
                process_availability=SimpleNamespace(value="complete"),
                identity_conflict=False,
                evidence_conflict=False,
            )
        return None

    monkeypatch.setattr(dispatcher, "observe_runtime_session", fake_observe)

    with ThreadPoolExecutor(max_workers=2) as pool:
        wrapper = pool.submit(
            _run_pane, dispatcher, slot_id=slot_id, launch_id=launch_id,
            input_stream=StringIO("1\n"), output_stream=StringIO(),
        )
        assert entered.wait(timeout=15)
        recovered = dispatcher.recover_captured_launch(gui="GUI", name="Agent", apply=True)
        assert recovered["status"] == "recovered"
        assert recovered["details"]["provenance"] == "claude_exact_runtime_process"
        assert recovered["details"]["association_state"] == "confirmed"
        assert recovered["details"]["identity_state"] == "reserved"
        assert recovered["details"]["resumability"] == "unverified"

        # Now write the transcript before wrapper exits cleanly.
        session_id = observed_uuid[0]
        transcript = tmp_path / ".claude" / "projects" / "repo" / f"{session_id}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        release.set()
        assert wrapper.result(timeout=15) == 0

    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    assert slot["current"]["native_session_id"] == session_id
    assert len(slot["history"]) == 1
    pending = dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
    assert pending["status"] == "resolved"


def test_interrupted_attach_metadata_completes_pending_launch_idempotently(tmp_path: Path):
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="claude", apply=True)
    slot_id = launch["details"]["slot_id"]
    launch_id = launch["details"]["launch_id"]
    session_id = str(uuid.uuid4())
    # Simulate activation already persisted before launch resolution event was written.
    dispatcher.continuity._emit_and_materialize([
        dispatcher._event(
            EventType.DISPATCHER_SESSION_ACTIVATED,
            environment_id=launch["details"]["environment_id"],
            provider="claude",
            session_id=session_id,
            payload={"slot_id": slot_id, "activation_id": "act-partial", "sequence": 1, "provenance": "partial"},
        )
    ])
    res = dispatcher.attach_session(
        gui="GUI", name="Agent", provider="claude", session_id=session_id,
        environment_selector=launch["details"]["environment_id"], launch_id=launch_id, apply=True,
    )
    assert res["applied"] is True
    pending = dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
    assert pending["status"] == "resolved"


def test_batch_runtime_discovery_uses_one_snapshot_and_avoids_lock_mislabeling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from agent_continuity.dispatcher import _mutation_lock, _session_lock_name
    from agent_continuity.dispatcher_cli import build_parser, dispatch
    from agent_continuity.runtime_discovery import RuntimeDiscovery

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    for idx in range(3):
        dispatcher.create_slot(gui="GUI", name=f"Agent{idx}", apply=True)
        dispatcher.attach_session(gui="GUI", name=f"Agent{idx}", provider="codex", session_id=f"sess-{idx}", apply=True)
    pending_launch = dispatcher.prepare_start(gui="GUI", name="PendingClaude", provider="claude", apply=True)
    reserved_id = str(uuid.uuid4())
    dispatcher.record_process_observation(
        slot_id=pending_launch["details"]["slot_id"],
        launch_id=pending_launch["details"]["launch_id"],
        return_code=0,
        outcome="claude_session_id_reserved",
        native_session_id=reserved_id,
    )

    snapshot_calls = 0

    def fake_capture_snapshot(self):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return SimpleNamespace(runtime_kind=self.runtime_kind, environment_id=self.environment_id,
                               captured_at=None, inventory=None)

    def fake_observe_many(self, keys, *, snapshot=None, **_kwargs):
        return tuple(
            SimpleNamespace(
                process_session_match=SimpleNamespace(value="not_observed"),
                process_liveness=SimpleNamespace(value="not_observed"),
                session_identity_state=SimpleNamespace(value="unknown"),
                process_availability=SimpleNamespace(value="complete"),
                identity_conflict=False,
                evidence_conflict=False,
            )
            for _ in keys
        )

    monkeypatch.setattr(RuntimeDiscovery, "capture_snapshot", fake_capture_snapshot)
    monkeypatch.setattr(RuntimeDiscovery, "observe_many", fake_observe_many)

    # Hold session lock for the pending Claude reserved UUID without a live process.
    lock_name = _session_lock_name("claude", pending_launch["details"]["environment_id"], reserved_id)
    with _mutation_lock(home, lock_name):
        parser = build_parser()
        json_out = StringIO()
        assert dispatch(parser.parse_args(["-H", str(home), "doctor", "-j"]), parser,
                        input_stream=StringIO(), output_stream=json_out) == 0
        assert snapshot_calls == 1
        doc = json.loads(json_out.getvalue())
        pending_agent = next(a for a in doc["agents"] if a["name"] == "PendingClaude")
        assert pending_agent["runtime"] == "IN USE"
        assert pending_agent["pending_destination"]["runtime_evidence"] == (
            "LLMD session lock contended; exact provider process not observed"
        )

        human_out = StringIO()
        assert dispatch(parser.parse_args(["-H", str(home), "list", "-g", "GUI"]), parser,
                        input_stream=StringIO(), output_stream=human_out) == 0
        assert snapshot_calls == 2
        assert "lock contended" in human_out.getvalue()
        assert "exact provider process observed" not in human_out.getvalue()


def test_partial_runtime_discovery_preserves_unknown_and_read_only_commands_create_no_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from agent_continuity.dispatcher_cli import build_parser, dispatch
    from agent_continuity.runtime_discovery import RuntimeDiscovery

    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="sess-partial", apply=True)

    monkeypatch.setattr(
        RuntimeDiscovery,
        "capture_snapshot",
        lambda self: SimpleNamespace(runtime_kind=self.runtime_kind, environment_id=self.environment_id,
                                     captured_at=None, inventory=None),
    )
    monkeypatch.setattr(
        RuntimeDiscovery,
        "observe_many",
        lambda self, keys, **_kw: tuple(
            SimpleNamespace(
                process_session_match=SimpleNamespace(value="not_observed"),
                process_liveness=SimpleNamespace(value="unknown"),
                session_identity_state=SimpleNamespace(value="unknown"),
                process_availability=SimpleNamespace(value="partial"),
                identity_conflict=False,
                evidence_conflict=False,
            )
            for _ in keys
        ),
    )

    before_locks = set(home.glob("*.lock"))
    parser = build_parser()
    doc_out = StringIO()
    assert dispatch(parser.parse_args(["-H", str(home), "doctor", "-j"]), parser,
                    input_stream=StringIO(), output_stream=doc_out) == 0
    doc = json.loads(doc_out.getvalue())
    assert doc["agents"][0]["runtime"] == "UNKNOWN"

    list_out = StringIO()
    assert dispatch(parser.parse_args(["-H", str(home), "list", "-g", "GUI", "-j"]), parser,
                    input_stream=StringIO(), output_stream=list_out) == 0
    listing = json.loads(list_out.getvalue())
    assert listing["slots"][0]["runtime_status"] == "UNKNOWN"

    assert dispatch(parser.parse_args(["-H", str(home), "open", "-g", "GUI", "-d", "-j"]), parser,
                    input_stream=StringIO(), output_stream=StringIO()) == 0
    assert set(home.glob("*.lock")) == before_locks
