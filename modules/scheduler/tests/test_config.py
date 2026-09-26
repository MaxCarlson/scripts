"""
Unit tests for scheduler config detection and serialization.
"""
from scheduler.config import ConfigManager, SchedulerConfig, ExecutablePaths


def test_detect_executables():
    paths = ConfigManager.detect_executables()
    assert isinstance(paths, ExecutablePaths)
    # Default terminal should always be resolvable on any test system
    assert paths.terminal != ""


def test_config_serialization():
    paths = ExecutablePaths(pwsh="/usr/bin/pwsh", powershell="/usr/bin/pwsh", terminal="/bin/bash")
    cfg = SchedulerConfig(
        executables=paths,
        log_retention_runs=25,
        notifications_enabled=False,
        notify_on_run=False,
    )

    d = cfg.to_dict()
    assert d["log_retention_runs"] == 25
    assert d["notifications_enabled"] is False
    assert d["executables"]["pwsh"] == "/usr/bin/pwsh"

    recovered = SchedulerConfig.from_dict(d)
    assert recovered.log_retention_runs == 25
    assert recovered.notifications_enabled is False
    assert recovered.executables.pwsh == "/usr/bin/pwsh"
