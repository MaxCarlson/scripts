"""Portable, checksummed exports of already-sanitized telemetry."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile
from typing import Any

from .history_analysis import analyze_stored_session
from . import __version__
from .storage import TelemetryStore

EXPORT_SCHEMA_VERSION = 1
REDACTION_POLICY = "stored-metadata-only-v1"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _contexts(store: TelemetryStore, session_ids: list[str], endpoints: list[str] | None):
    result = []
    for index, session_id in enumerate(session_ids):
        endpoint = endpoints[index] if endpoints and index < len(endpoints) else None
        context = store.session_context(session_id, endpoint=endpoint)
        if context is None:
            raise ValueError(f"session {session_id!r} was not found")
        result.append((session_id, endpoint, context))
    return result


def preview_evidence_package(*, store: TelemetryStore, session_ids: list[str], endpoints: list[str] | None,
                             output_path: Path, events_format: str = "jsonl") -> dict[str, Any]:
    contexts = _contexts(store, session_ids, endpoints)
    return {"ok": True, "written": False, "output": str(output_path), "sessions": session_ids,
            "record_count": sum(item[2]["event_count"] for item in contexts),
            "size_bytes": None, "format": events_format, "redaction_policy": REDACTION_POLICY}


def _csv_safe(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def write_evidence_package(*, store: TelemetryStore, session_ids: list[str], endpoints: list[str] | None,
                           output_path: Path, events_format: str = "jsonl") -> dict[str, Any]:
    contexts = _contexts(store, session_ids, endpoints)
    output_path = Path(output_path).absolute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    try:
        with tempfile.NamedTemporaryFile(prefix=".llm-monitor-", suffix=".tmp", dir=output_path.parent,
                                         delete=False) as handle:
            temporary = Path(handle.name)
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for index, (session_id, endpoint, context) in enumerate(contexts):
                prefix = f"sessions/{index + 1:03d}"
                datasets: dict[str, bytes] = {}
                datasets[f"{prefix}/session.json"] = _json_bytes({"session": context["session"],
                    "coverage": context["coverage"], "gaps": context["gaps"], "jobs": context["jobs"],
                    "model_configurations": context["model_configurations"],
                    "hardware_samples": context["hardware_samples"],
                    "hardware_samples_truncated": context["hardware_samples_truncated"]})
                analysis = analyze_stored_session(store, session_id, endpoint=endpoint)
                datasets[f"{prefix}/analysis.json"] = _json_bytes(analysis)
                record_count = 0
                event_name = f"{prefix}/events.{events_format}"
                hasher = hashlib.sha256()
                if events_format == "csv":
                    with archive.open(event_name, "w") as member:
                        def write_csv_line(fields):
                            buffer = io.StringIO(newline="")
                            csv.writer(buffer).writerow(fields)
                            data = buffer.getvalue().encode("utf-8")
                            member.write(data)
                            hasher.update(data)
                        write_csv_line(["event_uid", "timestamp", "observed_at", "source", "category", "subtype", "payload_json"])
                        for row in store.iter_session_records(session_id, endpoint=endpoint):
                            write_csv_line([_csv_safe(row.get(key)) for key in ("event_uid", "timestamp", "observed_at", "source", "category", "subtype")]
                                           + [_csv_safe(row["payload"])])
                            record_count += 1
                elif events_format == "json":
                    with archive.open(event_name, "w") as member:
                        member.write(b"[")
                        hasher.update(b"[")
                        first = True
                        for row in store.iter_session_records(session_id, endpoint=endpoint):
                            data = (b"" if first else b",") + json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
                            member.write(data)
                            hasher.update(data)
                            first = False
                            record_count += 1
                        member.write(b"]\n")
                        hasher.update(b"]\n")
                else:
                    with archive.open(event_name, "w") as member:
                        for row in store.iter_session_records(session_id, endpoint=endpoint):
                            data = _json_bytes(row)
                            member.write(data)
                            hasher.update(data)
                            record_count += 1
                counts[prefix] = record_count
                hashes[event_name] = hasher.hexdigest()
                for name, data in datasets.items():
                    archive.writestr(name, data)
                    hashes[name] = hashlib.sha256(data).hexdigest()
            manifest = {"export_schema_version": EXPORT_SCHEMA_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "monitor_version": __version__, "source_telemetry_schema_version": 1,
                "session_ids": session_ids, "record_counts": counts, "files": hashes,
                "redaction_policy": REDACTION_POLICY,
                "provenance_note": "Checksums establish package integrity only, not provider-data authenticity."}
            archive.writestr("manifest.json", _json_bytes(manifest))
        os.replace(temporary, output_path)
        temporary = None
        return {"ok": True, "written": True, "output": str(output_path), "sessions": session_ids,
                "record_count": sum(counts.values()), "size_bytes": output_path.stat().st_size,
                "manifest": manifest}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_evidence_package(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    checked = 0
    try:
        with ZipFile(path, "r") as archive:
            names = archive.namelist()
            if "manifest.json" not in names:
                return {"ok": False, "files_checked": 0, "errors": ["manifest.json is missing"]}
            if len(names) != len(set(names)):
                errors.append("duplicate archive member names")
            if any(name.startswith(("/", "\\")) or ".." in Path(name).parts for name in names):
                errors.append("unsafe archive member path")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("export_schema_version") != EXPORT_SCHEMA_VERSION:
                errors.append("unsupported export schema version")
            declared = manifest.get("files")
            if not isinstance(declared, dict):
                errors.append("manifest files table is invalid")
                declared = {}
            actual = set(names) - {"manifest.json"}
            for missing in sorted(set(declared) - actual):
                errors.append(f"missing file: {missing}")
            for unexpected in sorted(actual - set(declared)):
                errors.append(f"unlisted file: {unexpected}")
            for name, expected in declared.items():
                if name in actual:
                    checked += 1
                    if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                        errors.append(f"checksum mismatch: {name}")
    except (OSError, ValueError, KeyError) as exc:
        return {"ok": False, "files_checked": checked, "errors": [str(exc)]}
    return {"ok": not errors, "files_checked": checked, "errors": errors,
            "authenticity_verified": False}
