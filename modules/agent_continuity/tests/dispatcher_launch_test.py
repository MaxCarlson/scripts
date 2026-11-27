from __future__ import annotations

import json
import subprocess
from io import StringIO
from types import SimpleNamespace

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import (
    _bootstrap_native_argv,
    _extract_bootstrap_session_id,
    _native_argv,
    _run_pane,
    build_parser,
)
from agent_continuity.errors import ContinuityError, ErrorCode
from agent_continuity.models import EnvironmentInfo, EventEnvelope, EventType
from agent_continuity.service import ContinuityService


def test_provider_process_guard_rejects_direct_provider_spawn():
    with pytest.raises(AssertionError, match="attempted to spawn provider agy"):
        subprocess.Popen(["agy.EXE", "--help"])


def test_provider_args_are_split_only_after_explicit_separator():
    args = build_parser().parse_args([
        "continue", "GUI", "AGENT", "-C", r"C:\Work Tree", "-a", "--",
        "--sandbox", "workspace-write", "--ask-for-approval", "on-request",
    ])
    assert args.gui_pos == "GUI"
    assert args.agent_pos == "AGENT"
    assert args.cwd == r"C:\Work Tree"
    assert args.apply is True
    assert args.native_args == ["--sandbox", "workspace-write", "--ask-for-approval", "on-request"]


def test_codex_resume_command_keeps_identity_and_inserts_native_args_before_session():
    from agent_continuity.providers.codex import CodexAdapter

    plan = CodexAdapter().resolve_resume_command(
        "session-exact", cwd=r"C:\Work Tree", environment_id="windows",
        runtime_kind="windows", native_args=["--sandbox", "workspace-write", "--ask-for-approval", "on-request"],
    )
    assert plan.argv == [
        "codex", "resume", "-C", r"C:\Work Tree", "--sandbox", "workspace-write",
        "--ask-for-approval", "on-request", "session-exact",
    ]


def test_agy_resume_command_keeps_exact_conversation_and_native_options():
    from agent_continuity.providers.agy import AgyAdapter

    plan = AgyAdapter().resolve_resume_command(
        "conversation-exact", cwd=r"C:\Work Tree", environment_id="windows",
        runtime_kind="windows", native_args=["--model", "gemini-test", "--sandbox"],
    )
    assert plan.argv == [
        "agy", "--conversation", "conversation-exact", "--model", "gemini-test", "--sandbox",
    ]


def test_native_args_reject_identity_execution_and_directory_overrides():
    from agent_continuity.dispatcher_cli import _validated_native_args

    for provider, args in (("codex", ["--last"]), ("codex", ["--cd", "other"]),
                           ("agy", ["--conversation", "other"]), ("agy", ["--print"]),
                           ("agy", ["--mode", "plan"]),
                           ("codex", ["--sandbox"])):
        with pytest.raises(ContinuityError):
            _validated_native_args(provider, args)

    assert _validated_native_args("agy", ["--add-dir", "other"]) == ["--add-dir", "other"]
    assert _validated_native_args("codex", ["--enable", "feature-a", "--enable", "feature-b"]) == [
        "--enable", "feature-a", "--enable", "feature-b",
    ]
    assert _validated_native_args("agy", ["--sandbox", "--effort", "high"]) == ["--sandbox", "--effort", "high"]


@pytest.mark.parametrize(
    ("provider", "args"),
    [
        ("codex", ["-s", "unsupported"]),
        ("codex", ["--sandbox", "unsupported"]),
        ("codex", ["-s=unsupported"]),
        ("codex", ["--sandbox=unsupported"]),
        ("codex", ["-a", "always"]),
        ("codex", ["--ask-for-approval", "always"]),
        ("codex", ["-a=always"]),
        ("codex", ["--ask-for-approval=always"]),
        ("agy", ["--effort", "turbo"]),
        ("agy", ["--effort=turbo"]),
        ("codex", ["-s", "workspace-write", "--sandbox", "read-only"]),
        ("codex", ["-a", "never", "--ask-for-approval", "on-request"]),
    ],
)
def test_native_args_validate_enumerated_values_and_alias_duplicates(provider, args):
    from agent_continuity.dispatcher_cli import _validated_native_args

    with pytest.raises(ContinuityError, match="Unsupported|may only be specified once"):
        _validated_native_args(provider, args)


@pytest.mark.parametrize(
    ("provider", "args", "expected"),
    [
        ("codex", ["-s", "workspace-write", "-a", "on-request"],
         ["-s", "workspace-write", "-a", "on-request"]),
        ("codex", ["-s=read-only", "--ask-for-approval=never"],
         ["-s", "read-only", "--ask-for-approval", "never"]),
        ("agy", ["--effort=xhigh"], ["--effort", "xhigh"]),
    ],
)
def test_native_args_accept_aliases_and_equals_forms_without_losing_option_spelling(provider, args, expected):
    from agent_continuity.dispatcher_cli import _validated_native_args

    assert _validated_native_args(provider, args) == expected


def test_new_and_existing_previews_report_final_agy_sandbox_and_codex_aliases(tmp_path):
    from agent_continuity.dispatcher_cli import _launch_preview, _new_launch_preview

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="agy", session_id="agy-exact", apply=True)
    existing = _launch_preview(dispatcher, "agy", "agy-exact", "local", None, ["--sandbox"])
    created = _new_launch_preview(dispatcher, "agy", "local", None, ["--sandbox"])
    codex = _new_launch_preview(dispatcher, "codex", "local", None,
                                ["-s=workspace-write", "-a", "never"])

    assert existing["permission_settings"]["requested"] == {"--sandbox": True}
    assert created["permission_settings"]["requested"] == {"--sandbox": True}
    assert codex["permission_settings"]["requested"] == {
        "--sandbox": ["workspace-write"], "--ask-for-approval": ["never"],
    }
    assert all(preview["permission_settings"]["verified_effective"] is None
               for preview in (existing, created, codex))


@pytest.mark.parametrize(
    "command_args",
    [
        ("start", "GUI", "Agent", "-p", "codex", "-N", "-a", "--", "--sandbox=invalid"),
        ("switch", "-g", "GUI", "-n", "Original", "-p", "agy", "-a", "--", "--effort=turbo"),
        ("review", "-g", "GUI", "-n", "Original", "-R", "Reviewer", "-p", "agy", "-N", "-a",
         "--", "--effort", "turbo"),
    ],
)
def test_invalid_native_values_prevent_new_launch_and_registry_mutation(tmp_path, monkeypatch, command_args):
    from agent_continuity.dispatcher_cli import build_parser, dispatch

    home = tmp_path / "registry"
    seed = DispatcherService(home_dir=home)
    if command_args[0] != "start":
        seed.create_gui("GUI", apply=True)
        seed.create_slot(gui="GUI", name="Original", apply=True)
        seed.attach_session(gui="GUI", name="Original", provider="codex", session_id="original-exact", apply=True)
    before_guis = seed.list_guis(active_only=False)
    before_slots = seed.list_slots(gui="GUI", active_only=False) if before_guis else []
    before_pending = seed.list_pending_launches(gui="GUI") if before_guis else []
    provider_calls = []

    def unexpected_provider_call(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("Invalid native arguments reached provider initialization.")

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", unexpected_provider_call)
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), *command_args])
    with pytest.raises(ContinuityError, match="Unsupported"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())

    after = DispatcherService(home_dir=home)
    assert after.list_guis(active_only=False) == before_guis
    assert (after.list_slots(gui="GUI", active_only=False) if before_guis else []) == before_slots
    assert (after.list_pending_launches(gui="GUI") if before_guis else []) == before_pending
    assert provider_calls == []


def test_continue_preview_is_pure_reports_requested_settings_and_worktree_change(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import build_parser, dispatch

    original_cwd = tmp_path / "original repo"
    requested_cwd = tmp_path / "requested repo"
    original_cwd.mkdir()
    requested_cwd.mkdir()
    (original_cwd / ".git").mkdir()
    (requested_cwd / ".git").mkdir()
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="session-exact",
                              cwd=str(original_cwd), apply=True)
    before = dispatcher.get_slot(gui="GUI", name="Agent")
    process_calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", lambda *a, **k: process_calls.append((a, k)))
    parser = build_parser()
    args = parser.parse_args([
        "-H", str(dispatcher.home_dir), "continue", "GUI", "Agent", "-C", str(requested_cwd), "-j", "-d", "--",
        "--sandbox", "workspace-write", "--ask-for-approval", "on-request",
    ])
    output = StringIO()
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=output) == 0
    preview = json.loads(output.getvalue())["launch_preview"]
    assert preview["selected_session"]["native_session_id"] == "session-exact"
    assert preview["cwd"] == str(requested_cwd)
    assert preview["repository_context_changed"] is True
    assert preview["permission_settings"] == {
        "requested": {"--sandbox": ["workspace-write"], "--ask-for-approval": ["on-request"]},
        "verified_effective": None,
        "verification": "Provider enforcement is not observed by a launch preview.",
    }
    assert process_calls == []
    after = dispatcher.get_slot(gui="GUI", name="Agent")
    assert before["current"] == after["current"]
    native = dispatcher.materializer.get_session("codex", before["current"]["environment_id"], "session-exact")
    assert native.cwd_native == str(original_cwd)


def test_continue_cwd_override_resumes_exact_session_without_overwriting_provenance(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import build_parser, dispatch

    original_cwd = tmp_path / "original"
    override_cwd = tmp_path / "override with spaces"
    original_cwd.mkdir()
    override_cwd.mkdir()
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="native-exact",
                              cwd=str(original_cwd), apply=True)
    executed = []

    def fake_run(argv, **kwargs):
        executed.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    parser = build_parser()
    args = parser.parse_args([
        "-H", str(dispatcher.home_dir), "continue", "GUI", "Agent", "-C", str(override_cwd), "-a", "--",
        "--sandbox", "workspace-write", "--ask-for-approval", "on-request",
    ])
    assert dispatch(args, parser, input_stream=StringIO("1\n"), output_stream=StringIO()) == 0
    assert len(executed) == 1
    argv, options = executed[0]
    assert argv[argv.index("-C") + 1] == str(override_cwd)
    assert argv[-1] == "native-exact"
    assert options["cwd"] == str(override_cwd)
    current = dispatcher.get_slot(gui="GUI", name="Agent")["current"]
    native = dispatcher.materializer.get_session("codex", current["environment_id"], "native-exact")
    assert native.cwd_native == str(original_cwd)


def test_invalid_native_options_fail_before_lifecycle_or_process_change(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import build_parser, dispatch

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Agent", provider="codex", session_id="native")
    before = dispatcher.get_slot(gui="GUI", name="Agent")
    provider_calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", lambda *a, **k: provider_calls.append(a))
    parser = build_parser()
    args = parser.parse_args(["-H", str(dispatcher.home_dir), "continue", "GUI", "Agent", "-a", "--", "--last"])
    with pytest.raises(ContinuityError, match="LLMD-conflicting"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"] == before["current"]
    assert provider_calls == []


def test_open_rejects_provider_options_before_terminal_plan_submission(tmp_path):
    from agent_continuity.dispatcher_cli import build_parser, dispatch

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    parser = build_parser()
    args = parser.parse_args(["-H", str(dispatcher.home_dir), "open", "-g", "GUI", "--", "--sandbox"])
    with pytest.raises(ContinuityError, match="not supported by `llmd open`"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())


def test_wsl_cwd_override_validation_uses_recorded_distribution_and_argv(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import _validate_cwd_override

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="agy", session_id="wsl-native",
                              environment_selector="wsl:Ubuntu", cwd="/home/test/project", apply=True)
    environment_id = dispatcher.get_slot(gui="GUI", name="Agent")["current"]["environment_id"]
    captured = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which", lambda _name: "wsl.exe")
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: captured.append((argv, kwargs)) or SimpleNamespace(returncode=0))
    _validate_cwd_override(dispatcher, environment_id, "/mnt/c/worktree")
    assert captured[0][0] == ["wsl.exe", "--distribution", "Ubuntu", "--exec", "test", "-d", "/mnt/c/worktree"]
    assert captured[0][1]["capture_output"] is True


def test_start_switch_review_and_return_forward_provider_argv_by_destination(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import build_parser, dispatch

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Implementer", provider="codex", session_id="codex-original")
    dispatcher.attach_session(gui="GUI", name="Implementer", provider="agy", session_id="agy-prior", apply=True)
    dispatcher.attach_session(gui="GUI", name="Implementer", provider="codex", session_id="codex-original", apply=True)
    dispatcher.create_slot(gui="GUI", name="Reviewer", apply=True)
    dispatcher.attach_session(gui="GUI", name="Reviewer", provider="codex", session_id="codex-reviewer", apply=True)
    dispatcher.set_slot_state(gui="GUI", name="Reviewer", state="inactive", apply=True)
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda _dispatcher, **kwargs: launches.append(kwargs) or 0)
    parser = build_parser()

    def invoke(*tokens):
        args = parser.parse_args(["-H", str(dispatcher.home_dir), *tokens])
        return dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())

    assert invoke("start", "-g", "GUI", "-n", "Implementer", "-p", "codex", "-a", "--",
                  "--sandbox", "workspace-write") == 0
    assert launches[-1]["native_args"] == ["--sandbox", "workspace-write"]

    assert invoke("switch", "-g", "GUI", "-n", "Implementer", "-p", "agy", "-r", "-a", "--",
                  "--sandbox") == 0
    assert launches[-1]["native_args"] == ["--sandbox"]
    assert dispatcher.get_slot(gui="GUI", name="Implementer")["current"]["native_session_id"] == "agy-prior"

    assert invoke("review", "-g", "GUI", "-n", "Implementer", "-R", "Reviewer", "-p", "codex", "-a", "--",
                  "--sandbox", "workspace-write") == 0
    assert launches[-1]["native_args"] == ["--sandbox", "workspace-write"]
    assert dispatcher.get_slot(gui="GUI", name="Reviewer")["state"] == "active"

    assert invoke("return", "-g", "GUI", "-n", "Implementer", "-a", "--", "--sandbox") == 0
    assert launches[-1]["native_args"] == ["--sandbox"]
    assert dispatcher.get_slot(gui="GUI", name="Implementer")["current"]["native_session_id"] == "agy-prior"


class FakeAdapter:
    def __init__(self, executable="codex.exe"):
        self.executable = executable

    def detect_installation(self):
        return SimpleNamespace(installed=True, runnable=True, executable_path=self.executable, detail="")

    def resolve_resume_command(self, session_id, *, cwd, environment_id, runtime_kind, native_args=()):
        argv = ["codex", "resume"]
        if cwd:
            argv.extend(["-C", cwd])
        argv.extend(native_args)
        argv.append(session_id)
        return SimpleNamespace(argv=argv)


def _dispatcher_with_session(tmp_path, *, provider="codex", session_id="session-1", cwd=r"C:\Project With Spaces"):
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider=provider,
                              session_id=session_id, cwd=cwd, apply=True)
    return dispatcher, dispatcher.list_slots(gui="AgentImprovement")[0]


def test_windows_resume_uses_provider_adapter_arguments_and_executable(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    dispatcher.continuity.adapters["codex"] = FakeAdapter(r"C:\Program Files\Codex\codex.exe")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")

    argv = _native_argv(dispatcher, "codex", "session-1", environment_id=slot["current_environment_id"],
                        cwd=r"C:\Project With Spaces",
                        native_args=["--sandbox", "workspace-write", "--ask-for-approval", "on-request"])

    assert argv == [r"C:\Program Files\Codex\codex.exe", "resume", "-C", r"C:\Project With Spaces",
                    "--sandbox", "workspace-write", "--ask-for-approval", "on-request", "session-1"]


def test_codex_cmd_wrapper_is_invoked_as_argument_safe_powershell_file(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    install_dir = tmp_path / "Codex Tools"
    install_dir.mkdir()
    command_wrapper = install_dir / "codex.CMD"
    powershell_wrapper = install_dir / "codex.ps1"
    powershell_wrapper.write_text("# fixture", encoding="utf-8")
    dispatcher.continuity.adapters["codex"] = FakeAdapter(str(command_wrapper))
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which", lambda name: r"C:\Program Files\PowerShell\7\pwsh.exe" if name == "pwsh" else None)

    argv = _native_argv(dispatcher, "codex", "session-1", environment_id=slot["current_environment_id"],
                        cwd=r"C:\Project & $Data", native_args=["--sandbox", "workspace-write"])

    assert argv == [r"C:\Program Files\PowerShell\7\pwsh.exe", "-NoLogo", "-NoProfile", "-File",
                    str(powershell_wrapper), "resume", "-C", r"C:\Project & $Data", "--sandbox",
                    "workspace-write", "session-1"]


def test_windows_launcher_uses_wsl_distribution_and_native_working_directory(tmp_path, monkeypatch):
    dispatcher, _ = _dispatcher_with_session(tmp_path, provider="codex", session_id="wsl-session")
    env = EnvironmentInfo(
        environment_id="wsl_ubuntu_test", runtime_kind="wsl", distro="Ubuntu", hostname="test",
        label="Ubuntu", created_at="2026-11-19T00:00:00Z", last_seen_at="2026-11-19T00:00:00Z",
    )
    event = EventEnvelope(
        event_id="evt_wsl_environment", event_schema_version=1, event_type=EventType.ENVIRONMENT_REGISTERED.value,
        provider=None, environment_id=env.environment_id, native_session_id=None,
        source_timestamp=env.created_at, observed_timestamp=env.created_at, source_adapter_version="test",
        payload=env.to_dict(),
    )
    dispatcher.continuity._emit_and_materialize([event])
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="codex", session_id="wsl-session",
                              environment_selector=env.environment_id, cwd="/home/user/project", apply=True)
    dispatcher.continuity.adapters["codex"] = FakeAdapter()
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which", lambda name: r"C:\Windows\System32\wsl.exe")

    argv = _native_argv(dispatcher, "codex", "wsl-session", environment_id=env.environment_id,
                        cwd="/home/user/project")

    assert argv == [r"C:\Windows\System32\wsl.exe", "--distribution", "Ubuntu", "--cd",
                    "/home/user/project", "--exec", "codex", "resume", "wsl-session"]


def test_windows_session_is_not_launched_from_wsl(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "wsl")
    with pytest.raises(ContinuityError, match="Cannot launch windows session from runtime"):
        _native_argv(dispatcher, "codex", "session-1", environment_id=slot["current_environment_id"], cwd=None)


@pytest.mark.parametrize(
    ("provider", "stdout", "session_id"),
    [
        (
            "codex",
            "\n".join((
                '{"type":"thread.started","thread_id":"codex-id"}',
                '{"type":"turn.completed","turn_id":"turn-1"}',
            )),
            "codex-id",
        ),
        (
            "agy",
            json.dumps({"conversation_id": "agy-id", "status": "SUCCESS", "response": "READY"}),
            "agy-id",
        ),
    ],
)
def test_bootstrap_output_captures_exact_provider_session_id(provider, stdout, session_id):
    assert _extract_bootstrap_session_id(provider, stdout) == session_id


def test_bootstrap_output_rejects_missing_or_conflicting_ids():
    assert _extract_bootstrap_session_id("codex", '{"type":"turn.completed"}') is None
    conflicting = "\n".join((
        '{"type":"thread.started","thread_id":"one"}',
        '{"type":"thread.started","thread_id":"two"}',
    ))
    with pytest.raises(ValueError, match="conflicting"):
        _extract_bootstrap_session_id("codex", conflicting)


@pytest.mark.parametrize("provider", ["codex", "agy"])
def test_bootstrap_launch_uses_supported_headless_capture_arguments(tmp_path, monkeypatch, provider):
    dispatcher, slot = _dispatcher_with_session(tmp_path, provider=provider)
    dispatcher.continuity.adapters[provider] = FakeAdapter(r"C:\Tools\provider.exe")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")

    argv = _bootstrap_native_argv(
        dispatcher,
        provider,
        environment_id=slot["current_environment_id"],
        cwd=r"C:\Project With Spaces",
    )

    assert argv[0] == r"C:\Tools\provider.exe"
    if provider == "codex":
        assert argv[1:3] == ["exec", "--json"]
        assert argv[-1].startswith("Session initialization only.")
    else:
        assert argv[1] == "--print"
        assert argv[2].startswith("Session initialization only.")
        assert argv[3] == "--output-format"
        assert argv[4] == "json"


@pytest.mark.parametrize(("provider", "previous_provider"), [("codex", "agy"), ("agy", "codex")])
def test_post_exit_option_four_reuses_opposite_provider_without_creating_slot(
    tmp_path, monkeypatch, provider, previous_provider
):
    dispatcher, slot = _dispatcher_with_session(tmp_path, provider=provider, session_id=f"{provider}-current")
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider=previous_provider,
                              session_id=f"{previous_provider}-previous", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider=provider,
                              session_id=f"{provider}-current", apply=True)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv",
                        lambda dispatcher, selected_provider, session_id, **kw: [selected_provider, session_id])
    output = StringIO()

    code = _run_pane(
        dispatcher,
        slot_id=slot["slot_id"],
        launch_id=None,
        input_stream=StringIO("4\nr\n\n"),
        output_stream=output,
    )

    current = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")
    assert code == 0
    assert len(calls) == 2
    assert calls[1] == [previous_provider, f"{previous_provider}-previous"]
    assert current["current"]["provider"] == previous_provider
    assert len(current["history"]) == 4
    assert len(dispatcher.list_slots(gui="AgentImprovement", active_only=False)) == 1
    assert f"[4] Switch provider (Codex / AGY / Claude; default {previous_provider.upper()})" in output.getvalue()


def test_post_exit_option_four_requires_explicit_confirmation_before_new_provider_bootstrap(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path, provider="codex", session_id="codex-current")
    outputs = iter((
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=0,
                       stdout=json.dumps({"conversation_id": "agy-new", "status": "SUCCESS", "response": "READY"}),
                       stderr=""),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return next(outputs)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **kw: ["agy-bootstrap"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv",
                        lambda dispatcher, selected_provider, session_id, **kw: [selected_provider, session_id])

    code = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                     input_stream=StringIO("4\ny\n\n"), output_stream=StringIO())

    current = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")
    assert code == 0
    assert len(calls) == 3
    assert current["current"]["provider"] == "agy"
    assert current["current"]["native_session_id"] == "agy-new"
    assert len(current["history"]) == 2


def test_post_exit_option_four_cancel_does_not_bootstrap_new_provider(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path, provider="codex", session_id="codex-current")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv",
                        lambda dispatcher, selected_provider, session_id, **kw: [selected_provider, session_id])
    code = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                     input_stream=StringIO("4\nn\n"), output_stream=StringIO())

    current = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")
    assert code == 0
    assert len(calls) == 1
    assert current["current"]["native_session_id"] == "codex-current"
    assert len(current["history"]) == 1
    assert dispatcher.list_pending_launches(gui="AgentImprovement") == []


def test_new_codex_launch_bootstraps_captures_associates_then_resumes_exact_session(tmp_path, monkeypatch):
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    launch = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="codex", apply=True)
    launch_id = launch["details"]["launch_id"]
    calls = []
    outputs = iter(
        (
            SimpleNamespace(
                returncode=0,
                stdout="\n".join((
                    '{"type":"thread.started","thread_id":"codex-bootstrapped"}',
                    '{"type":"turn.completed","turn_id":"turn-1"}',
                )),
                stderr="",
            ),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
    )

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return next(outputs)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-codex", "exec"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv",
                        lambda *a, **k: ["fake-codex", "resume", *k.get("native_args", []), "codex-bootstrapped"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)

    code = _run_pane(dispatcher, slot_id=launch["details"]["slot_id"], launch_id=launch_id,
                     input_stream=StringIO("\n"), output_stream=StringIO(),
                     native_args=["--sandbox", "workspace-write"])

    assert code == 0
    assert len(calls) == 2
    assert calls[0][0] == ["fake-codex", "exec"]
    assert "--sandbox" not in calls[0][0]
    assert calls[0][1]["capture_output"] is True
    assert calls[1][0] == ["fake-codex", "resume", "--sandbox", "workspace-write", "codex-bootstrapped"]
    slot = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")
    assert slot["current"]["native_session_id"] == "codex-bootstrapped"
    assert slot["current"]["provenance"] == "provider_bootstrap_output"
    assert dispatcher.list_pending_launches() == []


def test_new_agy_launch_bootstraps_captures_associates_then_resumes_exact_session(tmp_path, monkeypatch):
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    launch = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="agy", apply=True)
    calls = []
    outputs = iter((
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"conversation_id": "agy-bootstrapped", "status": "SUCCESS", "response": "READY"}),
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ))

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return next(outputs)

    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-agy", "--print"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-agy", "--conversation", "agy-bootstrapped"])
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)

    code = _run_pane(dispatcher, slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
                     input_stream=StringIO("\n"), output_stream=StringIO())

    assert code == 0
    assert len(calls) == 2
    assert calls[0][0] == ["fake-agy", "--print"]
    assert calls[0][1]["capture_output"] is True
    assert calls[1][0] == ["fake-agy", "--conversation", "agy-bootstrapped"]
    slot = dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")
    assert slot["current"]["native_session_id"] == "agy-bootstrapped"
    assert slot["current"]["provenance"] == "provider_bootstrap_output"
    assert dispatcher.list_pending_launches() == []


def test_bootstrap_capture_failure_is_durable_and_does_not_retry_or_replace_current(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path, session_id="old-current")
    launch = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="agy", apply=True)
    calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-agy"])

    def failed_bootstrap(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="not-json", stderr="sensitive provider output")

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", failed_bootstrap)
    result = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                       input_stream=StringIO(""), output_stream=StringIO())

    assert result == 1
    pending = dispatcher.get_pending_launch(launch["details"]["launch_id"])
    assert pending["status"] == "pending"
    assert pending["failure_detail"]
    assert pending["captured_session_id"] is None
    assert "sensitive provider output" not in pending["failure_detail"]
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["current"]["native_session_id"] == "old-current"

    with pytest.raises(ContinuityError, match="not retried automatically"):
        _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                  input_stream=StringIO(""), output_stream=StringIO())
    assert len(calls) == 1


def test_bootstrap_timeout_preserves_pending_state_and_blocks_duplicate_model_call(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path, session_id="old-current")
    launch = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="codex", apply=True)
    calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-codex"])

    def timeout(_argv, **kwargs):
        calls.append(kwargs)
        assert kwargs["timeout"] == 180
        raise subprocess.TimeoutExpired("fake-codex", timeout=180, output="", stderr="")

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", timeout)
    result = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                       input_stream=StringIO(""), output_stream=StringIO())

    assert result == 124
    pending = dispatcher.get_pending_launch(launch["details"]["launch_id"])
    assert pending["failure_detail"] and "exceeded 180 seconds" in pending["failure_detail"]
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["current"]["native_session_id"] == "old-current"
    with pytest.raises(ContinuityError, match="not retried automatically"):
        _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                  input_stream=StringIO(""), output_stream=StringIO())
    assert len(calls) == 1


def test_captured_id_is_recoverable_when_activation_persistence_fails(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path, session_id="old-current")
    launch = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="codex", apply=True)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake-codex"])
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._run_provider_process",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="\n".join((
                '{"type":"thread.started","thread_id":"persist-me"}',
                '{"type":"turn.completed","turn_id":"turn-1"}',
            )),
            stderr="",
        ),
    )
    monkeypatch.setattr(
        dispatcher,
        "attach_session",
        lambda **kwargs: (_ for _ in ()).throw(ContinuityError(ErrorCode.MATERIALIZER_FAILED, "fixture persistence failure")),
    )

    with pytest.raises(ContinuityError, match="fixture persistence failure"):
        _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                  input_stream=StringIO(""), output_stream=StringIO())

    pending = dispatcher.get_pending_launch(launch["details"]["launch_id"])
    assert pending["captured_session_id"] == "persist-me"
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["current"]["native_session_id"] == "old-current"

    dispatcher.materializer.db_path.unlink()
    dispatcher.materializer.rebuild_from_spools()
    rebuilt = DispatcherService(ContinuityService(tmp_path / "registry"))
    assert rebuilt.get_pending_launch(launch["details"]["launch_id"])["captured_session_id"] == "persist-me"


@pytest.mark.parametrize("provider", ["codex", "agy"])
def test_concurrent_provider_bootstraps_bind_each_exact_output_to_its_launch(tmp_path, monkeypatch, provider):
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("GuiA", apply=True)
    dispatcher.create_gui("GuiB", apply=True)
    dispatcher.create_slot(gui="GuiA", name="Agent", apply=True)
    dispatcher.create_slot(gui="GuiB", name="Agent", apply=True)
    launch_a = dispatcher.begin_launch(gui="GuiA", name="Agent", provider=provider, apply=True)
    launch_b = dispatcher.begin_launch(gui="GuiB", name="Agent", provider=provider, apply=True)
    output_ids = iter(("session-from-b", "session-from-a"))

    monkeypatch.setattr("agent_continuity.dispatcher_cli._bootstrap_native_argv", lambda *a, **k: ["fake", "bootstrap"])
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._native_argv",
        lambda _dispatcher, _provider, session_id, **kwargs: ["fake", "resume", session_id],
    )
    def fake_run(_argv, **kwargs):
        if not kwargs.get("capture_output"):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        session_id = next(output_ids)
        if provider == "codex":
            stdout = "\n".join((
                json.dumps({"type": "thread.started", "thread_id": session_id}),
                json.dumps({"type": "turn.completed", "turn_id": session_id}),
            ))
        else:
            stdout = json.dumps({"conversation_id": session_id, "status": "SUCCESS"})
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", fake_run)

    for launch in (launch_b, launch_a):
        slot = dispatcher.get_slot_by_id(launch["details"]["slot_id"])
        assert _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                         input_stream=StringIO("\n"), output_stream=StringIO()) == 0

    assert dispatcher.get_slot(gui="GuiA", name="Agent")["current"]["native_session_id"] == "session-from-a"
    assert dispatcher.get_slot(gui="GuiB", name="Agent")["current"]["native_session_id"] == "session-from-b"


def test_startup_heartbeat_stops_before_interactive_provider_handoff(tmp_path, monkeypatch, capsys):
    import time

    from agent_continuity import dispatcher_cli

    dispatcher, slot = _dispatcher_with_session(tmp_path)
    monkeypatch.setattr(dispatcher_cli, "_native_argv", lambda *args, **kwargs: ["fake-provider"])
    monkeypatch.setattr(dispatcher_cli, "_run_provider_with_progress",
                        lambda *args, **kwargs: pytest.fail("interactive handoff must not use startup heartbeat"))
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process",
                        lambda *args, **kwargs: SimpleNamespace(returncode=17))

    progress_token = dispatcher_cli._STARTUP_PROGRESS.set(True)
    started_token = dispatcher_cli._STARTUP_STARTED.set(time.monotonic())
    try:
        result = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                           input_stream=StringIO(), output_stream=StringIO())
    finally:
        dispatcher_cli._STARTUP_STARTED.reset(started_token)
        dispatcher_cli._STARTUP_PROGRESS.reset(progress_token)

    captured = capsys.readouterr()
    assert result == 17
    assert "interactive provider handoff" in captured.err
    assert "still running" not in captured.err


def test_normal_exit_prompts_and_unexpected_nonzero_exit_preserves_active_state(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-provider"])
    codes = iter((0, 17))
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_provider_process", lambda *a, **k: SimpleNamespace(returncode=next(codes)))

    result = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                       input_stream=StringIO("2\n"), output_stream=StringIO())
    assert result == 0
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["state"] == "completed"

    dispatcher.set_slot_state(gui="AgentImprovement", name="AgentPerf", state="active", apply=True)
    result = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                       input_stream=StringIO("3\n"), output_stream=StringIO())
    assert result == 17
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["state"] == "active"
