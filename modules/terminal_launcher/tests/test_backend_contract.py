from dataclasses import FrozenInstanceError

import pytest
from terminal_launcher.backend import (
    LaunchPreview,
    LaunchResult,
    LaunchStatus,
    PlannedOperation,
    ProcessState,
    TerminalBackend,
)
from terminal_launcher.models import PaneSpec, TabSpec, TerminalLaunchPlan


class FakeBackend:
    def __init__(self):
        self.launch_calls = 0

    def preview(self, plan: TerminalLaunchPlan) -> LaunchPreview:
        return LaunchPreview(
            backend="fake",
            operations=tuple(
                PlannedOperation("create_tab", index, 0, tab.title, tab.panes[0].title, tab.layout, tab.panes[0].cwd)
                for index, tab in enumerate(plan.tabs)
            ),
            warnings=(),
        )

    def launch(self, plan: TerminalLaunchPlan) -> LaunchResult:
        self.launch_calls += 1
        return LaunchResult(LaunchStatus.SUBMITTED, "fake", process_state=ProcessState.UNKNOWN)


def test_preview_describes_operations_without_launching_processes():
    backend = FakeBackend()
    plan = TerminalLaunchPlan((TabSpec("Build", (PaneSpec("compiler", ("build.exe",)),), "single"),))

    preview = backend.preview(plan)

    assert isinstance(backend, TerminalBackend)
    assert backend.launch_calls == 0
    assert preview.operations[0].action == "create_tab"
    assert preview.operations[0].tab_title == "Build"


def test_launch_result_reports_submission_and_unknown_process_state():
    backend = FakeBackend()
    result = backend.launch(TerminalLaunchPlan(()))

    assert result.status is LaunchStatus.SUBMITTED
    assert result.process_state is ProcessState.UNKNOWN
    assert backend.launch_calls == 1
    with pytest.raises(FrozenInstanceError):
        result.status = LaunchStatus.FAILED


def test_launch_result_can_report_failed_submission_without_claiming_process_state():
    result = LaunchResult(
        LaunchStatus.FAILED,
        "fake",
        process_state=ProcessState.UNKNOWN,
        returncode=2,
        diagnostic="terminal rejected the request",
    )

    assert result.status is LaunchStatus.FAILED
    assert result.returncode == 2
    assert result.process_state is ProcessState.UNKNOWN
