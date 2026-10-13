from __future__ import annotations

from typing import Any, Sequence

from .client import KavitaClient
from .matching import match_series_by_path
from .pending import Assignment, PendingAssignmentStore


def reconcile_assignments(
    store: PendingAssignmentStore,
    client: KavitaClient,
    *,
    kavita_url: str,
    path_maps: Sequence[tuple[str, str]] = (),
    apply: bool = False,
) -> list[dict[str, Any]]:
    """Preview or apply pending exact-path collection assignments for one server."""
    rows = store.load()
    series = client.list_series()
    output: list[dict[str, Any]] = []
    server_key = kavita_url.rstrip("/")
    changed = False
    for item in rows:
        if item.status == "applied" or item.kavita_url.rstrip("/") != server_key:
            continue
        match = match_series_by_path(item.expected_path, series, path_maps=path_maps)
        if match is None:
            item.reason = "no unique exact Kavita folder-path match; scan the library and retry"
            output.append(_result(item, applied=False, series=None))
            changed = True
            continue
        series_id = int(match["id"])
        operations = [client.add_series_to_collection(name, [series_id], apply=apply) for name in item.collections]
        output.append({**_result(item, applied=apply, series=match), "operations": operations})
        if apply:
            item.status = "applied"
            item.series_id = series_id
            item.series_name = str(match.get("name") or "")
            item.reason = ""
            changed = True
    if changed:
        store.update(rows)
    return output


def _result(item: Assignment, *, applied: bool, series: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "source_url": item.source_url,
        "expected_path": item.expected_path,
        "collections": list(item.collections),
        "status": "applied" if applied else "pending",
        "series_id": int(series["id"]) if series and series.get("id") is not None else None,
        "series_name": str(series.get("name") or "") if series else "",
        "reason": "" if series else item.reason,
    }
