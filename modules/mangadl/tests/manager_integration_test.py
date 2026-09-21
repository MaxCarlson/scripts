import json
import sys
import time
from pathlib import Path

from mangadl.gallery_auth import ProbeResult
from mangadl.manager import DownloadManager, RunOptions
from mangadl.models import InputUrl
from mangadl.state import StateStore


def test_manager_runs_fake_worker_to_completion(tmp_path: Path, monkeypatch) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    run_id = store.create_run({}, "integration")
    item = InputUrl("1", "https://nhentai.net/g/1/", "test", 1)
    store.add_jobs(run_id, [item], {item.canonical_url: "gallery-dl"})
    options = RunOptions(
        run_id=run_id,
        destination=tmp_path / "downloads",
        archive=tmp_path / "archive.sqlite3",
        state_db=tmp_path / "state.sqlite3",
        log_dir=tmp_path / "logs",
        workers=1,
        retries=0,
        retry_wait=0.01,
        ui=False,
    )

    def fake_command(self, slot, job):
        base = {
            "schema": 1,
            "run_id": run_id,
            "job_id": job["id"],
            "attempt_id": job["attempt_id"],
            "worker": slot,
            "url": job["canonical_url"],
            "wall_time": time.time(),
            "monotonic": time.monotonic(),
        }
        events = [
            {**base, "event": "worker_ready", "data": {"state": "running"}},
            {
                **base,
                "event": "job_complete",
                "data": {"state": "succeeded", "images_done": 3, "images_total": 3, "bytes_done": 99},
            },
        ]
        script = ";".join(f"print({json.dumps(json.dumps(event))}, flush=True)" for event in events)
        return [sys.executable, "-c", script]

    monkeypatch.setattr(DownloadManager, "_worker_command", fake_command)
    try:
        assert DownloadManager(options, store).run() == 0
        job = store.jobs(run_id)[0]
        assert job["state"] == "succeeded"
        assert job["images_done"] == 3
        assert (tmp_path / "logs" / run_id / "summary.json").exists()
        worker_log = (tmp_path / "logs" / run_id / "workers" / "worker-01.log").read_text(encoding="utf-8")
        assert " START " in worker_log
        assert "FINISH_SUCCESS" in worker_log
        assert "NH:1" in worker_log
        assert worker_log.startswith("[") and "][00:00:00.000]" in worker_log
    finally:
        store.close()


def test_manager_coordinates_one_background_auth_refresh_for_same_domain_jobs(
    tmp_path: Path, monkeypatch
) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    run_id = store.create_run({}, "auth-integration")
    items = [
        InputUrl(str(index), f"https://www.mangakakalot.gg/manga/title-{index}", "test", index)
        for index in (1, 2)
    ]
    store.add_jobs(run_id, items, {item.canonical_url: "gallery-dl" for item in items})
    options = RunOptions(
        run_id=run_id,
        destination=tmp_path / "downloads",
        archive=tmp_path / "archive.sqlite3",
        state_db=tmp_path / "state.sqlite3",
        log_dir=tmp_path / "logs",
        workers=2,
        retries=0,
        retry_wait=0.01,
        auth_dir=tmp_path / "auth",
        worker_start_delay=0,
        ui=False,
    )
    refresh_calls: list[str] = []

    def fake_refresh(url, *, store, progress, **kwargs):
        refresh_calls.append(url)
        progress("[mangakakalot.gg] mocked browser verification")
        time.sleep(0.1)
        profile = store.save(
            url,
            "# Netscape HTTP Cookie File\n",
            "Matching UA",
            "chrome",
            source="test",
            cookie_file=tmp_path / "cookies.txt",
        )
        return profile, ProbeResult("success", 0, "ok")

    def fake_command(self, slot, job):
        base = {
            "schema": 1,
            "run_id": run_id,
            "job_id": job["id"],
            "attempt_id": job["attempt_id"],
            "worker": slot,
            "url": job["canonical_url"],
            "wall_time": time.time(),
            "monotonic": time.monotonic(),
        }
        terminal = (
            {
                **base,
                "event": "job_terminal_failure",
                "data": {
                    "state": "failed_auth",
                    "category": "auth_challenge",
                    "message": "Cloudflare challenge",
                },
            }
            if job["attempts"] == 1
            else {
                **base,
                "event": "job_complete",
                "data": {"state": "succeeded", "images_done": 1, "images_total": 1, "bytes_done": 10},
            }
        )
        events = [{**base, "event": "worker_ready", "data": {"state": "running"}}, terminal]
        script = ";".join(f"print({json.dumps(json.dumps(event))}, flush=True)" for event in events)
        return [sys.executable, "-c", script]

    monkeypatch.setattr("mangadl.manager.refresh_profile", fake_refresh)
    monkeypatch.setattr(DownloadManager, "_worker_command", fake_command)
    try:
        assert DownloadManager(options, store).run() == 0
        jobs = store.jobs(run_id)
        assert [entry["state"] for entry in jobs] == ["succeeded", "succeeded"]
        assert [entry["attempts"] for entry in jobs] == [2, 2]
        assert len(refresh_calls) == 1
    finally:
        store.close()
