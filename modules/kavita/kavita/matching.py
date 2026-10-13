from __future__ import annotations

import ntpath
from pathlib import Path
from typing import Any, Sequence


def normalize_kavita_path(value: str | Path) -> str:
    return str(value).strip().replace("\\", "/").rstrip("/")


def _path_key(value: str) -> str:
    drive, _ = ntpath.splitdrive(value)
    return value.casefold() if drive or value.startswith("//") else value


def map_local_path(path: str | Path, path_maps: Sequence[tuple[str, str]] = ()) -> str:
    local = normalize_kavita_path(path)
    for source, target in path_maps:
        normalized_source = normalize_kavita_path(source)
        if _path_key(local) == _path_key(normalized_source) or _path_key(local).startswith(_path_key(normalized_source) + "/"):
            suffix = local[len(normalized_source) :].lstrip("/")
            return normalize_kavita_path(target) + ("/" + suffix if suffix else "")
    return local


def parse_path_maps(values: Sequence[str]) -> list[tuple[str, str]]:
    mappings: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid Kavita path map {value!r}; expected LOCAL=KAVITA")
        local, remote = value.split("=", 1)
        if not local.strip() or not remote.strip():
            raise ValueError(f"invalid Kavita path map {value!r}; expected non-empty LOCAL=KAVITA")
        mappings.append((local.strip(), remote.strip()))
    return mappings


def match_series_by_path(
    path: str | Path,
    series: Sequence[dict[str, Any]],
    *,
    path_maps: Sequence[tuple[str, str]] = (),
) -> dict[str, Any] | None:
    """Return a unique exact folder-path match; ambiguous paths never match."""
    expected = map_local_path(path, path_maps)
    matches = []
    for row in series:
        candidates = [
            normalize_kavita_path(str(row.get(field) or ""))
            for field in ("folderPath", "lowestFolderPath")
        ]
        if any(_path_key(expected) == _path_key(candidate) for candidate in candidates):
            matches.append(row)
    return matches[0] if len(matches) == 1 else None
