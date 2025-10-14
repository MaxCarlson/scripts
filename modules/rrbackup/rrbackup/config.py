from __future__ import annotations

import dataclasses as dc
import os
import sys
import pathlib
import shutil
import typing as t
from dataclasses import field

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    tomli_w = None


PathLikeStr = str | os.PathLike[str]
ConfigDict = dict[str, t.Any]

_SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}


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


def _parse_size_to_bytes(raw: str | None) -> tuple[str | None, int | None]:
    if raw is None:
        return None, None
    value = raw.strip().upper()
    if not value:
        return None, None
    for unit in sorted(_SIZE_UNITS, key=len, reverse=True):
        if value.endswith(unit):
            number_part = value[: -len(unit)].strip()
            try:
                numeric = float(number_part)
            except ValueError:
                raise ValueError(f"Invalid size value: {raw!r}")
            return raw, int(numeric * _SIZE_UNITS[unit])
    # default assume bytes
    try:
        numeric = float(value)
    except ValueError:
        raise ValueError(f"Invalid size value: {raw!r}")
    return raw, int(numeric)


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
class Schedule:
    type: str = "manual"          # manual, hourly, daily, weekly, monthly, custom
    time: str | None = None       # HH:MM 24h time
    interval_hours: int | None = None
    day_of_week: str | None = None
    day_of_month: int | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, t.Any]:
        data: dict[str, t.Any] = {"type": self.type}
        if self.time:
            data["time"] = self.time
        if self.interval_hours is not None:
            data["interval_hours"] = self.interval_hours
        if self.day_of_week:
            data["day_of_week"] = self.day_of_week
        if self.day_of_month is not None:
            data["day_of_month"] = self.day_of_month
        if self.description:
            data["description"] = self.description
        return data


@dc.dataclass
class RetentionPolicy:
    keep_last: int | None = None
    keep_hourly: int | None = None
    keep_daily: int | None = 7
    keep_weekly: int | None = 4
    keep_monthly: int | None = 6
    keep_yearly: int | None = 2
    max_total_size: str | None = None
    max_total_size_bytes: int | None = None

    def to_dict(self) -> dict[str, t.Any]:
        data: dict[str, t.Any] = {}
        for field_name in ("keep_last", "keep_hourly", "keep_daily", "keep_weekly", "keep_monthly", "keep_yearly"):
            value = getattr(self, field_name)
            if value is not None:
                data[field_name] = value
        if self.max_total_size:
            data["max_total_size"] = self.max_total_size
        return data


@dc.dataclass
class BackupSet:
    name: str
    include: list[str]            # paths to include
    exclude: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    one_fs: bool = False          # restic --one-file-system
    dry_run_default: bool = False # default dry-run behavior for this set
    backup_type: str = "incremental"
    encryption: str | None = None
    compression: str | None = None
    schedule: Schedule = field(default_factory=Schedule)
    retention: RetentionPolicy | None = None


@dc.dataclass
class Settings:
    restic_bin: str = "restic"
    rclone_bin: str = "rclone"
    log_dir: str | None = None  # default resolved from state_dir if not set
    state_dir: str | None = None  # default: platform-appropriate cache dir
    repo: Repo | None = None
    sets: list[BackupSet] = field(default_factory=list)
    retention_defaults: RetentionPolicy = field(default_factory=RetentionPolicy)

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

        expanded_sets: list[BackupSet] = []
        for s in self.sets:
            expanded_sets.append(
                BackupSet(
                    name=s.name,
                    include=[os.path.expanduser(p) for p in s.include],
                    exclude=list(s.exclude),
                    tags=list(s.tags),
                    one_fs=s.one_fs,
                    dry_run_default=s.dry_run_default,
                    backup_type=s.backup_type,
                    encryption=s.encryption,
                    compression=s.compression,
                    schedule=s.schedule,
                    retention=s.retention,
                )
            )

        return Settings(
            restic_bin=self.restic_bin,
            rclone_bin=self.rclone_bin,
            log_dir=log_dir,
            state_dir=state_dir,
            repo=self.repo.expand() if self.repo else None,
            sets=expanded_sets,
            retention_defaults=self.retention_defaults,
        )


def resolve_config_path(path: PathLikeStr | None) -> pathlib.Path:
    """
    Resolve the path to the rrbackup configuration file using the standard
    precedence order (explicit path -> RRBACKUP_CONFIG env -> platform default).
    """
    if path:
        return pathlib.Path(path)
    env = os.environ.get("RRBACKUP_CONFIG")
    if env:
        return pathlib.Path(env)
    return platform_config_default()


def load_config(path: PathLikeStr | None, *, expand: bool = True) -> Settings:
    """
    Load configuration in TOML. Search order if path is None:
      1) ENV RRBACKUP_CONFIG
      2) platform default (see platform_config_default)
    """
    candidate = resolve_config_path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"Config file not found: {candidate}")

    with candidate.open("rb") as f:
        data = tomllib.load(f)

    cfg_model = _parse_config_dict(data)
    cfg = cfg_model.expand() if expand else cfg_model

    if expand:
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
        schedule_input = s.get("schedule")
        schedule = _parse_schedule(schedule_input)

        retention_input = s.get("retention")
        retention = _parse_retention(retention_input) if retention_input else None

        # Backwards compatibility for legacy fields
        if not retention:
            legacy_max = s.get("max_snapshots")
            if legacy_max is not None:
                retention = RetentionPolicy(keep_last=legacy_max)

        sets.append(
            BackupSet(
                name=s["name"],
                include=s["include"],
                exclude=s.get("exclude", []),
                tags=s.get("tags", []),
                one_fs=bool(s.get("one_fs", False)),
                dry_run_default=bool(s.get("dry_run_default", False)),
                backup_type=s.get("backup_type", "incremental"),
                encryption=s.get("encryption"),
                compression=s.get("compression"),
                schedule=schedule,
                retention=retention,
            )
        )

    retention_defaults_input = (
        d.get("retention_defaults")
        or d.get("retention")  # backwards compatibility
        or {}
    )
    retention_defaults = _parse_retention(retention_defaults_input)

    settings = Settings(
        restic_bin=d.get("restic", {}).get("bin", "restic"),
        rclone_bin=d.get("rclone", {}).get("bin", "rclone"),
        log_dir=d.get("log", {}).get("dir"),
        state_dir=d.get("state", {}).get("dir"),
        repo=repo,
        sets=sets,
        retention_defaults=retention_defaults or RetentionPolicy(),
    )
    return settings


def _parse_schedule(value: t.Any) -> Schedule:
    if isinstance(value, dict):
        return Schedule(
            type=value.get("type", "manual"),
            time=value.get("time"),
            interval_hours=value.get("interval_hours"),
            day_of_week=value.get("day_of_week"),
            day_of_month=value.get("day_of_month"),
            description=value.get("description"),
        )
    if isinstance(value, str):
        return Schedule(type="custom", description=value)
    return Schedule()


def _parse_retention(value: t.Any) -> RetentionPolicy | None:
    if value is None:
        return None
    if isinstance(value, RetentionPolicy):
        return value
    if not isinstance(value, dict):
        raise TypeError("Retention policy must be a dict.")

    max_size_raw, max_size_bytes = _parse_size_to_bytes(value.get("max_total_size"))
    return RetentionPolicy(
        keep_last=value.get("keep_last"),
        keep_hourly=value.get("keep_hourly"),
        keep_daily=value.get("keep_daily", 7),
        keep_weekly=value.get("keep_weekly", 4),
        keep_monthly=value.get("keep_monthly", 6),
        keep_yearly=value.get("keep_yearly", 2),
        max_total_size=max_size_raw,
        max_total_size_bytes=max_size_bytes,
    )


def settings_to_dict(settings: Settings) -> ConfigDict:
    """
    Serialize Settings back into the TOML dictionary layout expected by rrbackup.
    Only non-empty sections are included.
    """
    data: ConfigDict = {}
    if settings.repo:
        repo_dict: dict[str, t.Any] = {"url": settings.repo.url}
        if settings.repo.password_env:
            repo_dict["password_env"] = settings.repo.password_env
        if settings.repo.password_file:
            repo_dict["password_file"] = settings.repo.password_file
        data["repository"] = repo_dict

    data["restic"] = {"bin": settings.restic_bin}
    data["rclone"] = {"bin": settings.rclone_bin}

    if settings.state_dir is not None:
        data["state"] = {"dir": settings.state_dir}
    if settings.log_dir is not None:
        data["log"] = {"dir": settings.log_dir}

    retention_defaults_dict = settings.retention_defaults.to_dict()
    if retention_defaults_dict:
        data["retention_defaults"] = retention_defaults_dict

    if settings.sets:
        backup_sets: list[dict[str, t.Any]] = []
        for bset in settings.sets:
            entry: dict[str, t.Any] = {
                "name": bset.name,
                "include": list(bset.include),
                "exclude": list(bset.exclude),
                "tags": list(bset.tags),
                "one_fs": bool(bset.one_fs),
                "dry_run_default": bool(bset.dry_run_default),
            }
            if bset.backup_type and bset.backup_type != "incremental":
                entry["backup_type"] = bset.backup_type
            if bset.encryption:
                entry["encryption"] = bset.encryption
            if bset.compression:
                entry["compression"] = bset.compression
            schedule_dict = bset.schedule.to_dict()
            if schedule_dict.get("type") != "manual" or len(schedule_dict) > 1:
                entry["schedule"] = schedule_dict
            if bset.retention:
                retention_dict = bset.retention.to_dict()
                if retention_dict:
                    entry["retention"] = retention_dict
            backup_sets.append(entry)
        data["backup_sets"] = backup_sets

    return data


def save_config(settings: Settings, path: PathLikeStr, *, overwrite: bool = False) -> pathlib.Path:
    """
    Persist Settings to a TOML configuration file. Returns the resolved path.
    """
    if tomli_w is None:  # pragma: no cover - dependency should exist via pyproject
        raise RuntimeError("tomli-w is required to write rrbackup configuration files.")

    target = pathlib.Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Config file already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = settings_to_dict(settings)
    content = tomli_w.dumps(payload)
    target.write_text(content, encoding="utf-8")
    return target
