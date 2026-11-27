import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
from terminal_launcher.backend import LaunchStatus, ProcessState
from terminal_launcher.backends._pane_runner import run_payload
from terminal_launcher.backends.windows_terminal import WindowsTerminalBackend
from terminal_launcher.errors import (
    InvalidPlanError,
    TerminalNotFoundError,
    UnsupportedLayoutError,
    UnsupportedPlatformError,
)
from terminal_launcher.models import PaneSpec, TabSpec, TerminalLaunchPlan


class CaptureRunner:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, self.returncode, stdout="", stderr="")


def make_plan(count: int = 1, *, target_window: str | None = None) -> TerminalLaunchPlan:
    panes = tuple(
        PaneSpec(
            f"Pane {index}",
            (r"C:\Program Files\Tools\worker.exe", "two words", 'say "hi"', "semi;colon", "|&<>^()雪"),
            rf"C:\Work Area\{index}",
        )
        for index in range(1, count + 1)
    )
    layout = {1: "single", 2: "two-column", 3: "three-left", 4: "grid"}[count]
    return TerminalLaunchPlan((TabSpec("Tab 雪", panes, layout),), target_window)


@pytest.mark.parametrize(
    ("count", "split_directions", "focus_directions"),
    [
        (1, [], []),
        (2, ["-V"], []),
        (3, ["-V", "-H"], []),
        (4, ["-V", "-H", "-H"], ["left", "right"]),
    ],
)
def test_preview_builds_documented_nested_split_operations_without_running_processes(
    count, split_directions, focus_directions
):
    runner = CaptureRunner()
    backend = WindowsTerminalBackend(executable="wt.exe", runner=runner)

    preview = backend.preview(make_plan(count))

    assert runner.calls == []
    assert len(preview.operations) == count
    command = backend.build_command(make_plan(count))
    assert [command[index + 1] for index, token in enumerate(command) if token == "split-pane"] == split_directions
    assert [command[index + 1] for index, token in enumerate(command) if token == "move-focus"] == focus_directions
    assert "--target" not in command
    assert "--title" in command
    assert "Tab 雪" in command
    assert "--suppressApplicationTitle" in command
    assert all(pane.cwd is not None for pane in make_plan(count).tabs[0].panes)


def test_build_command_transports_exact_argv_and_cwd_outside_wt_command_grammar():
    original = make_plan().tabs[0].panes[0]
    pane = PaneSpec(original.title, original.argv, r"C:\Work Area;雪")
    plan = TerminalLaunchPlan((TabSpec("Tab 雪", (pane,), "single"),))
    command = WindowsTerminalBackend(executable="wt.exe").build_command(plan)

    commandline = command[-1]
    payload = json.dumps((pane.argv, pane.cwd), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    assert commandline.endswith(encoded)
    assert ";" not in commandline
    assert "semi;colon" not in commandline
    assert "雪" not in commandline

    seen = {}

    def child_runner(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    assert run_payload(encoded, runner=child_runner) == 0
    assert seen["argv"] == list(pane.argv)
    assert seen["cwd"] == pane.cwd
    assert seen["shell"] is False


def test_pane_runner_works_when_executed_as_the_windows_terminal_script():
    pane = PaneSpec("relay", (sys.executable, "-c", "pass"))
    encoded = WindowsTerminalBackend._relay_argv(pane)[-1]
    relay = Path(__file__).parents[1] / "backends" / "_pane_runner.py"

    completed = subprocess.run(
        [sys.executable, str(relay), encoded],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_target_window_is_explicit_and_default_policy_is_explained():
    backend = WindowsTerminalBackend(executable="wt.exe")

    targeted = backend.build_command(make_plan(target_window="build window"))
    preview = backend.preview(make_plan())

    assert targeted[:3] == ("wt.exe", "--window", "build window")
    assert any("windowingBehavior" in warning for warning in preview.warnings)


def test_multiple_tabs_are_submitted_in_one_command_vector():
    first = make_plan(2).tabs[0]
    second = TabSpec("Second", (PaneSpec("Last", ("echo", "ok")),), "single")
    plan = TerminalLaunchPlan((first, second))

    command = WindowsTerminalBackend(executable="wt.exe").build_command(plan)

    assert command.count(";") == 2
    assert command.count("new-tab") == 2
    assert command.count("split-pane") == 1
    assert "Second" in command


def test_preview_does_not_include_process_arguments_in_diagnostics():
    secret = "opaque-secret-token"
    plan = TerminalLaunchPlan((TabSpec("safe", (PaneSpec("pane", ("worker", secret)),), "single"),))
    preview = WindowsTerminalBackend(executable="wt.exe").preview(plan)

    assert secret not in repr(preview)


def test_missing_terminal_executable_has_a_typed_error(monkeypatch):
    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.shutil.which", lambda _: None)

    with pytest.raises(TerminalNotFoundError, match="wt.exe"):
        WindowsTerminalBackend().preview(make_plan())


def test_unsupported_platform_has_a_typed_error(monkeypatch):
    backend = WindowsTerminalBackend(executable="wt.exe")
    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.sys.platform", "linux")

    with pytest.raises(UnsupportedPlatformError):
        backend.preview(make_plan())


def test_unsupported_layout_and_invalid_plan_are_reported(monkeypatch):
    plan = make_plan()
    object.__setattr__(plan.tabs[0], "layout", "diagonal")
    backend = WindowsTerminalBackend(executable="wt.exe")

    with pytest.raises(UnsupportedLayoutError):
        backend.preview(plan)
    with pytest.raises(InvalidPlanError):
        backend.preview(object())


def test_launch_returns_submission_status_and_keeps_process_state_unknown():
    runner = CaptureRunner()
    backend = WindowsTerminalBackend(executable="wt.exe", runner=runner)

    result = backend.launch(make_plan())

    assert result.status is LaunchStatus.SUBMITTED
    assert result.process_state is ProcessState.UNKNOWN
    assert len(runner.calls) == 1
    command, kwargs = runner.calls[0]
    assert command[0] == "wt.exe"
    assert kwargs["shell"] is False


def test_nonzero_terminal_exit_is_reported_as_a_failed_request():
    runner = CaptureRunner(returncode=17)
    backend = WindowsTerminalBackend(executable="wt.exe", runner=runner)

    result = backend.launch(make_plan())

    assert result.status is LaunchStatus.FAILED
    assert result.returncode == 17
    assert result.process_state is ProcessState.UNKNOWN
    assert result.diagnostic


def test_runner_failure_is_reported_without_echoing_child_arguments():
    class MissingAtCall:
        def __call__(self, command, **kwargs):
            raise FileNotFoundError("wt.exe vanished after preview")

    result = WindowsTerminalBackend(executable="wt.exe", runner=MissingAtCall()).launch(make_plan())

    assert result.status is LaunchStatus.FAILED
    assert result.process_state is ProcessState.UNKNOWN
    assert "FileNotFoundError" in result.diagnostic
    assert "semi;colon" not in result.diagnostic


def test_empty_plan_is_a_noop_and_does_not_invoke_the_runner():
    runner = CaptureRunner()

    result = WindowsTerminalBackend(executable="wt.exe", runner=runner).launch(TerminalLaunchPlan(()))

    assert result.status is LaunchStatus.NOOP
    assert runner.calls == []


def test_empty_plan_preview_does_not_require_windows_terminal(monkeypatch):
    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.shutil.which", lambda _: None)

    preview = WindowsTerminalBackend().preview(TerminalLaunchPlan(()))

    assert preview.operations == ()
    assert preview.warnings == ()


def test_custom_executable_path_is_kept_as_one_argument():
    executable = str(Path("C:/Program Files/Windows Terminal/wt.exe"))
    command = WindowsTerminalBackend(executable=executable).build_command(make_plan())

    assert command[0] == executable


@pytest.mark.parametrize("value_kind", ["title", "window"])
def test_wt_metadata_with_semicolon_is_rejected_instead_of_corrupted(value_kind):
    pane = PaneSpec("Worker", ("worker.exe",), r"C:\Work;Area")
    title = "Worker; One" if value_kind == "title" else "Worker"
    target = "Window; One" if value_kind == "window" else None
    plan = TerminalLaunchPlan((TabSpec(title, (pane,), "single"),), target_window=target)

    with pytest.raises(UnsupportedLayoutError, match="semicolon"):
        WindowsTerminalBackend(executable="wt.exe").build_command(plan)
    with pytest.raises(UnsupportedLayoutError, match="semicolon"):
        WindowsTerminalBackend(executable="wt.exe").preview(plan)


def test_missing_executable_on_launch_is_a_structured_failed_request(monkeypatch):
    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.shutil.which", lambda _: None)

    result = WindowsTerminalBackend().launch(make_plan())

    assert result.status is LaunchStatus.FAILED
    assert "Windows Terminal was not found" in result.diagnostic
    assert result.process_state is ProcessState.UNKNOWN
