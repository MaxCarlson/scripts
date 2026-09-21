from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Callable, Iterable

from .gallery_auth import ProfileStore

RECONCILE_MARKER = "__MANGADL_RECONCILE_KEY__"


def partial_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def candidate_state_databases(destination: Path, supplied: Iterable[Path] = ()) -> tuple[Path, ...]:
    destination = destination.expanduser().resolve()
    candidates = [
        *(path.expanduser().resolve() for path in supplied),
        destination / ".mangadl" / "state.sqlite3",
        destination / "mangadl-state.sqlite3",
    ]
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique and candidate.is_file():
            unique.append(candidate)
    return tuple(unique)


def state_url_candidates(
    destination: Path,
    supplied: Iterable[Path] = (),
) -> dict[str, tuple[str, ...]]:
    matches: dict[str, set[str]] = {}
    for database in candidate_state_databases(destination, supplied):
        for query in ("?mode=ro", "?mode=ro&immutable=1"):
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(database.as_uri() + query, uri=True)
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
                ).fetchone()
                if table is None:
                    break
                for (url,) in connection.execute(
                    "SELECT DISTINCT canonical_url FROM jobs WHERE canonical_url <> ''"
                ):
                    value = str(url)
                    matches.setdefault(partial_key(value), set()).add(value)
                break
            except sqlite3.Error:
                continue
            finally:
                if connection is not None:
                    connection.close()
    return {key: tuple(sorted(values)) for key, values in matches.items()}


def parse_url_overrides(values: Iterable[str]) -> tuple[dict[str, str], tuple[str, ...]]:
    keyed: dict[str, str] = {}
    unkeyed: list[str] = []
    for value in values:
        key, separator, url = value.partition("=")
        if separator and len(key) == 12 and url.startswith(("http://", "https://")):
            keyed[key] = url
        elif value.startswith(("http://", "https://")):
            unkeyed.append(value)
        else:
            raise ValueError(
                "legacy URL overrides must be URL or PARTIAL_KEY=URL: " + value
            )
    return keyed, tuple(unkeyed)


def resolve_owner_urls(
    destination: Path,
    owners: Iterable[Path],
    *,
    state_databases: Iterable[Path] = (),
    overrides: Iterable[str] = (),
) -> dict[Path, str]:
    selected = tuple(owner.expanduser().resolve() for owner in owners)
    keyed, unkeyed = parse_url_overrides(overrides)
    if unkeyed:
        unresolved_for_override = [owner for owner in selected if owner.name not in keyed]
        if len(unkeyed) != 1 or len(unresolved_for_override) != 1:
            raise ValueError(
                "an unkeyed --url override requires exactly one unresolved selected partial"
            )
        keyed[unresolved_for_override[0].name] = unkeyed[0]

    state_matches = state_url_candidates(destination, state_databases)
    resolved: dict[Path, str] = {}
    for owner in selected:
        if owner.name in keyed:
            url = keyed[owner.name]
            if partial_key(url) != owner.name:
                raise ValueError(
                    f"URL does not match partial key {owner.name}: {url}"
                )
            resolved[owner] = url
            continue
        candidates = state_matches.get(owner.name, ())
        if len(candidates) == 1:
            resolved[owner] = candidates[0]
        elif not candidates:
            raise ValueError(
                f"no URL was found for legacy partial {owner.name}; supply --url {owner.name}=URL"
            )
        else:
            raise ValueError(
                f"legacy partial {owner.name} has ambiguous URLs: {', '.join(candidates)}"
            )
    return resolved


def reconstruct_archive_keys(
    url: str,
    *,
    gallery_config: Path | None = None,
    cookies: Path | None = None,
    cookies_browser: str | None = None,
    user_agent: str | None = None,
    auth_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> set[str]:
    """Enumerate exact gallery-dl archive keys without downloading media."""
    with tempfile.TemporaryDirectory(prefix="mangadl-reconcile-") as temporary:
        root = Path(temporary)
        command = [
            sys.executable,
            "-m",
            "gallery_dl",
            "--no-input",
            "--destination",
            str(root / "output"),
            "--download-archive",
            str(root / "empty-archive.sqlite3"),
            "--print",
            f"prepare-after:{RECONCILE_MARKER}{{_archive_key}}",
        ]
        if gallery_config:
            command.extend(["--config", str(gallery_config)])
        if cookies:
            command.extend(["--cookies", str(cookies)])
        if cookies_browser:
            command.extend(["--cookies-from-browser", cookies_browser])
        selected_user_agent = user_agent
        if not any((gallery_config, cookies, cookies_browser)):
            managed = ProfileStore(auth_dir).load(url)
            if managed:
                command.extend(["--cookies", str(managed.cookie_path)])
                selected_user_agent = selected_user_agent or managed.user_agent
        if selected_user_agent:
            command.extend(["--user-agent", selected_user_agent])
        command.append(url)

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        keys: set[str] = set()
        tail: deque[str] = deque(maxlen=12)
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if line.startswith(RECONCILE_MARKER):
                key = line.removeprefix(RECONCILE_MARKER).strip()
                if key:
                    keys.add(key)
                    if progress and len(keys) % 500 == 0:
                        progress(f"Reconstructed {len(keys):,} archive keys for {url}")
            elif line:
                tail.append(line)
        returncode = process.wait()
        if returncode != 0:
            detail = " | ".join(tail) or f"gallery-dl exited {returncode}"
            raise RuntimeError(f"failed to reconstruct archive keys for {url}: {detail}")
        if not keys:
            raise RuntimeError(f"gallery-dl reconstructed no archive keys for {url}")
        if progress:
            progress(f"Reconstructed {len(keys):,} archive keys for {url}")
        return keys


def metadata_url(owner: Path) -> tuple[str | None, str | None, str | None]:
    path = owner / ".mangadl-partial.json"
    if not path.is_file():
        return None, None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None, None, None
    return (
        str(payload.get("url") or "") or None,
        str(payload.get("backend") or "") or None,
        str(payload.get("archive") or "") or None,
    )
