from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener


class KavitaError(RuntimeError):
    """An HTTP or response-shape error from Kavita."""


@dataclass(frozen=True, slots=True)
class KavitaConfig:
    base_url: str
    api_key: str
    timeout: float = 30.0

    def __post_init__(self) -> None:
        parts = urlsplit(self.base_url.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("Kavita base URL must be an absolute HTTP or HTTPS URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Kavita base URL cannot contain credentials, a query, or a fragment")
        if not self.api_key:
            raise ValueError("Kavita API key is empty")
        if self.timeout <= 0:
            raise ValueError("Kavita timeout must be positive")

    @classmethod
    def from_env(
        cls,
        base_url: str,
        *,
        api_key_env: str = "KAVITA_API_KEY",
        timeout: float = 30.0,
        environ: Mapping[str, str] | None = None,
    ) -> "KavitaConfig":
        source = os.environ if environ is None else environ
        if not api_key_env.strip():
            raise ValueError("Kavita API key environment variable name is empty")
        return cls(base_url=base_url, api_key=source.get(api_key_env, ""), timeout=timeout)


class KavitaClient:
    """Small dependency-free client for Kavita's Auth Key API."""

    def __init__(self, config: KavitaConfig, *, opener: Any | None = None) -> None:
        self.config = config
        self._opener = opener or build_opener()
        self._base = config.base_url.rstrip("/") + "/api/"

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
        headers = {"x-api-key": self.config.api_key, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self._base + path.lstrip("/"), data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.config.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace").strip()
            raise KavitaError(f"Kavita API {method} {path} failed with HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError) as exc:
            raise KavitaError(f"Kavita API {method} {path} failed: {exc}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KavitaError(f"Kavita API {method} {path} returned invalid JSON") from exc

    @staticmethod
    def _rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            value = payload
        elif isinstance(payload, dict):
            value = payload.get("items", payload.get("result", payload.get("data", [])))
        else:
            value = []
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def list_series(self, *, page_size: int = 500) -> list[dict[str, Any]]:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._request(
                "POST", "series/v2?" + urlencode({"pageNumber": page, "pageSize": page_size}), {}
            )
            batch = self._rows(payload)
            rows.extend(batch)
            if len(batch) < page_size:
                return rows
            page += 1

    def list_collections(self) -> list[dict[str, Any]]:
        return self._rows(self._request("GET", "collection?ownedOnly=true"))

    def list_reading_lists(self, *, page_size: int = 500) -> list[dict[str, Any]]:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urlencode({"pageNumber": page, "pageSize": page_size, "includePromoted": "false"})
            batch = self._rows(self._request("POST", f"readinglist/lists?{query}", {}))
            rows.extend(batch)
            if len(batch) < page_size:
                return rows
            page += 1

    def create_collection(self, name: str, *, apply: bool = False) -> dict[str, Any]:
        title = _required_name(name)
        if not apply:
            return {"action": "create_collection", "collection": title, "applied": False}
        existing = _named(self.list_collections(), title)
        if existing is None:
            existing = self._create_collection(title)
        return {"action": "create_collection", "collection": title, "id": existing.get("id"), "applied": True}

    def create_reading_list(self, name: str, *, apply: bool = False) -> dict[str, Any]:
        title = _required_name(name)
        if not apply:
            return {"action": "create_reading_list", "reading_list": title, "applied": False}
        existing = _named(self.list_reading_lists(), title)
        if existing is None:
            existing = self._create_reading_list(title)
        if not isinstance(existing, dict) or not existing.get("id"):
            raise KavitaError(f"Kavita did not return the newly created reading list {title!r}")
        return {"action": "create_reading_list", "reading_list": title, "id": existing.get("id"), "applied": True}

    def _create_collection(self, title: str) -> dict[str, Any]:
        self._request(
            "POST",
            "collection/update-for-series",
            {"collectionTagId": 0, "collectionTagTitle": title, "seriesIds": []},
        )
        existing = _named(self.list_collections(), title)
        if existing is None:
            raise KavitaError(f"Kavita did not return the newly created collection {title!r}")
        return existing

    def _create_reading_list(self, title: str) -> dict[str, Any]:
        result = self._request("POST", "readinglist/create", {"title": title})
        if isinstance(result, dict) and result.get("id"):
            return result
        existing = _named(self.list_reading_lists(), title)
        if existing is None:
            raise KavitaError(f"Kavita did not return the newly created reading list {title!r}")
        return existing

    def add_series_to_collection(
        self, collection_name: str, series_ids: list[int], *, apply: bool = False
    ) -> dict[str, Any]:
        name = _required_name(collection_name)
        ids = _series_ids(series_ids)
        if not apply:
            return {"action": "add_to_collection", "collection": name, "series_ids": ids, "applied": False}
        collection = _named(self.list_collections(), name)
        if collection is None:
            collection = self._create_collection(name)
        if collection is None:
            raise KavitaError(f"Kavita did not return the newly created collection {name!r}")
        if ids:
            self._request(
                "POST",
                "collection/update-for-series",
                {"collectionTagId": int(collection["id"]), "collectionTagTitle": name, "seriesIds": ids},
            )
        return {"action": "add_to_collection", "collection": name, "series_ids": ids, "applied": True}

    def add_series_to_reading_list(
        self, reading_list_name: str, series_ids: list[int], *, apply: bool = False
    ) -> dict[str, Any]:
        name = _required_name(reading_list_name)
        ids = _series_ids(series_ids)
        if not apply:
            return {"action": "add_to_reading_list", "reading_list": name, "series_ids": ids, "applied": False}
        row = _named(self.list_reading_lists(), name)
        if row is None:
            row = self._create_reading_list(name)
        if not isinstance(row, dict) or not row.get("id"):
            raise KavitaError(f"Kavita did not return the newly created reading list {name!r}")
        if ids:
            self._request(
                "POST",
                "readinglist/update-by-multiple-series",
                {"readingListId": int(row["id"]), "seriesIds": ids},
            )
        return {"action": "add_to_reading_list", "reading_list": name, "series_ids": ids, "applied": True}


def _required_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Kavita collection or reading-list name is empty")
    return name


def _series_ids(values: list[int]) -> list[int]:
    ids = list(dict.fromkeys(int(value) for value in values))
    if any(value <= 0 for value in ids):
        raise ValueError("Kavita series IDs must be positive integers")
    return ids


def _named(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matches = [row for row in rows if str(row.get("title") or row.get("name") or "").casefold() == name.casefold()]
    if len(matches) > 1:
        raise KavitaError(f"Kavita returned multiple collections or reading lists named {name!r}")
    return matches[0] if matches else None
