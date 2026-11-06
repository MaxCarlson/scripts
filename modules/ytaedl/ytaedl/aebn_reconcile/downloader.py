"""Bounded, resumable AEBN scene-ID replacement downloads."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .store import ReconciliationStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _process_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _run_aebndl(command: list[str], on_spawn: Callable[[int], None]) -> tuple[int, list[dict]]:
    """Run the existing aebndl downloader and retain its structured events."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", bufsize=1)
    on_spawn(process.pid)
    events: list[dict] = []
    tail: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            tail.append(line.rstrip())
            tail = tail[-8:]
            continue
        if isinstance(event, dict):
            # Progress events can be numerous; keep lifecycle and completion data only.
            if event.get("event") not in {"progress", "heartbeat"}:
                events.append(event)
    rc = process.wait()
    if rc and tail:
        events.append({"event": "process_output", "tail": tail})
    return rc, events


def _command(row: dict, database_path: Path, roots: list[str]) -> list[str]:
    if not roots:
        raise ValueError("no download roots are configured; scan with at least one -L/--download-root")
    movie_key_dir = re.sub(r"[^A-Za-z0-9._-]+", "_", row["movie_key"])
    scene_dir = Path(roots[0]) / "AEBN Scene Replacements" / movie_key_dir
    work_dir = database_path.parent / "work" / movie_key_dir / row["scene_id"]
    return [sys.executable, "-m", "aebn_dl.cli", "-o", str(scene_dir), "-w", str(work_dir),
            "-I", row["scene_id"], "--json", row["original_url"]]


def _candidate_jobs(store: ReconciliationStore) -> list[dict]:
    return [dict(row) for row in store.execute(
        """SELECT s.movie_key,s.scene_id,s.ordinal,s.original_url,s.status,m.movie_id
           FROM requested_scenes s JOIN movies m USING(movie_key)
           WHERE s.metadata_status='resolved' AND s.ordinal IS NOT NULL
             AND s.status IN ('scene_missing','scene_candidate_unverified','scene_ambiguous','scene_invalid')
             AND NOT EXISTS(SELECT 1 FROM download_jobs j WHERE j.movie_key=s.movie_key AND j.scene_id=s.scene_id
                            AND (j.status='verified' OR (j.status='downloaded' AND j.verification_status!='failed')))
           ORDER BY m.movie_id,s.ordinal""")]


def _recover_running(store: ReconciliationStore) -> int:
    recovered = 0
    for row in store.execute("SELECT job_id,process_id,status FROM download_jobs WHERE status='running'").fetchall():
        if not _process_is_alive(row["process_id"]):
            store.execute("UPDATE download_jobs SET status='interrupted',process_id=NULL,ended_at=?,error=? WHERE job_id=?",
                          (_now(), "worker process is no longer active; output must be verified before reuse", row["job_id"]))
            store.record_event("download_interrupted", details={"job_id": row["job_id"]})
            recovered += 1
    return recovered


def download_missing(database_path: Path | str, *, apply: bool = False, threads: int = 1,
                     runner: Callable[[list[str]], tuple[int, list[dict]]] | None = None) -> dict[str, int | list[dict]]:
    """Preview or execute only scene requests without verified local replacements.

    Downloads use the existing ``aebn_dl`` scene-ID path in a dedicated output
    directory, so historical ytaedl archive records cannot suppress the request
    and an existing full-movie filename cannot be overwritten.
    """
    if threads < 1 or threads > 16:
        raise ValueError("threads must be between 1 and 16")
    db_path = Path(database_path).expanduser().resolve()
    with ReconciliationStore(db_path) as store:
        recovered = _recover_running(store) if apply else 0
        work = _candidate_jobs(store)
        for row in store.execute(
            """SELECT s.movie_key,s.scene_id,s.ordinal,s.original_url,s.status,m.movie_id
               FROM requested_scenes s JOIN movies m USING(movie_key)
               WHERE s.metadata_status='resolved' AND s.ordinal IS NOT NULL AND s.status='scene_missing'
                 AND NOT EXISTS(SELECT 1 FROM download_jobs j WHERE j.movie_key=s.movie_key AND j.scene_id=s.scene_id)"""
        ):
            work.append(dict(row))
        existing = work
        roots = store.get_setting("download_roots", [])
        if apply and existing and not roots:
            raise ValueError("no download roots are configured; scan with at least one valid -L/--download-root")
        if not apply:
            planned = []
            for row in existing:
                planned.append({"movie_id": row["movie_id"], "scene_id": row["scene_id"], "ordinal": row["ordinal"],
                                "url": row["original_url"], "command": _command(row, db_path, roots) if roots else None})
            return {"planned": len(planned), "started": 0, "completed": 0, "failed": 0,
                    "recovered": recovered, "operations": planned}
        for row in existing:
            store.execute(
                "INSERT OR IGNORE INTO download_jobs(movie_key,scene_id,target_dir,status) VALUES(?,?,?,'pending')",
                (row["movie_key"], row["scene_id"], roots[0] if roots else ""),
            )
        candidate_data = existing

    def run(row: dict) -> tuple[dict, int, list[dict]]:
        with ReconciliationStore(db_path) as store:
            cursor = store.execute(
                "UPDATE download_jobs SET status='running',process_id=?,attempts=attempts+1,started_at=?,ended_at=NULL,error=NULL "
                "WHERE movie_key=? AND scene_id=? AND status IN ('pending','failed','interrupted','downloaded')",
                (os.getpid(), _now(), row["movie_key"], row["scene_id"]),
            )
            if cursor.rowcount != 1:
                return row, -2, [{"event": "skipped", "reason": "already claimed or complete"}]
            store.record_event("download_started", movie_key=row["movie_key"], scene_id=row["scene_id"],
                               details={"ordinal": row["ordinal"]})
        def on_spawn(pid: int) -> None:
            with ReconciliationStore(db_path) as state:
                state.execute("UPDATE download_jobs SET process_id=? WHERE movie_key=? AND scene_id=? AND status='running'",
                              (pid, row["movie_key"], row["scene_id"]))
        try:
            command = _command(row, db_path, roots)
            Path(command[command.index("-o") + 1]).mkdir(parents=True, exist_ok=True)
            Path(command[command.index("-w") + 1]).mkdir(parents=True, exist_ok=True)
            if runner is None:
                rc, events = _run_aebndl(command, on_spawn)
            else:
                rc, events = runner(command)
            complete = next((event for event in reversed(events) if event.get("event") in {"complete", "already"}), None)
            output_path = complete.get("path") if complete else None
            status = "downloaded" if rc == 0 and output_path else "failed"
            error = None if status == "downloaded" else f"aebndl exited {rc} without a completed output event"
            result_rc = rc if rc != 0 else (0 if status == "downloaded" else 1)
        except Exception as exc:
            rc, events, output_path, status = 1, [], None, "failed"
            error = f"{type(exc).__name__}: {exc}"
            result_rc = rc
        with ReconciliationStore(db_path) as store:
            store.execute("UPDATE download_jobs SET status=?,process_id=NULL,ended_at=?,exit_code=?,output_path=?,error=? "
                          "WHERE movie_key=? AND scene_id=?",
                          (status, _now(), result_rc, output_path, error, row["movie_key"], row["scene_id"]))
            store.record_event("download_completed" if status == "downloaded" else "download_failed",
                               movie_key=row["movie_key"], scene_id=row["scene_id"],
                               details={"exit_code": result_rc, "output_path": output_path, "error": error, "events": events})
        return row, result_rc, events

    completed = failed = started = 0
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = {pool.submit(run, row): row for row in candidate_data}
        for future in as_completed(futures):
            row, rc, _events = future.result()
            if rc == -2:
                continue
            started += 1
            if rc == 0:
                completed += 1
            else:
                failed += 1
    return {"planned": len(candidate_data), "started": started, "completed": completed,
            "failed": failed, "recovered": recovered, "operations": []}
