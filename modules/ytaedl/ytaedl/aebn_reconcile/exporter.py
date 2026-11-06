"""Export human-reviewable reconciliation state as JSON or CSV."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from .store import ReconciliationStore, SCHEMA_VERSION


def export_report(database_path: Path | str, *, format: str = "json", output: Path | str | None = None) -> None:
    if format not in {"json", "csv"}:
        raise ValueError("format must be json or csv")
    stream = Path(output).open("w", encoding="utf-8", newline="") if output else sys.stdout
    close = output is not None
    try:
        with ReconciliationStore(database_path) as store:
            if format == "json":
                data = {"schema_version": SCHEMA_VERSION}
                for table in ("movies", "requested_scenes", "scene_sources", "media_candidates",
                              "candidate_scenes", "download_jobs", "events"):
                    data[table] = [dict(row) for row in store.execute(f"SELECT * FROM {table} ORDER BY 1")]
                print(json.dumps(data, ensure_ascii=False, indent=2), file=stream)
            else:
                writer = csv.DictWriter(stream, fieldnames=["record_type", "movie_id", "title", "scene_id", "ordinal",
                                                            "status", "path", "size_bytes", "classification", "approval",
                                                            "eligible", "details"], extrasaction="ignore")
                writer.writeheader()
                for scene in store.list_scenes():
                    writer.writerow({"record_type": "scene", "movie_id": scene["movie_id"], "title": scene["title"],
                                     "scene_id": scene["scene_id"], "ordinal": scene["ordinal"], "status": scene["status"],
                                     "details": scene["status_detail"]})
                for candidate in store.list_candidates():
                    writer.writerow({"record_type": "candidate", "movie_id": candidate["movie_key"].split("|")[-1],
                                     "path": candidate["path"], "size_bytes": candidate["size_bytes"],
                                     "classification": candidate["classification"], "approval": candidate["approval"],
                                     "eligible": bool(candidate["eligible"]), "details": candidate["match_evidence"]})
    finally:
        if close:
            stream.close()
