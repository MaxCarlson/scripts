from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from file_utils import diskspace


class DummySys:
    def __init__(self):
        self._os = "linux"

    def is_windows(self) -> bool: return False
    def is_linux(self) -> bool: return True
    def is_wsl2(self) -> bool: return False
    def is_termux(self) -> bool: return False

    def run_command(self, command: str, sudo: bool = False) -> str:
        # Synthetic outputs for find and du -sb used by diskspace helpers
        if command.startswith("find ") and "-printf" in command:
            # two files
            return "100\t/tmp/foo\n200\t/tmp/bar\n"
        if command.startswith("du -sb "):
            return "1024\n"
        if "docker system df" in command or "podman system df" in command:
            return ""
        return ""


def test_run_full_scan_aggregates(monkeypatch, tmp_path):
    sysu = DummySys()

    # Stub caches to a deterministic temp dir
    cache_dir = tmp_path / "cacheA"
    cache_dir.mkdir()
    (cache_dir / "a.bin").write_bytes(b"x" * 512)
    (cache_dir / "b.bin").write_bytes(b"x" * 512)

    monkeypatch.setattr(diskspace, "detect_common_caches", lambda s, r: {"python": [str(cache_dir)]})

    info = diskspace.run_full_scan(sysu, path=str(tmp_path), top_n=2, min_size=None, provider="podman", list_containers=False)

    assert "largest" in info and "caches" in info and "overall" in info
    # Largest total from DummySys.find
    assert info["largest"]["total_bytes"] == 300
    # Caches total should be 1024 from DummySys.du or fallback
    assert info["caches"]["total_bytes"] >= 1024
    # Overall at least the sum of sections
    assert info["overall"]["total_bytes"] >= info["largest"]["total_bytes"] + info["caches"]["total_bytes"]

