from __future__ import annotations

from file_utils import wsltool


class DummySys:
    def __init__(self, win: bool = False, wsl: bool = False):
        self._win = win
        self._wsl = wsl

    def is_windows(self) -> bool:
        return self._win

    def is_linux(self) -> bool:
        return not self._win

    def is_wsl2(self) -> bool:
        return self._wsl

    def run_command(self, cmd: str, sudo: bool = False) -> str:
        return f"ran: {cmd}"


def test_detect_env_variants():
    assert wsltool.detect_env(DummySys(win=True, wsl=False)) == "windows"
    assert wsltool.detect_env(DummySys(win=False, wsl=True)) == "wsl"
    assert wsltool.detect_env(DummySys(win=False, wsl=False)) == "unsupported"


def test_compact_wsl_and_windows_dryrun():
    acts_wsl = wsltool.compact(DummySys(win=False, wsl=True), guard_gb=10, dry_run=True)
    assert any("WSL fstrim" in a for a in acts_wsl)
    # No host instructions by default
    assert all("compact the VHDX" not in a for a in acts_wsl)

    # With host help
    acts_wsl_help = wsltool.compact(DummySys(win=False, wsl=True), guard_gb=10, dry_run=True, show_host_instructions=True)
    assert any("compact the VHDX" in a for a in acts_wsl_help)

    acts_win = wsltool.compact(DummySys(win=True, wsl=False), guard_gb=10, dry_run=True)
    assert any("Windows VHDX LZX compact" in a for a in acts_win)


def test_docker_desktop_fixups_windows_only():
    acts = wsltool.docker_desktop_fixups(DummySys(win=True, wsl=False), dry_run=True)
    # Should include PowerShell-wrapped cmdlets (Stop-Process/Start-Process) and docker context
    assert any("docker context use desktop-linux" in a for a in acts)
    assert any("-NoProfile -Command" in a for a in acts)
    acts2 = wsltool.docker_desktop_fixups(DummySys(win=False, wsl=True), dry_run=True)
    assert any("only applicable" in a for a in acts2)
