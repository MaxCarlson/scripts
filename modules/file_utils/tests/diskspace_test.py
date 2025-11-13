from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from file_utils import diskspace


class DummySys:
    def __init__(self, os_name: str = "linux", termux: bool = False, wsl: bool = False):
        self._os = os_name
        self._termux = termux
        self._wsl = wsl

    def is_windows(self) -> bool:
        return self._os == "windows"

    def is_linux(self) -> bool:
        return self._os == "linux"

    def is_darwin(self) -> bool:
        return self._os == "darwin"

    def is_termux(self) -> bool:
        return self._termux

    def is_wsl2(self) -> bool:
        return self._wsl

    def run_command(self, command: str, sudo: bool = False) -> str:
        # Return a tiny synthetic output for parsing
        if command.startswith("find ") and "-printf" in command:
            return "123\t/tmp/a\n456\t/tmp/b\n"
        if command.startswith("du -xhd1"):
            return "1.0K\t/tmp\n2.0K\t/var\n"
        return ""


def test_scan_largest_files_linux_parse():
    sysu = DummySys(os_name="linux")
    items = diskspace.scan_largest_files(sysu, str(Path.cwd()), top_n=2, min_size=None)
    assert len(items) == 2
    assert items[0].path.endswith("/tmp/a")
    assert items[0].size_bytes == 123


def test_scan_heaviest_dirs_linux_parse():
    sysu = DummySys(os_name="linux")
    items = diskspace.scan_heaviest_dirs(sysu, str(Path.cwd()), top_n=2)
    assert len(items) == 2
    assert items[0].path in ("/tmp", "/var")


def test_build_report_shapes():
    files = [diskspace.FileEntry(path="/x", size_bytes=1024)]
    dirs = [diskspace.DirEntry(path="/y", size_human="1.0K")]
    caches = {"python": ["~/.cache/pip"]}
    data, md = diskspace.build_report(files, dirs, caches)
    assert "largest_files" in data and "heaviest_dirs" in data and "caches" in data
    assert "# Disk Space Report" in md


def test_clean_caches_dry_run_linux():
    sysu = DummySys(os_name="linux")
    actions = diskspace.clean_caches(sysu, ["python", "node", "build", "apt", "journals", "git", "fstrim"], dry_run=True)
    assert any("DRY-RUN" in a for a in actions)
    assert any("APT clean" in a for a in actions)
    assert any("Git GC" in a for a in actions)
    # node_modules included
    assert any("node_modules" in a for a in actions)
    # fstrim present
    assert any("FSTRIM" in a for a in actions)


def test_containers_maint_auto():
    sysu = DummySys(os_name="linux")
    actions = diskspace.containers_maint(sysu, "auto", dry_run=True)
    joined = "\n".join(actions)
    assert "Docker df" in joined and "Podman ps" in joined


def test_wsl_reclaim_linux_and_windows():
    # WSL side (linux kernel)
    sysu_wsl = DummySys(os_name="linux", wsl=True)
    acts = diskspace.wsl_reclaim(sysu_wsl, dry_run=True)
    assert any("WSL fstrim" in a for a in acts)
    assert any("compact" in a for a in acts)

    # Windows host side
    sysu_win = DummySys(os_name="windows")
    acts2 = diskspace.wsl_reclaim(sysu_win, dry_run=True)
    assert any("Windows VHDX LZX compact" in a for a in acts2)
