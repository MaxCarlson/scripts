"""Provision and validate the shared local operator credential."""

from __future__ import annotations

import os
import re
import secrets
import stat
import subprocess
import csv
import io
from pathlib import Path


class CredentialError(RuntimeError):
    """Credential storage is missing, corrupt, or cannot be secured."""


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{64,}$")


def credential_path() -> Path:
    override = os.environ.get("RESOURCE_COORDINATOR_TOKEN_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".resource_coordinator" / "secrets" / "operator-token"


def _windows_user_sid() -> str:
    try:
        result = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        match = re.search(r"S-1-[0-9-]+", result.stdout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialError("Cannot identify the Windows account for credential ACLs") from exc
    if not match:
        raise CredentialError("Cannot identify the Windows account SID for credential ACLs")
    return match.group(0)


def _windows_user_name() -> str:
    try:
        result = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        return next(csv.reader(io.StringIO(result.stdout)))[0]
    except (OSError, subprocess.SubprocessError, StopIteration, IndexError) as exc:
        raise CredentialError("Cannot identify the Windows account for credential ACL checks") from exc


def _secure_path(path: Path) -> None:
    """Restrict the token directory/file to its owner and LocalSystem."""
    if os.name == "nt":
        sid = _windows_user_sid()
        is_dir = path.is_dir()
        flags = ("(OI)(CI)" if is_dir else "") + "(F)"
        try:
            subprocess.run(
                ["icacls.exe", str(path), "/reset"],
                check=True, capture_output=True, text=True, timeout=10,
            )
            subprocess.run(
                ["icacls.exe", str(path), "/inheritance:r", "/grant:r",
                 f"*{sid}:{flags}", f"*S-1-5-18:{flags}"],
                check=True, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CredentialError("Cannot restrict operator credential ACL to this user and SYSTEM") from exc
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def load_or_create_token() -> str:
    """Load the configured override or securely provision the shared token once."""
    override = os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN")
    if override:
        return override
    path = credential_path()
    if path.exists():
        return load_token()
    if os.name == "nt" and _windows_user_sid() == "S-1-5-18":
        raise CredentialError("Run a normal user CLI command once to provision the shared credential before SYSTEM startup")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _secure_path(path.parent)
        try:
            with path.open("x", encoding="ascii") as stream:
                token = secrets.token_urlsafe(48)
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
        _secure_path(path)
        token = path.read_text(encoding="ascii")
    except CredentialError:
        if 'token' in locals() and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        raise
    except (OSError, UnicodeError) as exc:
        raise CredentialError(f"Cannot read or provision operator credential at {path}") from exc
    if not _TOKEN_RE.fullmatch(token):
        raise CredentialError(f"Operator credential at {path} is invalid; use explicit auth reinitialize")
    return token


def load_token() -> str:
    """Read an existing credential without creating or replacing anything."""
    override = os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN")
    if override:
        return override
    path = credential_path()
    try:
        token = path.read_text(encoding="ascii")
    except (OSError, UnicodeError, CredentialError) as exc:
        raise CredentialError(f"Cannot load operator credential at {path}") from exc
    if not _TOKEN_RE.fullmatch(token):
        raise CredentialError(f"Operator credential at {path} is invalid; use explicit auth reinitialize")
    return token


def _coordinator_is_running(host: str = "127.0.0.1", port: int = 1235) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def reinitialize_token(*, coordinator_is_running: bool | None = None) -> str:
    """Explicitly rotate while coordinator is stopped; never silently replace."""
    if coordinator_is_running is None:
        coordinator_is_running = _coordinator_is_running()
    if coordinator_is_running:
        raise CredentialError("Stop the coordinator safely before auth reinitialize")
    if os.name == "nt" and _windows_user_sid() == "S-1-5-18":
        raise CredentialError("Run auth reinitialize as the interactive user so its ACL remains available")
    path = credential_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _secure_path(path.parent)
        token = secrets.token_urlsafe(48)
        temporary = path.with_name(path.name + ".new")
        temporary.write_text(token, encoding="ascii")
        _secure_path(temporary)
        os.replace(temporary, path)
        _secure_path(path)
        return token
    except (OSError, CredentialError) as exc:
        raise CredentialError(f"Cannot reinitialize operator credential at {path}: {exc}") from exc


def repair_permissions() -> None:
    """Repair ACLs without changing the credential value."""
    path = credential_path()
    if os.name == "nt" and _windows_user_sid() == "S-1-5-18":
        raise CredentialError("Run auth repair as the interactive user so its ACL remains available")
    if not path.is_file():
        raise CredentialError(f"No operator credential at {path}; use auth reinitialize")
    _secure_path(path.parent)
    _secure_path(path)
    try:
        token = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise CredentialError(f"Cannot read operator credential at {path}") from exc
    if not _TOKEN_RE.fullmatch(token):
        raise CredentialError(f"Operator credential at {path} is invalid; use auth reinitialize")


def _acl_is_restricted(path: Path) -> bool:
    if os.name == "nt":
        try:
            output = subprocess.run(
                ["icacls.exe", str(path)], check=True, capture_output=True, text=True, timeout=5
            ).stdout
            first = output.splitlines()[0].partition(str(path))[-1]
            principals = re.findall(r"([^\r\n]+?):\(", first)
            for line in output.splitlines()[1:]:
                match = re.search(r"([^\r\n]+?):\(", line)
                if match:
                    principals.append(match.group(1).strip())
            allowed = {"nt authority\\system", _windows_user_name().casefold()}
            return bool(principals) and {principal.casefold().strip() for principal in principals} == allowed
        except (OSError, subprocess.SubprocessError, CredentialError):
            return False
    try:
        return stat.S_IMODE(path.stat().st_mode) == 0o600
    except OSError:
        return False


def doctor() -> dict[str, object]:
    """Offline credential check; does not contact the coordinator or alter files."""
    path = credential_path()
    env_token = os.environ.get("RESOURCE_COORDINATOR_OPERATOR_TOKEN")
    report: dict[str, object] = {
        "credential_path": str(path),
        "credential_file_exists": path.is_file(),
        "credential_file_readable": False,
        "credential_valid": False,
        "environment_override_present": bool(env_token),
        "environment_override_matches_file": None,
        "acl_restricted": None,
    }
    try:
        token = path.read_text(encoding="ascii")
        report["credential_file_readable"] = True
        report["credential_valid"] = bool(_TOKEN_RE.fullmatch(token))
        if env_token:
            report["environment_override_matches_file"] = secrets.compare_digest(env_token, token)
    except (OSError, UnicodeError):
        pass
    if path.is_file():
        report["acl_restricted"] = _acl_is_restricted(path)
    return report
