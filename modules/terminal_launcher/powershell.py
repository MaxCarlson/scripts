"""PowerShell 7 launch-plan convenience helpers."""

from .models import PaneSpec, TabSpec, TerminalLaunchPlan


def powershell_plan(
    *,
    target_window: str,
    cwd: str | None = None,
    title: str = "PowerShell 7",
) -> TerminalLaunchPlan:
    """Build a plan that opens an interactive PowerShell 7 tab in a named window.

    Reuse the same ``target_window`` value on later calls to send additional tabs
    to that Windows Terminal window. Windows Terminal creates the named window
    when it does not exist yet.
    """
    if not isinstance(target_window, str) or not target_window:
        raise ValueError("target_window must be a non-empty Windows Terminal window name")

    pane = PaneSpec(title=title, argv=("pwsh.exe", "-NoLogo", "-NoExit"), cwd=cwd)
    tab = TabSpec(title=title, panes=(pane,), layout="single")
    return TerminalLaunchPlan(tabs=(tab,), target_window=target_window)
