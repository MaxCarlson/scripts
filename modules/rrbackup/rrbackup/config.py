from __future__ import annotations

import dataclasses as dc
import os
import pathlib
import shutil
import sys
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
    """Return the platform-default canonical configuration path."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        return pathlib.Path(appdata) / "rrbackup" / "config.toml"
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
    try:
        numeric = float(value)
    except ValueError:
        raise ValueError(f"Invalid size value: {raw!r}")
    return raw, int(numeric)


@dc.dataclass
class Repo:
    url: str
    password_env: str | None = None
    password_file: str | None = None

    def expand(self) -> "Repo":
        return Repo(
            url=os.path.expanduser(self.url),
            password_env=self.password_env,
            password_file=os.path.expanduser(self.password_file) if self.password_file else None,
        )


@dc.dataclass
class Schedule:
    """Portable schedule metadata used by wizards and scheduler adapters."""

    type: str = "manual"
    time: str | None = None
    interval: int = 1
    interval_hours: int | None = None
    day_of_week: str | None = None
    day_of_month: int | None = None
    month_of_year: int | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, t.Any]:
        data: dict[str, t.Any] = {"type": self.type}
        if self.time:
            data["time"] = self.time
        if self.interval != 1:
            data["interval"] = self.interval
        if self.interval_hours is not None:
            data["interval_hours"] = self.interval_hours
        if self.day_of_week:
            data["day_of_week"] = self.day_of_week
        if self.day_of_month is not None:
            data["day_of_month"] = self.day_of_month
        if self.month_of_year is not None:
            data["month_of_year"] = self.month_of_year
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
        for field_name in (
            "keep_last",
            "keep_hourly",
            "keep_daily",
            "keep_weekly",
            "keep_monthly",
            "keep_yearly",
        ):
            value = getattr(self, field_name)
            if value is not None:
                data[field_name] = value
        if self.max_total_size:
            data["max_total_size"] = self.max_total_size
        return data


@dc.dataclass
class BackupSet:
    name: str
    include: list[str]
    exclude: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    one_fs: bool = False
    dry_run_default: bool = False
    backup_type: str = "incremental"
    encryption: str | None = None
    compression: str | None = None
    schedule: Schedule = field(default_factory=Schedule)
    retention: RetentionPolicy | None = None
    use_fs_snapshot: bool = True
    exclude_caches: bool = True
    extra_backup_args: list[str] = field(default_factory=list)


@dc.dataclass
class Settings:
    restic_bin: str = "restic"
    rclone_bin: str = "rclone"
    log_dir: str | None = None
    state_dir: str | None = None
    repo: Repo | None = None
    sets: list[BackupSet] = field(default_factory=list)
    retention_defaults: RetentionPolicy = field(default_factory=RetentionPolicy)

    def expand(self) -> "Settings":
        state_dir = self.state_dir
        if not state_dir:
            if os.name == "nt":
                localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
                state_dir = str(pathlib.Path(localapp) / "rrbackup")
            else:
                state_dir = str(pathlib.Path.home() / ".cache" / "rrbackup")

        log_dir = self.log_dir or str(pathlib.Path(state_dir) / "logs")
        expanded_sets: list[BackupSet] = []
        for backup_set in self.sets:
            expanded_sets.append(
                BackupSet(
                    name=backup_set.name,
                    include=[os.path.expanduser(path) for path in backup_set.include],
                    exclude=list(backup_set.exclude),
                    tags=list(backup_set.tags),
                    one_fs=backup_set.one_fs,
                    dry_run_default=backup_set.dry_run_default,
                    backup_type=backup_set.backup_type,
                    encryption=backup_set.encryption,
                    compression=backup_set.compression,
                    schedule=backup_set.schedule,
                    retention=backup_set.retention,
                    use_fs_snapshot=backup_set.use_fs_snapshot,
                    exclude_caches=backup_set.exclude_caches,
                    extra_backup_args=list(backup_set.extra_backup_args),
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
    """Resolve explicit path, RRBACKUP_CONFIG, then platform default."""
    if path:
        return pathlib.Path(path)
    environment_path = os.environ.get("RRBACKUP_CONFIG")
    if environment_path:
        return pathlib.Path(environment_path)
    return platform_config_default()


def load_config(path: PathLikeStr | None, *, expand: bool = True) -> Settings:
    """Load canonical TOML configuration."""
    candidate = resolve_config_path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"Config file not found: {candidate}")

    with candidate.open("rb") as handle:
        data = tomllib.load(handle)
    config_model = _parse_config_dict(data)
    config = config_model.expand() if expand else config_model

    if expand:
        for executable in (config.restic_bin, config.rclone_bin):
            if shutil.which(executable) is None:
                print(f"[rrbackup] Warning: '{executable}' not found on PATH.", file=sys.stderr)
        pathlib.Path(config.state_dir).mkdir(parents=True, exist_ok=True)
        pathlib.Path(config.log_dir).mkdir(parents=True, exist_ok=True)
    return config


def _parse_config_dict(data: ConfigDict) -> Settings:
    repo = Repo(**data["repository"]) if "repository" in data else None
    sets: list[BackupSet] = []
    for raw_set in data.get("backup_sets", []):
        schedule = _parse_schedule(raw_set.get("schedule"))
        retention_input = raw_set.get("retention")
        retention = _parse_retention(retention_input) if retention_input else None
        if not retention and raw_set.get("max_snapshots") is not None:
            retention = RetentionPolicy(keep_last=raw_set["max_snapshots"])
        sets.append(
            BackupSet(
                name=raw_set["name"],
                include=raw_set["include"],
                exclude=raw_set.get("exclude", []),
                tags=raw_set.get("tags", []),
                one_fs=bool(raw_set.get("one_fs", False)),
                dry_run_default=bool(raw_set.get("dry_run_default", False)),
                backup_type=raw_set.get("backup_type", "incremental"),
                encryption=raw_set.get("encryption"),
                compression=raw_set.get("compression"),
                schedule=schedule,
                retention=retention,
                use_fs_snapshot=bool(raw_set.get("use_fs_snapshot", True)),
                exclude_caches=bool(raw_set.get("exclude_caches", True)),
                extra_backup_args=[str(value) for value in raw_set.get("extra_backup_args", [])],
            )
        )

    retention_defaults_input = data.get("retention_defaults") or data.get("retention") or {}
    retention_defaults = _parse_retention(retention_defaults_input)
    return Settings(
        restic_bin=data.get("restic", {}).get("bin", "restic"),
        rclone_bin=data.get("rclone", {}).get("bin", "rclone"),
        log_dir=data.get("log", {}).get("dir"),
        state_dir=data.get("state", {}).get("dir"),
        repo=repo,
        sets=sets,
        retention_defaults=retention_defaults or RetentionPolicy(),
    )


def _parse_schedule(value: t.Any) -> Schedule:
    if isinstance(value, dict):
        interval = value.get("interval", 1)
        legacy_interval_hours = value.get("interval_hours")
        if legacy_interval_hours is not None and "interval" not in value:
            interval = legacy_interval_hours
        return Schedule(
            type=value.get("type", "manual"),
            time=value.get("time"),
            interval=max(1, int(interval)),
            interval_hours=legacy_interval_hours,
            day_of_week=value.get("day_of_week"),
            day_of_month=value.get("day_of_month"),
            month_of_year=value.get("month_of_year"),
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
    """Serialize settings into the canonical TOML dictionary layout."""
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
        for backup_set in settings.sets:
            entry: dict[str, t.Any] = {
                "name": backup_set.name,
                "include": list(backup_set.include),
                "exclude": list(backup_set.exclude),
                "tags": list(backup_set.tags),
                "one_fs": bool(backup_set.one_fs),
                "dry_run_default": bool(backup_set.dry_run_default),
                "use_fs_snapshot": bool(backup_set.use_fs_snapshot),
                "exclude_caches": bool(backup_set.exclude_caches),
            }
            if backup_set.extra_backup_args:
                entry["extra_backup_args"] = list(backup_set.extra_backup_args)
            if backup_set.backup_type and backup_set.backup_type != "incremental":
                entry["backup_type"] = backup_set.backup_type
            if backup_set.encryption:
                entry["encryption"] = backup_set.encryption
            if backup_set.compression:
                entry["compression"] = backup_set.compression
            schedule_dict = backup_set.schedule.to_dict()
            if schedule_dict.get("type") != "manual" or len(schedule_dict) > 1:
                entry["schedule"] = schedule_dict
            if backup_set.retention:
                retention_dict = backup_set.retention.to_dict()
                if retention_dict:
                    entry["retention"] = retention_dict
            backup_sets.append(entry)
        data["backup_sets"] = backup_sets
    return data


def save_config(settings: Settings, path: PathLikeStr, *, overwrite: bool = False) -> pathlib.Path:
    """Persist settings to TOML and return the target path."""
    if tomli_w is None:  # pragma: no cover
        raise RuntimeError("tomli-w is required to write rrbackup configuration files.")
    target = pathlib.Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Config file already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tomli_w.dumps(settings_to_dict(settings)), encoding="utf-8")
    return target
