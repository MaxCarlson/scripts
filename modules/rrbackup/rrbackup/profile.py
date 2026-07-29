"""Canonical backup profile and legacy `backup_module` configuration adapter."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .policy import CpuPolicy

DEFAULT_REPOSITORY = r"B:\ResticRepos\PC-Local"
DEFAULT_PASSWORD_FILE = r"C:\BackupConfig\restic-local-password.txt"
DEFAULT_SOURCES_FILE = r"C:\BackupConfig\local-sources.txt"
DEFAULT_EXCLUDES_FILE = r"C:\BackupConfig\local-excludes.txt"
DEFAULT_STATUS_FILE = r"C:\BackupConfig\local-backup-status.json"
DEFAULT_LOG_FILE = r"C:\BackupConfig\local-backup.log"
DEFAULT_LOCK_FILE = r"C:\BackupConfig\local-backup.lock"
DEFAULT_CONFIG_PATH = r"C:\BackupConfig\local_backup_config.json"
DEFAULT_TAG = "local-main"
DEFAULT_RESTIC_EXECUTABLE = "restic"
DEFAULT_RESTORE_ROOT = r"B:\ResticRestore"


class ValueSource(str, Enum):
    """Origin of an effective profile field."""

    DEFAULT = "default"
    ENVIRONMENT = "environment"
    CONFIG_FILE = "config-file"
    EXPLICIT = "explicit"


@dataclass(frozen=True)
class SourceAttribution:
    """Source metadata for one effective profile field."""

    source: ValueSource
    detail: str

    def to_dict(self) -> Dict[str, str]:
        return {"source": self.source.value, "detail": self.detail}


@dataclass
class BackupProfile:
    """Canonical configuration used by the merged backup engine."""

    name: str
    repository: str
    password_file: str
    sources_file: Optional[str]
    excludes_file: Optional[str]
    status_file: str
    log_file: str
    lock_file: str
    tag: Optional[str]
    restic_executable: str
    restore_root: str
    use_fs_snapshot: bool = True
    exclude_caches: bool = True
    dry_run: bool = False
    cpu_policy: CpuPolicy = field(default_factory=CpuPolicy)
    extra_backup_args: List[str] = field(default_factory=list)
    attribution: Dict[str, SourceAttribution] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate required fields and policy values."""

        for name in (
            "name",
            "repository",
            "password_file",
            "status_file",
            "log_file",
            "lock_file",
            "restic_executable",
            "restore_root",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError("{0} is required.".format(name))
        self.cpu_policy.validate()

    def to_public_dict(self) -> Dict[str, Any]:
        """Return non-secret effective configuration plus source attribution."""

        values: Dict[str, Any] = {
            "name": self.name,
            "repository": self.repository,
            "password_file": self.password_file,
            "sources_file": self.sources_file,
            "excludes_file": self.excludes_file,
            "status_file": self.status_file,
            "log_file": self.log_file,
            "lock_file": self.lock_file,
            "tag": self.tag,
            "restic_executable": self.restic_executable,
            "restore_root": self.restore_root,
            "use_fs_snapshot": self.use_fs_snapshot,
            "exclude_caches": self.exclude_caches,
            "dry_run": self.dry_run,
            "extra_backup_args": list(self.extra_backup_args),
            "cpu_policy": {
                "normal_threshold": self.cpu_policy.normal_threshold,
                "overdue_threshold": self.cpu_policy.overdue_threshold,
                "overdue_after_seconds": self.cpu_policy.overdue_after.total_seconds(),
                "sample_seconds": self.cpu_policy.sample_seconds,
                "retry_interval_seconds": self.cpu_policy.retry_interval.total_seconds(),
                "max_wait_seconds": self.cpu_policy.max_wait.total_seconds(),
            },
        }
        return {
            "values": values,
            "sources": {
                name: attribution.to_dict()
                for name, attribution in sorted(self.attribution.items())
            },
        }


_DEFAULTS: Dict[str, Any] = {
    "name": DEFAULT_TAG,
    "repository": DEFAULT_REPOSITORY,
    "password_file": DEFAULT_PASSWORD_FILE,
    "sources_file": DEFAULT_SOURCES_FILE,
    "excludes_file": DEFAULT_EXCLUDES_FILE,
    "status_file": DEFAULT_STATUS_FILE,
    "log_file": DEFAULT_LOG_FILE,
    "lock_file": DEFAULT_LOCK_FILE,
    "tag": DEFAULT_TAG,
    "restic_executable": DEFAULT_RESTIC_EXECUTABLE,
    "restore_root": DEFAULT_RESTORE_ROOT,
    "use_fs_snapshot": True,
    "exclude_caches": True,
    "dry_run": False,
    "not_backup_days": 3.0,
    "min_cpu_cutoff": 25.0,
    "max_cpu_cutoff": 85.0,
    "cpu_sample_seconds": 5.0,
    "cpu_check_interval_seconds": 300.0,
    "max_wait_minutes": 60.0,
    "extra_backup_args": [],
}

_ENVIRONMENT_FIELDS = {
    "repository": "BACKUP_MODULE_REPOSITORY",
    "password_file": "BACKUP_MODULE_PASSWORD_FILE",
    "sources_file": "BACKUP_MODULE_SOURCES_FILE",
    "excludes_file": "BACKUP_MODULE_EXCLUDES_FILE",
    "status_file": "BACKUP_MODULE_STATUS_FILE",
    "log_file": "BACKUP_MODULE_LOG_FILE",
    "lock_file": "BACKUP_MODULE_LOCK_FILE",
    "tag": "BACKUP_MODULE_TAG",
    "restic_executable": "BACKUP_MODULE_RESTIC_EXECUTABLE",
    "restore_root": "BACKUP_MODULE_DEFAULT_RESTORE_ROOT",
}

_PATH_FIELDS = {
    "password_file",
    "sources_file",
    "excludes_file",
    "status_file",
    "log_file",
    "lock_file",
    "restore_root",
}


def _is_windows_drive_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _is_remote_repository(value: str) -> bool:
    if _is_windows_drive_path(value) or value.startswith("\\\\"):
        return False
    return ":" in value


def _resolve_path(value: Optional[str], base_dir: Path, *, remote: bool = False) -> Optional[str]:
    if value is None or value == "":
        return value

    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    if remote and _is_remote_repository(expanded):
        return expanded
    if _is_windows_drive_path(expanded) or expanded.startswith("\\\\"):
        return expanded

    path = Path(expanded)
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def legacy_config_candidates(
    *,
    environment: Mapping[str, str],
    cwd: Path,
) -> List[Path]:
    """Return legacy JSON candidates in precedence order."""

    candidates: List[Path] = []
    environment_path = environment.get("BACKUP_MODULE_CONFIG")
    if environment_path:
        candidates.append(Path(os.path.expandvars(os.path.expanduser(environment_path))))
    candidates.extend(
        [
            Path(DEFAULT_CONFIG_PATH),
            cwd / "local_backup_config.json",
            cwd / "backup_config.json",
            cwd / "backup_module_config.json",
        ]
    )
    return candidates


def discover_legacy_config(
    explicit_path: Optional[str] = None,
    *,
    environment: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
) -> Optional[Path]:
    """Discover the legacy `backup_module` JSON configuration without writing files."""

    env = dict(os.environ if environment is None else environment)
    base = Path.cwd() if cwd is None else cwd

    if explicit_path:
        return Path(os.path.expandvars(os.path.expanduser(explicit_path))).resolve()

    for candidate in legacy_config_candidates(environment=env, cwd=base):
        if candidate.exists():
            return candidate.resolve()
    return None


def _apply_value(
    values: MutableMapping[str, Any],
    attribution: MutableMapping[str, SourceAttribution],
    name: str,
    value: Any,
    source: ValueSource,
    detail: str,
) -> None:
    values[name] = value
    attribution[name] = SourceAttribution(source=source, detail=detail)


def load_legacy_profile(
    explicit_config_path: Optional[str] = None,
    *,
    environment: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> Tuple[BackupProfile, Optional[Path]]:
    """Load effective legacy behavior into the canonical profile model.

    Precedence is defaults, environment variables, JSON configuration, then
    explicit overrides. This matches the historical `backup_module` behavior
    while exposing the origin of every effective value.
    """

    env = dict(os.environ if environment is None else environment)
    base = Path.cwd() if cwd is None else cwd
    values: Dict[str, Any] = {}
    attribution: Dict[str, SourceAttribution] = {}

    for name, value in _DEFAULTS.items():
        _apply_value(
            values,
            attribution,
            name,
            list(value) if isinstance(value, list) else value,
            ValueSource.DEFAULT,
            "legacy backup_module default",
        )

    for field_name, variable_name in _ENVIRONMENT_FIELDS.items():
        if variable_name in env:
            _apply_value(
                values,
                attribution,
                field_name,
                env[variable_name],
                ValueSource.ENVIRONMENT,
                variable_name,
            )

    config_path = discover_legacy_config(
        explicit_config_path,
        environment=env,
        cwd=base,
    )
    config_base = base
    if config_path is not None:
        if not config_path.exists():
            raise FileNotFoundError(
                "Legacy config file does not exist: {0}".format(config_path)
            )
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Legacy config must contain a JSON object.")
        config_base = config_path.parent

        field_aliases = {"default_restore_root": "restore_root"}
        for raw_name, value in payload.items():
            field_name = field_aliases.get(raw_name, raw_name)
            if field_name in values:
                _apply_value(
                    values,
                    attribution,
                    field_name,
                    value,
                    ValueSource.CONFIG_FILE,
                    str(config_path),
                )

    for name, value in dict(overrides or {}).items():
        normalized_name = "restore_root" if name == "default_restore_root" else name
        if normalized_name not in values:
            raise KeyError("Unknown profile override: {0}".format(name))
        _apply_value(
            values,
            attribution,
            normalized_name,
            value,
            ValueSource.EXPLICIT,
            "explicit override",
        )

    values["repository"] = _resolve_path(
        None if values["repository"] is None else str(values["repository"]),
        config_base,
        remote=True,
    )
    for field_name in _PATH_FIELDS:
        values[field_name] = _resolve_path(
            None if values[field_name] is None else str(values[field_name]),
            config_base,
        )

    policy = CpuPolicy(
        normal_threshold=float(values["min_cpu_cutoff"]),
        overdue_threshold=float(values["max_cpu_cutoff"]),
        overdue_after=timedelta(days=float(values["not_backup_days"])),
        sample_seconds=float(values["cpu_sample_seconds"]),
        retry_interval=timedelta(
            seconds=float(values["cpu_check_interval_seconds"])
        ),
        max_wait=timedelta(minutes=float(values["max_wait_minutes"])),
    )

    profile = BackupProfile(
        name=str(values["name"]),
        repository=str(values["repository"]),
        password_file=str(values["password_file"]),
        sources_file=(
            None if values["sources_file"] is None else str(values["sources_file"])
        ),
        excludes_file=(
            None
            if values["excludes_file"] is None
            else str(values["excludes_file"])
        ),
        status_file=str(values["status_file"]),
        log_file=str(values["log_file"]),
        lock_file=str(values["lock_file"]),
        tag=None if values["tag"] is None else str(values["tag"]),
        restic_executable=str(values["restic_executable"]),
        restore_root=str(values["restore_root"]),
        use_fs_snapshot=bool(values["use_fs_snapshot"]),
        exclude_caches=bool(values["exclude_caches"]),
        dry_run=bool(values["dry_run"]),
        cpu_policy=policy,
        extra_backup_args=[str(value) for value in values["extra_backup_args"]],
        attribution=attribution,
    )
    profile.validate()
    return profile, config_path


def read_path_list(path: Optional[str]) -> List[str]:
    """Read a newline-delimited source or exclusion file."""

    if not path:
        return []

    result: List[str] = []
    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        result.append(line)
    return result
