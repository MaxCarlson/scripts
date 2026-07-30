from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import worker_core as _core
from .covers import (
    CoverResult,
    apply_kavita_cover,
    identity_without_metadata,
    install_download_cover,
    parse_path_maps,
    snapshot_top_level,
    supports_cover_url,
    tree_stats_without_metadata,
)

build_parser = _core.build_parser
_tree_stats = tree_stats_without_metadata
_identity = identity_without_metadata


def __getattr__(name: str) -> object:
    return getattr(_core, name)


def _enabled(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"", "0", "false", "no", "off"}


def _log_cover_result(raw_log: Path, result: CoverResult | str) -> None:
    payload: dict[str, Any]
    if isinstance(result, CoverResult):
        payload = {"event": "cover", **asdict(result)}
    else:
        payload = {"event": "cover", "status": "failed", "message": result}
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    with raw_log.open("a", encoding="utf-8", errors="replace") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _apply_kavita_from_environment(result: CoverResult) -> CoverResult:
    if not _enabled("MANGADL_APPLY_KAVITA_COVERS"):
        return result
    if not result.folder:
        raise RuntimeError("cover result does not identify a local series folder")

    base_url = os.environ.get("MANGADL_KAVITA_URL", "").strip()
    key_env = os.environ.get("MANGADL_KAVITA_API_KEY_ENV", "KAVITA_API_KEY").strip()
    api_key = os.environ.get(key_env, "") if key_env else ""
    if not base_url or not api_key:
        raise RuntimeError(
            "automatic Kavita cover application requires MANGADL_KAVITA_URL and "
            f"a non-empty {key_env or 'Kavita API key'} environment variable"
        )

    raw_maps = os.environ.get("MANGADL_KAVITA_PATH_MAPS", "[]")
    try:
        decoded = json.loads(raw_maps)
    except json.JSONDecodeError as exc:
        raise RuntimeError("MANGADL_KAVITA_PATH_MAPS is not valid JSON") from exc
    if not isinstance(decoded, list) or not all(isinstance(value, str) for value in decoded):
        raise RuntimeError("MANGADL_KAVITA_PATH_MAPS must be a JSON list of LOCAL=KAVITA strings")

    return apply_kavita_cover(
        result,
        Path(result.folder),
        kavita_url=base_url,
        api_key=api_key,
        path_maps=parse_path_maps(decoded),
    )


def run(args: argparse.Namespace) -> int:
    destination = Path(args.destination).expanduser().resolve()
    before = snapshot_top_level(destination)
    _core._tree_stats = tree_stats_without_metadata
    _core._identity = identity_without_metadata
    returncode = _core.run(args)
    if (
        returncode != 0
        or not supports_cover_url(args.url)
        or not _enabled("MANGADL_DOWNLOAD_COVERS", default=True)
    ):
        return returncode

    try:
        result = install_download_cover(
            args.url,
            destination,
            before,
            cookies=Path(args.cookies).expanduser().resolve() if args.cookies else None,
        )
        result = _apply_kavita_from_environment(result)
        _log_cover_result(Path(args.raw_log), result)
    except Exception as exc:  # A cover failure must never invalidate a completed gallery download.
        _log_cover_result(Path(args.raw_log), f"{type(exc).__name__}: {exc}")
    return returncode


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
