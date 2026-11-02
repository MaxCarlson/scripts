"""LLM Monitor evidence preservation and verification for suite runs.

Preserves consistent SQLite backups, streaming SHA-256 hashes, API snapshots,
task-to-request reconciliation, and integrity indexes for benchmark runs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from .suite_output import emit

ENDPOINTS = {
    "recording_status": "/api/inference/v1/recording/status",
    "status": "/api/inference/v1/status",
    "servers": "/api/inference/v1/servers",
    "models": "/api/inference/v1/models",
    "requests": "/api/inference/v1/requests",
    "hardware": "/api/inference/v1/hardware",
    "analytics": "/api/inference/v1/analytics",
    "history_analytics": "/api/inference/v1/history/analytics",
}

TERMINAL_REQUEST_STATES = {"completed", "failed", "cancelled"}
ACTIVE_REQUEST_STATES = {
    "active", "generating", "streaming", "pending", "started"
}
SCORED_TASK_STATES = {"passed", "failed", "timed_out"}


class ArchiveError(RuntimeError):
    """An archive operation failed or required evidence is unavailable."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ArchiveError(f"Expected a JSON object: {path}")
    return result


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def safe_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost", "host.docker.internal"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ArchiveError("Monitor API origin must be a local HTTP(S) URL")

    return f"{parsed.scheme}://{parsed.netloc}"


def monitor_get(origin: str, endpoint: str) -> dict[str, Any]:
    headers = {"Origin": origin, "Accept": "application/json"}

    if os.environ.get("LLM_MONITOR_AUTHORIZATION"):
        headers["Authorization"] = os.environ["LLM_MONITOR_AUTHORIZATION"]
    if os.environ.get("LLM_MONITOR_SESSION_COOKIE"):
        headers["Cookie"] = os.environ["LLM_MONITOR_SESSION_COOKIE"]

    request = Request(origin + endpoint, headers=headers)
    opener = build_opener(ProxyHandler({}))

    try:
        with opener.open(request, timeout=15) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ArchiveError(f"Invalid response object: {endpoint}")
        return data
    except HTTPError as error:
        raise ArchiveError(
            f"Monitor API {endpoint}: HTTP {error.code}"
        ) from error
    except (URLError, TimeoutError, ValueError) as error:
        raise ArchiveError(
            f"Monitor API {endpoint}: {type(error).__name__}"
        ) from error


def recording_status(origin: str) -> dict[str, Any]:
    data = monitor_get(origin, ENDPOINTS["recording_status"])
    rec = data.get("recording")
    if not isinstance(rec, dict):
        raise ArchiveError("Invalid monitor recording status")
    return rec


def wait_for_drain(
    origin: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> tuple[dict[str, Any], int, bool]:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    active = -1

    while True:
        last_status = recording_status(origin)
        data = monitor_get(origin, ENDPOINTS["requests"])
        requests = data.get("requests", [])

        if not isinstance(requests, list):
            raise ArchiveError("Invalid monitor request inventory")

        active = sum(
            isinstance(item, dict)
            and item.get("state") in ACTIVE_REQUEST_STATES
            for item in requests
        )
        pending = int(last_status.get("pending_queue_size") or 0)

        if pending == 0 and active == 0:
            return last_status, active, True

        if time.monotonic() >= deadline:
            return last_status, active, False

        time.sleep(poll_seconds)


def resolve_run(run: str, runs_root: Path) -> Path:
    supplied = Path(run).expanduser()
    path = supplied if supplied.is_dir() else runs_root / supplied

    path = path.resolve()
    for name in ("manifest.json", "checkpoint.json"):
        if not (path / name).is_file():
            raise ArchiveError(f"Missing {name} in run: {path}")

    return path


def sqlite_online_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ArchiveError(f"Source SQLite database does not exist: {source}")
    if destination.exists():
        raise ArchiveError(f"Refusing to overwrite: {destination}")

    # as_uri() correctly encodes Windows paths and spaces.
    uri = source.resolve().as_uri() + "?mode=ro"

    with sqlite3.connect(uri, uri=True, timeout=60) as src:
        with sqlite3.connect(destination, timeout=60) as dst:
            src.backup(dst, pages=1000, sleep=0.05)


def sqlite_inspect(path: Path) -> dict[str, Any]:
    uri = path.resolve().as_uri() + "?mode=ro"

    with sqlite3.connect(uri, uri=True, timeout=30) as db:
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        foreign_keys = list(db.execute("PRAGMA foreign_key_check"))
        names = [
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]

        counts = {}
        for name in names:
            escaped = name.replace('"', '""')
            counts[name] = db.execute(
                f'SELECT COUNT(*) FROM "{escaped}"'
            ).fetchone()[0]

        modes: dict[str, int] = {}
        states: dict[str, int] = {}
        truncated = 0

        if "inference_requests" in counts:
            for mode, count in db.execute(
                "SELECT recording_mode, COUNT(*) "
                "FROM inference_requests GROUP BY recording_mode"
            ):
                modes[str(mode)] = count

            for state, count in db.execute(
                "SELECT state, COUNT(*) "
                "FROM inference_requests GROUP BY state"
            ):
                states[str(state)] = count

        if "inference_contents" in counts:
            truncated = db.execute(
                "SELECT COUNT(*) FROM inference_contents WHERE truncated != 0"
            ).fetchone()[0]

        empty_content_requests = 0
        if "inference_requests" in counts and "inference_contents" in counts:
            empty_content_requests = db.execute(
                "SELECT COUNT(*) FROM inference_requests r "
                "LEFT JOIN inference_contents c ON r.request_id = c.request_id "
                "WHERE r.recording_mode = 'content' AND c.id IS NULL"
            ).fetchone()[0]

    return {
        "integrity_ok": integrity == ["ok"],
        "integrity_results": integrity,
        "foreign_key_violations": len(foreign_keys),
        "table_counts": counts,
        "recording_modes": modes,
        "request_states": states,
        "truncated_content_segments": truncated,
        "empty_content_requests": empty_content_requests,
    }


def reconcile_tasks(
    backup: Path,
    checkpoint: dict[str, Any],
    required_mode: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    uri = backup.resolve().as_uri() + "?mode=ro"
    tasks: list[dict[str, Any]] = []
    gaps: list[str] = []

    with sqlite3.connect(uri, uri=True) as db:
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"inference_requests", "inference_contents"} <= tables:
            return [], ["Inference request/content tables are missing"]

        for task in checkpoint.get("tasks", []):
            task_id = str(task.get("task_id", "unknown"))
            task_state = str(task.get("status", "unknown"))
            request_ids = list(dict.fromkeys(
                str(value) for value in
                (task.get("monitor_request_ids") or [])
            ))

            verified = 0
            complete = 0
            segments = 0
            truncated = 0
            missing: list[str] = []
            empty_requests: list[str] = []
            observed_modes: set[str] = set()

            for request_id in request_ids:
                record = db.execute(
                    "SELECT state, recording_mode FROM inference_requests "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()

                if record is None:
                    missing.append(request_id)
                    continue

                verified += 1
                state, mode = record
                observed_modes.add(str(mode))

                if state in TERMINAL_REQUEST_STATES:
                    complete += 1

                content_count, truncated_count = db.execute(
                    "SELECT COUNT(*), "
                    "COALESCE(SUM(CASE WHEN truncated != 0 THEN 1 ELSE 0 END), 0) "
                    "FROM inference_contents WHERE request_id = ?",
                    (request_id,),
                ).fetchone()

                if required_mode == "content" and content_count == 0:
                    empty_requests.append(request_id)

                segments += content_count
                truncated += truncated_count

            coverage_ok = (
                bool(request_ids)
                and verified == len(request_ids)
                and complete == len(request_ids)
                and (required_mode != "content" or (segments > 0 and not empty_requests))
                and (required_mode == "off"
                     or observed_modes == {required_mode})
                and truncated == 0
            )

            # Pending tasks do not yet require recorded inference,
            # but do prevent a complete final archive.
            if empty_requests:
                gaps.append(f"{task_id}: requests missing recorded content: {', '.join(empty_requests)}")
            if task_state in SCORED_TASK_STATES and not coverage_ok:
                gaps.append(f"{task_id}: incomplete recorded inference")
            elif task_state == "infrastructure_invalid" and not coverage_ok:
                gaps.append(f"{task_id}: infrastructure attempt lacks full evidence")
            elif task_state in {"pending", "running"}:
                gaps.append(f"{task_id}: task is not terminal")

            tasks.append({
                "task_id": task_id,
                "status": task_state,
                "expected_request_ids": len(request_ids),
                "verified_request_ids": verified,
                "terminal_requests": complete,
                "content_segments": segments,
                "truncated_segments": truncated,
                "empty_requests": empty_requests,
                "recording_modes": sorted(observed_modes),
                "missing_request_ids": missing,
                "coverage_ok": coverage_ok,
                "duration_wall_ms": task.get("duration_wall_ms"),
                "native_artifacts": task.get("native_artifacts", []),
            })

    return tasks, gaps


def copy_run_metadata(source: Path, target: Path) -> None:
    for filename in (
        "manifest.json",
        "checkpoint.json",
        "report.json",
        "monitor-preflight.json",
    ):
        item = source / filename
        if item.is_file():
            shutil.copy2(item, target / f"suite_{filename}")


def create_index(manifest: dict[str, Any]) -> str:
    run_id = manifest["run_id"]
    info = manifest["sqlite"]
    rows = manifest["task_reconciliation"]

    lines = [
        f"# Benchmark Evidence — {run_id}",
        "",
        f"- Created: {manifest['created_at']}",
        f"- Archive completeness: **{manifest['completeness']}**",
        f"- Cohort: `{manifest.get('cohort')}`",
        f"- Agent/model: `{manifest.get('agent')}` / `{manifest.get('model')}`",
        f"- Source revision: `{manifest.get('source_revision')}`",
        "- SQLite backup: `monitor_snapshot.sqlite3`",
        f"- SQLite integrity: {'OK' if info['integrity_ok'] else 'FAILED'}",
        f"- Requests: {info['table_counts'].get('inference_requests', 0)}",
        f"- Content segments: {info['table_counts'].get('inference_contents', 0)}",
        f"- Hardware samples: {info['table_counts'].get('inference_hardware_samples', 0)}",
        "",
        "## Per-task evidence",
        "",
        "| Task | Status | Request IDs | Persisted | Content segments | Coverage |",
        "|---|---|---:|---:|---:|---|",
    ]

    for item in rows:
        lines.append(
            f"| `{item['task_id']}` | {item['status']} | "
            f"{item['expected_request_ids']} | "
            f"{item['verified_request_ids']} | "
            f"{item['content_segments']} | "
            f"{'OK' if item['coverage_ok'] else 'Incomplete'} |"
        )

    lines.extend(["", "## Gaps and limitations", ""])
    if manifest["gaps"]:
        lines.extend(f"- {gap}" for gap in manifest["gaps"])
    else:
        lines.append("- No gaps detected by the available checks.")

    lines.extend([
        "",
        "Request-to-task association comes from the suite checkpoint.",
        "It does not independently prove exclusive or exhaustive capture.",
        "Monitor API snapshots represent observations at capture time;",
        "the SQLite backup is the consistent database snapshot.",
        "Full prompts and responses are sensitive private evidence.",
        "",
        "## Source artifacts",
        "",
        f"- Suite run directory: `{manifest['source_run_dir']}`",
        "- Suite logs and native Harbor artifacts remain in the run directory",
        "  unless copied using `--include-native`.",
        "",
    ])
    return "\n".join(lines)


def file_inventory(directory: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == "archive_manifest.json":
            continue
        relative = path.relative_to(directory).as_posix()
        result[relative] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return result


def create_archive(args: argparse.Namespace) -> int:
    runs_root = Path(getattr(args, "runs_root", Path("reports/agent-bench-suite"))).expanduser()
    run_id_or_path = getattr(args, "run", None)
    if not run_id_or_path:
        raise ArchiveError("Run ID or run path is required (-r/--run)")

    run_dir = resolve_run(run_id_or_path, runs_root)
    run = read_json(run_dir / "manifest.json")
    checkpoint = read_json(run_dir / "checkpoint.json")

    origin_value = getattr(args, "monitor_host_url", None) or (
        run.get("provenance", {}).get("monitor_host_url")
    )
    origin = safe_origin(origin_value) if origin_value else None

    output_arg = getattr(args, "output", None)
    output = (
        Path(output_arg).resolve()
        if output_arg
        else run_dir / "evidence" / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-" + uuid4().hex[:8]
        )
    )

    friendly = bool(getattr(args, "llm_friendly", False))
    execute = bool(getattr(args, "execute", False))
    allow_partial = bool(getattr(args, "allow_partial", False))
    include_native = bool(getattr(args, "include_native", False))
    drain_timeout = float(getattr(args, "drain_timeout", 30.0))
    poll_interval = float(getattr(args, "poll_interval", 1.0))
    database_arg = getattr(args, "database", None)

    if not execute:
        result = {
            "dry_run": True,
            "run_id": run.get("run_id"),
            "run_state": checkpoint.get("state"),
            "source_run_dir": str(run_dir),
            "monitor_host_url": origin,
            "source_database": str(database_arg) if database_arg else "monitor API",
            "archive_output": str(output),
            "allow_partial": allow_partial,
            "include_native": include_native,
        }
        emit(result, llm_friendly=friendly)
        return 0

    status: dict[str, Any] = {}
    active_requests = -1
    drained = False
    api_errors: list[str] = []

    if origin:
        try:
            if checkpoint.get("state") == "finished":
                status, active_requests, drained = wait_for_drain(
                    origin, drain_timeout, poll_interval
                )
            else:
                status = recording_status(origin)
                drained = False
        except ArchiveError as error:
            api_errors.append(str(error))

    database_value = database_arg or status.get("database_path")
    if not database_value:
        raise ArchiveError(
            "Cannot discover recording database; supply -d/--database"
        )

    database = Path(database_value).expanduser().resolve()
    if not database.is_file():
        raise ArchiveError(f"Recording database is missing: {database}")

    if checkpoint.get("state") != "finished" and not allow_partial:
        raise ArchiveError(
            "Run is not finished; use --allow-partial for a live snapshot"
        )
    if (not origin or api_errors or not drained) and not allow_partial:
        raise ArchiveError(
            "Recorder drain/health could not be verified; "
            "use --allow-partial if appropriate"
        )

    if output.exists():
        raise ArchiveError(f"Archive path already exists: {output}")

    output.mkdir(parents=True, exist_ok=False)
    if os.name == "posix":
        output.chmod(0o700)

    api_summary: dict[str, Any] = {}

    if origin:
        for name, endpoint in ENDPOINTS.items():
            try:
                payload = monitor_get(origin, endpoint)
                filename = f"api_{name}.json"
                write_json(output / filename, payload)
                api_summary[name] = {"captured": True, "file": filename}
            except ArchiveError as error:
                api_summary[name] = {
                    "captured": False,
                    "error": str(error),
                }
                api_errors.append(str(error))

    backup = output / "monitor_snapshot.sqlite3"
    sqlite_online_backup(database, backup)
    db_info = sqlite_inspect(backup)

    required_mode = str(
        checkpoint.get("recording_configuration")
        or run.get("provenance", {}).get("recording_required")
        or "off"
    )
    reconciliation, gaps = reconcile_tasks(
        backup, checkpoint, required_mode
    )

    if not db_info["integrity_ok"]:
        gaps.append("SQLite integrity_check failed")
    if db_info["foreign_key_violations"]:
        gaps.append("SQLite foreign key violations detected")
    if db_info["truncated_content_segments"]:
        gaps.append("Some recorded content segments were truncated")
    if db_info.get("empty_content_requests", 0) > 0 and required_mode == "content":
        gaps.append(f"{db_info['empty_content_requests']} content-mode requests lack recorded content")
    if checkpoint.get("state") != "finished":
        gaps.append("Benchmark has not reached its finished state")
    if origin is None:
        gaps.append("Live recorder status not available")
    if api_errors:
        gaps.append("One or more monitor API snapshots/checks failed")
    if origin and not drained:
        gaps.append("Recorder/active request drain not confirmed")
    if origin and status.get("healthy", status.get("is_healthy")) is not True:
        gaps.append("Recorder health not verified")
    if origin and status.get("dropped_count") != 0:
        gaps.append("Recorder reports dropped observations")
    if origin and status.get("last_error"):
        gaps.append("Recorder reports an error")
    if origin and status.get("mode") != required_mode:
        gaps.append("Recorder mode differs from run requirement")

    copy_run_metadata(run_dir, output)

    if include_native:
        for dirname in ("logs", "harbor-jobs", "results"):
            source = run_dir / dirname
            if source.is_dir():
                shutil.copytree(source, output / dirname)

    completeness = "verified" if not gaps else "partial"

    manifest = {
        "schema": "agent-benchmark-evidence-archive-v1",
        "created_at": utc_now(),
        "run_id": run.get("run_id"),
        "source_run_dir": str(run_dir),
        "source_database": str(database),
        "monitor_host_url": origin,
        "cohort": run.get("cohort"),
        "agent": run.get("agent"),
        "model": run.get("model"),
        "source_revision": run.get("source_revision"),
        "effective_api_format": run.get("provenance", {}).get(
            "effective_api_format"
        ),
        "run_state": checkpoint.get("state"),
        "recording_required": required_mode,
        "recording_telemetry": status,
        "active_requests_at_check": active_requests,
        "recorder_drained": drained,
        "sqlite": db_info,
        "task_reconciliation": reconciliation,
        "api_snapshots": api_summary,
        "gaps": gaps,
        "completeness": completeness,
    }

    (output / "EVIDENCE_INDEX.md").write_text(
        create_index(manifest), encoding="utf-8"
    )
    manifest["files"] = file_inventory(output)
    write_json(output / "archive_manifest.json", manifest)

    result = {
        "archive": str(output),
        "run_id": run.get("run_id"),
        "completeness": completeness,
        "requests": db_info["table_counts"].get("inference_requests", 0),
        "contents": db_info["table_counts"].get("inference_contents", 0),
        "gaps": gaps,
    }
    emit(result, llm_friendly=friendly)
    return 0 if completeness == "verified" else 1


def verify_archive(args: argparse.Namespace) -> int:
    archive_path = getattr(args, "archive", None) or getattr(args, "path", None)
    if not archive_path:
        raise ArchiveError("Missing archive path for verification (-p/--archive)")

    root = Path(archive_path).expanduser().resolve()
    manifest_file = root / "archive_manifest.json"
    if not manifest_file.is_file():
        raise ArchiveError(f"Missing archive_manifest.json in: {root}")

    manifest = read_json(manifest_file)
    problems: list[str] = []

    for relative, info in manifest.get("files", {}).items():
        path = (root / relative).resolve()

        if not path.is_relative_to(root):
            problems.append(f"Archive path escapes root: {relative}")
            continue

        if not path.is_file():
            problems.append(f"Missing file: {relative}")
            continue

        if path.stat().st_size != info["bytes"]:
            problems.append(f"Size mismatch: {relative}")
        if sha256_file(path) != info["sha256"]:
            problems.append(f"Hash mismatch: {relative}")

    backup = root / "monitor_snapshot.sqlite3"
    inspection = None

    if not backup.is_file():
        problems.append("Missing SQLite backup")
    else:
        try:
            inspection = sqlite_inspect(backup)
            if not inspection["integrity_ok"]:
                problems.append("SQLite integrity check failed")
            if inspection["foreign_key_violations"]:
                problems.append("SQLite foreign key check failed")
            if inspection["table_counts"] != manifest["sqlite"]["table_counts"]:
                problems.append("SQLite table counts changed")
        except sqlite3.DatabaseError as error:
            problems.append(f"SQLite error: {type(error).__name__}")

    friendly = bool(getattr(args, "llm_friendly", False))
    result = {
        "archive": str(root),
        "run_id": manifest.get("run_id"),
        "archive_completeness": manifest.get("completeness"),
        "integrity_ok": not problems,
        "problems": problems,
        "sqlite": inspection,
    }
    emit(result, llm_friendly=friendly)
    return 0 if not problems else 1


def parser_factory() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive and verify Agent Benchmark / LLM Monitor evidence"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "create", help="Create a consistent SQLite evidence archive"
    )
    create.add_argument("-r", "--run", required=True, help="Run ID or run path")
    create.add_argument(
        "-R", "--runs-root", type=Path,
        default=Path("reports/agent-bench-suite"),
    )
    create.add_argument("-d", "--database", type=Path)
    create.add_argument("-H", "--monitor-host-url")
    create.add_argument("-o", "--output", type=Path)
    create.add_argument("-t", "--drain-timeout", type=float, default=30)
    create.add_argument("-i", "--poll-interval", type=float, default=1)
    create.add_argument(
        "-P", "--allow-partial", action="store_true",
        help="Allow incomplete or live evidence; never mark it verified",
    )
    create.add_argument(
        "-N", "--include-native", action="store_true",
        help="Also copy run logs and native Harbor artifacts",
    )
    create.add_argument(
        "-x", "--execute", action="store_true",
        help="Actually write the archive; default is dry-run",
    )
    create.add_argument("-F", "--llm-friendly", action="store_true")

    verify = commands.add_parser(
        "verify", help="Verify an archived database and file checksums offline"
    )
    verify.add_argument("-p", "--archive", type=Path, required=True)
    verify.add_argument("-F", "--llm-friendly", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = parser_factory()
    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            if args.drain_timeout < 0 or args.poll_interval <= 0:
                parser.error("drain timeout must be >= 0; poll interval must be > 0")
            return create_archive(args)

        if args.command == "verify":
            return verify_archive(args)

        return 2
    except (ArchiveError, OSError, sqlite3.Error, ValueError) as error:
        print(
            json.dumps({
                "event": "error",
                "code": type(error).__name__,
                "detail": str(error),
            }),
            file=sys.stderr,
        )
        return 2
