"""Runtime environment identity and Windows/WSL2 storage safety guards."""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import socket
from pathlib import Path
from typing import Any

from .errors import ContinuityError, ErrorCode
from .identifiers import now_utc_iso
from .models import EnvironmentInfo, RuntimeKind

HOME_ENV_VAR = "AGENT_CONTINUITY_HOME"
_MNT_DRIVE_RE = re.compile(r"^/mnt/[a-zA-Z](?:/|$)")


def resolve_home_dir(home_override: Path | str | None = None) -> Path:
    """Resolve the agent_continuity state directory."""
    if home_override is not None:
        return Path(home_override).expanduser().resolve()
    env_home = os.environ.get(HOME_ENV_VAR)
    if env_home:
        return Path(env_home).expanduser().resolve()
    return (Path.home() / ".agent_continuity").resolve()


def is_wsl2() -> bool:
    """Return True when running inside WSL2."""
    if os.name == "nt":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    release = platform.uname().release.lower()
    return "microsoft" in release


def detect_runtime_kind() -> str:
    """Return the normalized runtime kind for the active Python process."""
    system = platform.system().lower()
    if system == "windows":
        return RuntimeKind.WINDOWS.value
    if is_wsl2():
        return RuntimeKind.WSL.value
    if system == "darwin":
        return RuntimeKind.MACOS.value
    return RuntimeKind.LINUX.value


def is_windows_mount_path(path: Path) -> bool:
    """Return True if a POSIX path points into a Windows NTFS mount under /mnt/<drive>."""
    if os.name == "nt":
        return False
    raw = str(path).replace("\\", "/")
    resolved = str(path.resolve()).replace("\\", "/") if path.exists() else raw
    return bool(_MNT_DRIVE_RE.match(raw) or _MNT_DRIVE_RE.match(resolved))


def assert_sqlite_writer_allowed(db_path: Path, *, allow_unsafe_cross_os: bool = False) -> None:
    """
    Prevent WSL2 processes from opening a Windows-owned SQLite database over /mnt/<drive> for writes.

    Master Plan §8.5 & ADR-001 require a single designated SQLite writer; WSL2 runtimes must
    write events to their local event spool rather than mutating a Windows SQLite file over DrvFs.
    """
    if allow_unsafe_cross_os:
        return
    if is_wsl2() and is_windows_mount_path(db_path):
        raise ContinuityError(
            ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
            (
                f"Refusing to open Windows-mounted SQLite index {db_path} for writes from WSL2. "
                "Emit events to the WSL2 local spool and run materialization/rebuild from Windows."
            ),
            {"db_path": str(db_path), "runtime_kind": detect_runtime_kind()},
        )


def load_config(home_dir: Path) -> dict[str, Any]:
    """Load optional configuration from <home_dir>/config.json."""
    cfg_path = home_dir / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuityError(
            ErrorCode.METADATA_INACCESSIBLE,
            f"Failed to read configuration file {cfg_path}: {exc}",
            {"path": str(cfg_path)},
        ) from exc


def _sanitize_token(value: str, max_len: int = 12) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", value.lower())
    return cleaned[:max_len] or "host"


def _build_local_environment() -> EnvironmentInfo:
    runtime_kind = detect_runtime_kind()
    hostname = socket.gethostname() or "unknown"
    distro = os.environ.get("WSL_DISTRO_NAME") if runtime_kind == RuntimeKind.WSL.value else None
    suffix = secrets.token_hex(2)
    if runtime_kind == RuntimeKind.WINDOWS.value:
        env_id = f"env_win_{_sanitize_token(hostname, 8)}_{suffix}"
        label = f"Windows ({hostname})"
    elif runtime_kind == RuntimeKind.WSL.value:
        distro_tok = _sanitize_token(distro or "wsl", 10)
        env_id = f"env_wsl_{distro_tok}_{suffix}"
        label = f"WSL {distro}" if distro else f"WSL ({hostname})"
    else:
        env_id = f"env_{runtime_kind}_{_sanitize_token(hostname, 8)}_{suffix}"
        label = f"{runtime_kind.title()} ({hostname})"
    ts = now_utc_iso()
    return EnvironmentInfo(
        environment_id=env_id,
        runtime_kind=runtime_kind,
        distro=distro,
        hostname=hostname,
        label=label,
        created_at=ts,
        last_seen_at=ts,
    )


def load_or_create_environment(home_dir: Path, *, persist: bool = True) -> EnvironmentInfo:
    """
    Load the stable local environment identity from <home_dir>/environment.json.

    When persist=False (used by dry-run previews), an uninitialized environment is computed
    in memory without creating files on disk.
    """
    env_file = home_dir / "environment.json"
    if env_file.exists():
        try:
            raw = json.loads(env_file.read_text(encoding="utf-8"))
            return EnvironmentInfo(
                environment_id=str(raw["environment_id"]),
                runtime_kind=str(raw["runtime_kind"]),
                distro=raw.get("distro"),
                hostname=str(raw.get("hostname", "")),
                label=str(raw.get("label", raw["environment_id"])),
                created_at=str(raw.get("created_at", now_utc_iso())),
                last_seen_at=str(raw.get("last_seen_at", now_utc_iso())),
            )
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise ContinuityError(
                ErrorCode.METADATA_INACCESSIBLE,
                f"Corrupt environment metadata at {env_file}: {exc}",
                {"path": str(env_file)},
            ) from exc

    env = _build_local_environment()
    if persist:
        home_dir.mkdir(parents=True, exist_ok=True)
        tmp = env_file.with_name(f".environment.{os.getpid()}.{secrets.token_hex(3)}.tmp")
        tmp.write_text(json.dumps(env.to_dict(), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, env_file)
    return env


def resolve_environment_selector(
    selector: str | None,
    known_environments: list[EnvironmentInfo],
    local_env: EnvironmentInfo,
) -> EnvironmentInfo:
    """
    Resolve a CLI environment selector (-e/--environment) to a concrete EnvironmentInfo.

    Supports exact environment_id, 'local', 'windows'/'win', 'wsl', 'wsl:<distro>', or distro name.
    When an explicit cross-environment selector like 'wsl' or 'windows' is passed before any session
    has been registered in that environment, synthesizes a deterministic logical environment ID.
    """
    if not selector or selector.strip().lower() == "local":
        return local_env

    raw = selector.strip()
    lower = raw.lower()
    if lower == "win":
        lower = "windows"

    candidates = list(known_environments)
    if all(e.environment_id != local_env.environment_id for e in candidates):
        candidates.append(local_env)

    # 1. Exact ID match
    for env in candidates:
        if env.environment_id == raw:
            return env

    # 2. Match wsl:<distro>
    if lower.startswith("wsl:"):
        distro_q = lower.split(":", 1)[1].strip()
        matches = [
            e
            for e in candidates
            if e.runtime_kind == RuntimeKind.WSL.value and (e.distro or "").lower() == distro_q
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ContinuityError(
                ErrorCode.ENVIRONMENT_AMBIGUOUS,
                f"Multiple WSL environments match {raw!r}; specify exact environment_id.",
                {"matches": [m.environment_id for m in matches]},
            )
        ts = now_utc_iso()
        distro_name = raw.split(":", 1)[1].strip() or "Ubuntu"
        return EnvironmentInfo(
            environment_id=f"env_wsl_{_sanitize_token(distro_name, 10)}",
            runtime_kind=RuntimeKind.WSL.value,
            distro=distro_name,
            hostname="",
            label=f"WSL {distro_name}",
            created_at=ts,
            last_seen_at=ts,
        )

    # 3. Match runtime_kind ('windows' or 'wsl') or distro name
    matches = [
        e
        for e in candidates
        if e.runtime_kind.lower() == lower or (e.distro and e.distro.lower() == lower)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ContinuityError(
            ErrorCode.ENVIRONMENT_AMBIGUOUS,
            f"Multiple environments match {raw!r}; specify exact environment_id.",
            {"matches": [m.environment_id for m in matches]},
        )

    # 4. Synthesize explicit named/typed environment for manual registration when none exists yet
    ts = now_utc_iso()
    if lower == RuntimeKind.WINDOWS.value:
        return EnvironmentInfo(
            environment_id="env_win_manual",
            runtime_kind=RuntimeKind.WINDOWS.value,
            distro=None,
            hostname="",
            label="Windows",
            created_at=ts,
            last_seen_at=ts,
        )
    if lower == RuntimeKind.WSL.value:
        return EnvironmentInfo(
            environment_id="env_wsl_manual",
            runtime_kind=RuntimeKind.WSL.value,
            distro="Ubuntu",
            hostname="",
            label="WSL Ubuntu",
            created_at=ts,
            last_seen_at=ts,
        )

    # Treat unknown explicit token as a literal custom environment_id
    return EnvironmentInfo(
        environment_id=raw,
        runtime_kind=local_env.runtime_kind if raw == local_env.environment_id else "unknown",
        distro=None,
        hostname="",
        label=raw,
        created_at=ts,
        last_seen_at=ts,
    )
