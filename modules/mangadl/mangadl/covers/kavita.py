from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence
from urllib.request import Request, build_opener

from .constants import COVER_APPLIED_NAME, COVER_PENDING_NAME, METADATA_DIR_NAME, SCHEMA_VERSION
from .models import CoverResult
from .util import atomic_write_json, basename_any, normalize_fs_path, normalize_name


class KavitaClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 45.0,
        path_maps: Sequence[tuple[str, str]] = (),
        opener: object | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Kavita API key is empty")
        self.base_url = base_url.rstrip("/") + "/api/"
        self.api_key = api_key
        self.timeout = timeout
        self.path_maps = tuple(path_maps)
        self.opener = opener or build_opener()

    def _open(self, request: Request) -> BinaryIO:
        request.add_header("x-api-key", self.api_key)
        request.add_header("User-Agent", "mangadl-cover-manager/1")
        return self.opener.open(request, timeout=self.timeout)  # type: ignore[attr-defined,no-any-return]

    def _json(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(dict(payload)).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path.lstrip("/"), data=data, headers=headers, method=method)
        with self._open(request) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None

    def list_series(self) -> list[dict[str, Any]]:
        page = 1
        page_size = 500
        all_series: list[dict[str, Any]] = []
        while True:
            payload = self._json("POST", f"series/v2?pageNumber={page}&pageSize={page_size}", {})
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                rows = payload.get("items") or payload.get("result") or payload.get("data") or []
            else:
                rows = []
            rows = [row for row in rows if isinstance(row, dict)]
            all_series.extend(rows)
            if len(rows) < page_size:
                return all_series
            page += 1

    def _mapped_path(self, folder: Path) -> str:
        value = str(folder.resolve())
        normalized = normalize_fs_path(value)
        for local, remote in self.path_maps:
            local_normal = normalize_fs_path(local)
            if normalized == local_normal or normalized.startswith(local_normal + "/"):
                suffix = normalized[len(local_normal) :].lstrip("/")
                return remote.rstrip("/\\") + ("/" + suffix if suffix else "")
        return value

    def match_series(self, folder: Path, series: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
        mapped = normalize_fs_path(self._mapped_path(folder))
        exact = [
            row
            for row in series
            if mapped
            in {
                normalize_fs_path(str(row.get("folderPath") or "")),
                normalize_fs_path(str(row.get("lowestFolderPath") or "")),
            }
        ]
        if len(exact) == 1:
            return exact[0]
        by_name = [
            row
            for row in series
            if normalize_name(str(row.get("name") or "")) == normalize_name(folder.name)
            or basename_any(str(row.get("folderPath") or "")).casefold() == folder.name.casefold()
        ]
        return by_name[0] if len(by_name) == 1 else None

    def _upload_file(self, path: Path) -> str:
        boundary = "----mangadl" + hashlib.sha256(os.urandom(32)).hexdigest()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = Request(
            self.base_url + "upload/upload-by-file",
            data=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with self._open(request) as response:
            raw = response.read().decode("utf-8").strip()
        try:
            value = json.loads(raw)
            return str(value)
        except json.JSONDecodeError:
            return raw.strip('"')

    def apply_cover(self, series_id: int, cover: Path) -> None:
        staged = self._upload_file(cover)
        if not staged:
            raise RuntimeError("Kavita returned an empty staged cover filename")
        self._json("POST", "upload/series", {"id": series_id, "fileName": staged, "lockCover": True})


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


def apply_kavita_cover(
    result: CoverResult,
    folder: Path,
    *,
    kavita_url: str,
    api_key: str,
    timeout: float = 45.0,
    path_maps: Sequence[tuple[str, str]] = (),
    client: KavitaClient | None = None,
    series_rows: Sequence[dict[str, Any]] | None = None,
) -> CoverResult:
    if not result.cover_file:
        raise ValueError("cannot apply a cover to Kavita without a local cover file")
    cover = Path(result.cover_file)
    if not cover.is_file():
        raise OSError(f"managed cover file does not exist: {cover}")

    active = client or KavitaClient(kavita_url, api_key, timeout=timeout, path_maps=path_maps)
    series = active.match_series(folder, series_rows if series_rows is not None else active.list_series())
    metadata_dir = folder / METADATA_DIR_NAME
    pending_path = metadata_dir / COVER_PENDING_NAME
    if series is None:
        pending = {
            "schema_version": SCHEMA_VERSION,
            "kavita_url": kavita_url,
            "local_series_path": str(folder),
            "cover_file": str(cover),
            "source_url": result.url,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "reason": "Kavita series match was not unique or the series has not been indexed yet",
        }
        atomic_write_json(pending_path, pending)
        return CoverResult(**{**asdict(result), "status": "kavita_pending", "message": pending["reason"]})

    series_id = int(series["id"])
    active.apply_cover(series_id, cover)
    applied = {
        "schema_version": SCHEMA_VERSION,
        "kavita_url": kavita_url,
        "series_id": series_id,
        "series_name": series.get("name"),
        "cover_file": str(cover),
        "source_url": result.url,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "locked": True,
    }
    atomic_write_json(metadata_dir / COVER_APPLIED_NAME, applied)
    pending_path.unlink(missing_ok=True)
    return CoverResult(
        **{**asdict(result), "status": "applied_kavita", "kavita_series_id": series_id, "message": ""}
    )
