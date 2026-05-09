"""Process discovery and native Jellyfin control helpers."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROCESS_NAMES = ("jellyfin", "Jellyfin.Windows.Tray", "ffmpeg", "ffprobe")


@dataclass(frozen=True)
class ProcessInfo:
    """Serializable process information."""

    pid: int
    ppid: int | None
    name: str
    command_line: str
    rss_bytes: int
    cpu_time_seconds: float
    create_time: float | None


def _psutil():
    try:
        import psutil

        return psutil
    except ImportError as exc:  # pragma: no cover - dependency should be installed in normal use
        raise RuntimeError("psutil is required for process commands") from exc


def find_processes(names: Iterable[str] = DEFAULT_PROCESS_NAMES) -> list[ProcessInfo]:
    """Find matching processes by executable name substring."""
    psutil = _psutil()
    lowered = tuple(name.lower() for name in names)
    matches: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "memory_info", "cpu_times", "create_time"]):
        try:
            name = proc.info.get("name") or ""
            if not any(target in name.lower() for target in lowered):
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            memory = proc.info.get("memory_info")
            cpu_times = proc.info.get("cpu_times")
            matches.append(
                ProcessInfo(
                    pid=int(proc.info["pid"]),
                    ppid=proc.info.get("ppid"),
                    name=name,
                    command_line=cmdline,
                    rss_bytes=int(getattr(memory, "rss", 0)),
                    cpu_time_seconds=float(getattr(cpu_times, "user", 0.0) + getattr(cpu_times, "system", 0.0)),
                    create_time=proc.info.get("create_time"),
                )
            )
        except Exception:
            continue
    return matches


def is_jellyfin_running() -> bool:
    """Return whether a Jellyfin server or tray process is running."""
    return bool(find_processes(("jellyfin", "Jellyfin.Windows.Tray")))


def stop_jellyfin(*, force: bool = False, timeout_seconds: float = 15.0) -> dict[str, object]:
    """Terminate Jellyfin processes."""
    psutil = _psutil()
    stopped: list[int] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name") or ""
            if "jellyfin" not in name.lower():
                continue
            proc.kill() if force else proc.terminate()
            stopped.append(int(proc.info["pid"]))
        except Exception:
            continue
    deadline = time.time() + timeout_seconds
    while time.time() < deadline and is_jellyfin_running():
        time.sleep(0.2)
    return {"stopped_pids": stopped, "still_running": is_jellyfin_running()}


def start_tray(tray_exe: Path) -> dict[str, object]:
    """Start the native Windows Jellyfin tray executable."""
    if not tray_exe.exists():
        return {"started": False, "error": f"Tray executable not found: {tray_exe}"}
    proc = subprocess.Popen([str(tray_exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"started": True, "pid": proc.pid, "tray_exe": str(tray_exe)}

