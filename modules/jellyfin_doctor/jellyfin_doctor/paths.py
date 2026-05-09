"""Jellyfin path defaults and discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_SERVER_DIR = Path(r"C:\ProgramData\Jellyfin\Server")
DEFAULT_INSTALL_DIR = Path(r"C:\Program Files\Jellyfin\Server")
DEFAULT_DATA_DIR = Path(r"C:\ProgramData\Jellyfin\Server\data")
DEFAULT_CONFIG_DIR = Path(r"C:\ProgramData\Jellyfin\Server\config")
DEFAULT_CACHE_DIR = Path(r"C:\ProgramData\Jellyfin\Server\cache")
DEFAULT_METADATA_DIR = Path(r"C:\ProgramData\Jellyfin\Server\metadata")
DEFAULT_ROOT_DIR = Path(r"C:\ProgramData\Jellyfin\Server\root")
DEFAULT_LOG_DIR = Path(r"C:\ProgramData\Jellyfin\Server\log")
DEFAULT_TRAY_EXE = Path(r"C:\Program Files\Jellyfin\Server\jellyfin-windows-tray\Jellyfin.Windows.Tray.exe")


@dataclass(frozen=True)
class JellyfinPaths:
    """Resolved paths for a Jellyfin server state tree."""

    server_dir: Path = DEFAULT_SERVER_DIR
    install_dir: Path = DEFAULT_INSTALL_DIR
    data_dir: Path = DEFAULT_DATA_DIR
    config_dir: Path = DEFAULT_CONFIG_DIR
    cache_dir: Path = DEFAULT_CACHE_DIR
    metadata_dir: Path = DEFAULT_METADATA_DIR
    root_dir: Path = DEFAULT_ROOT_DIR
    log_dir: Path = DEFAULT_LOG_DIR
    tray_exe: Path = DEFAULT_TRAY_EXE

    @classmethod
    def from_overrides(
        cls,
        *,
        server_dir: str | Path | None = None,
        install_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
        log_dir: str | Path | None = None,
        tray_exe: str | Path | None = None,
    ) -> JellyfinPaths:
        server = Path(server_dir) if server_dir else DEFAULT_SERVER_DIR
        install = Path(install_dir) if install_dir else DEFAULT_INSTALL_DIR
        return cls(
            server_dir=server,
            install_dir=install,
            data_dir=Path(data_dir) if data_dir else server / "data",
            config_dir=server / "config",
            cache_dir=server / "cache",
            metadata_dir=server / "metadata",
            root_dir=server / "root",
            log_dir=Path(log_dir) if log_dir else server / "log",
            tray_exe=Path(tray_exe) if tray_exe else install / "jellyfin-windows-tray" / "Jellyfin.Windows.Tray.exe",
        )

    def state_dirs(self) -> dict[str, Path]:
        """Return all resettable Jellyfin state directories."""
        return {
            "data": self.data_dir,
            "config": self.config_dir,
            "cache": self.cache_dir,
            "metadata": self.metadata_dir,
            "root": self.root_dir,
        }

    def report_dirs(self) -> dict[str, Path]:
        """Return directories shown by path and backup diagnostics."""
        return {**self.state_dirs(), "log": self.log_dir}


def latest_log(log_dir: Path) -> Path | None:
    """Return the newest ``log_*.log`` file in ``log_dir``."""
    try:
        logs = [path for path in log_dir.glob("log_*.log") if path.is_file()]
    except OSError:
        return None
    if not logs:
        return None
    return max(logs, key=lambda item: item.stat().st_mtime)


def resolve_log_file(log_file: str | Path | None = None, log_dir: str | Path | None = None) -> Path | None:
    """Resolve an explicit log file or the latest log under a directory."""
    if log_file:
        return Path(log_file)
    return latest_log(Path(log_dir) if log_dir else DEFAULT_LOG_DIR)

