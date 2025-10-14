from __future__ import annotations

import dataclasses as dc
import os
import sys
import pathlib
import shutil
import typing as t

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


ConfigDict = dict[str, t.Any]


def platform_config_default() -> pathlib.Path:
    """
    Determine the default config path by OS:
      - Windows: %APPDATA%/rrbackup/config.toml
      - Others:  ~/.config/rrbackup/config.toml
    """
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return pathlib.Path(appdata) / "rrbackup" / "config.toml"
    else:
        return pathlib.Path.home() / ".config" / "rrbackup" / "config.toml"


@dc.dataclass
class Repo:
    # Example: "rclone:gdrive:/backups/rrbackup" or "/mnt/d/restic-repo"
    url: str

    # Where Restic password is sourced from. Prefer PASSWORD_FILE for security.
    password_env: str | None = None          # e.g., "RESTIC_PASSWORD"
    password_file: str | None = None         # e.g., "~/.config/rrbackup/restic_password.txt"

    def expand(self) -> "Repo":
        return Repo(
            url=os.path.expanduser(self.url),
            password_env=self.password_env,
            password_file=os.path.expanduser(self.password_file) if self.password_file else None,
        )


@dc.dataclass
class BackupSet:
    name: str
    include: list[str]            # paths to include
    exclude: list[str] = dc.field(default_factory=list)
    tags: list[str] = dc.field(default_factory=list)
    one_fs: bool = False          # restic --one-file-system
    dry_run_default: bool = False # default dry-run behavior for this set


@dc.dataclass
class Retention:
    keep_last: int | None = None
    keep_hourly: int | None = None
    keep_daily: int | None = 7
    keep_weekly: int | None = 4
    keep_monthly: int | None = 6
    keep_yearly: int | None = 2


@dc.dataclass
class Settings:
    restic_bin: str = "restic"
    rclone_bin: str = "rclone"
    log_dir: str | None = None  # default resolved from state_dir if not set
    state_dir: str | None = None  # default: platform-appropriate cache dir
    repo: Repo | None = None
    sets: list[BackupSet] = dc.field(default_factory=list)
    retention: Retention = dc.field(default_factory=Retention)

    def expand(self) -> "Settings":
        # Resolve state_dir & log_dir with OS-specific defaults.
        state_dir = self.state_dir
        if not state_dir:
            if os.name == "nt":
                localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
                state_dir = str(pathlib.Path(localapp) / "rrbackup")
            else:
                state_dir = str(pathlib.Path.home() / ".cache" / "rrbackup")

        log_dir = self.log_dir or str(pathlib.Path(state_dir) / "logs")

        return Settings(
            restic_bin=self.restic_bin,
            rclone_bin=self.rclone_bin,
            log_dir=log_dir,
            state_dir=state_dir,
            repo=self.repo.expand() if self.repo else None,
            sets=[BackupSet(**{**dc.asdict(s), "include": s.include}) for s in self.sets],
            retention=self.retention,
        )


def load_config(path: str | os.PathLike | None) -> Settings:
    """
    Load configuration in TOML. Search order if path is None:
      1) ENV RRBACKUP_CONFIG
      2) platform default (see platform_config_default)
    """
    candidate: pathlib.Path
    if path:
        candidate = pathlib.Path(path)
    else:
        env = os.environ.get("RRBACKUP_CONFIG")
        candidate = pathlib.Path(env) if env else platform_config_default()

    if not candidate.exists():
        raise FileNotFoundError(f"Config file not found: {candidate}")

    with candidate.open("rb") as f:
        data = tomllib.load(f)

    cfg = _parse_config_dict(data)
    # Verify binaries exist (best-effort)
    for exe in (cfg.restic_bin, cfg.rclone_bin):
        if shutil.which(exe) is None:
            print(f"[rrbackup] Warning: '{exe}' not found on PATH.", file=sys.stderr)
    # Ensure dirs exist
    pathlib.Path(cfg.state_dir).mkdir(parents=True, exist_ok=True)
    pathlib.Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def _parse_config_dict(d: ConfigDict) -> Settings:
    repo = None
    if "repository" in d:
        repo = Repo(**d["repository"])

    sets: list[BackupSet] = []
    for s in d.get("backup_sets", []):
        sets.append(BackupSet(
            name=s["name"],
            include=s["include"],
            exclude=s.get("exclude", []),
            tags=s.get("tags", []),
            one_fs=bool(s.get("one_fs", False)),
            dry_run_default=bool(s.get("dry_run_default", False)),
        ))

    retention = Retention(**d.get("retention", {}))
    settings = Settings(
        restic_bin=d.get("restic", {}).get("bin", "restic"),
        rclone_bin=d.get("rclone", {}).get("bin", "rclone"),
        log_dir=d.get("log", {}).get("dir"),
        state_dir=d.get("state", {}).get("dir"),
        repo=repo,
        sets=sets,
        retention=retention,
    )
    return settings.expand()
