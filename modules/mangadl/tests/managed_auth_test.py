from __future__ import annotations

from pathlib import Path

import pytest

from mangadl.gallery_auth import ProbeResult
from mangadl.manager import DownloadManager, RunOptions


class RetryStore:
    def __init__(self) -> None:
        self.retries: list[tuple[object, ...]] = []

    def retry(self, *values) -> bool:
        self.retries.append(values)
        return True


def options(tmp_path: Path, **overrides) -> RunOptions:
    values = dict(
        run_id="managed-auth-test",
        destination=tmp_path / "downloads",
        archive=tmp_path / "archive.sqlite3",
        state_db=tmp_path / "state.sqlite3",
        log_dir=tmp_path / "logs",
        workers=1,
        retries=0,
        retry_wait=0,
        auth_dir=tmp_path / "auth",
        worker_start_delay=0,
        ui=False,
    )
    values.update(overrides)
    return RunOptions(**values)


def job(job_id: int = 1) -> dict[str, object]:
    return {
        "id": job_id,
        "attempt_id": f"attempt-{job_id}",
        "attempts": 1,
        "backend": "gallery-dl",
        "canonical_url": "https://www.mangakakalot.gg/manga/title",
    }


def test_managed_profile_is_resolved_per_gallery_job(tmp_path: Path) -> None:
    manager = DownloadManager(options(tmp_path), RetryStore())  # type: ignore[arg-type]
    profile = manager.auth_store.save(
        "mangakakalot.gg",
        "# Netscape HTTP Cookie File\n",
        "Matching UA",
        "chrome",
        source="chrome-cdp",
    )

    command = manager._worker_command(1, job())

    assert command[command.index("--cookies") + 1] == str(profile.cookie_path)
    assert command[command.index("--gallery-user-agent") + 1] == "Matching UA"


def test_explicit_credentials_win_over_managed_profile(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.txt"
    manager = DownloadManager(
        options(tmp_path, cookies=explicit, gallery_user_agent="Explicit UA"), RetryStore()  # type: ignore[arg-type]
    )
    profile = manager.auth_store.save(
        "mangakakalot.gg",
        "# Netscape HTTP Cookie File\n",
        "Managed UA",
        "chrome",
        source="chrome-cdp",
    )

    command = manager._worker_command(1, job())

    assert command.count("--cookies") == 1
    assert command[command.index("--cookies") + 1] == str(explicit)
    assert command[command.index("--gallery-user-agent") + 1] == "Explicit UA"


def test_one_domain_refresh_serves_multiple_failed_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RetryStore()
    manager = DownloadManager(options(tmp_path), store)  # type: ignore[arg-type]
    calls: list[str] = []
    profile = manager.auth_store.save(
        "mangakakalot.gg",
        "# Netscape HTTP Cookie File\n"
        ".mangakakalot.gg\tTRUE\t/\tTRUE\t4102444800\tcf_clearance\tstale-secret\n",
        "Unchanged UA",
        "chrome",
        source="chrome-cdp",
    )

    def fake_refresh(url, **kwargs):
        calls.append(url)
        return profile, ProbeResult("success", 0, "ok")

    monkeypatch.setattr("mangadl.manager.refresh_profile", fake_refresh)
    event1 = {"job_id": 1, "attempt_id": "attempt-1", "url": job()["canonical_url"], "data": {}}
    event2 = {"job_id": 2, "attempt_id": "attempt-2", "url": job()["canonical_url"], "data": {}}

    assert manager._retry_after_auth(1, event1, job(1), "403")
    assert manager._retry_after_auth(1, event2, job(2), "403")
    assert not manager._retry_after_auth(1, event1, job(1), "403")
    assert len(calls) == 1
    assert calls == ["https://www.mangakakalot.gg/manga/title"]
    assert len(store.retries) == 2


def test_explicit_credentials_disable_automatic_browser_refresh(tmp_path: Path) -> None:
    manager = DownloadManager(options(tmp_path, cookies=tmp_path / "cookies.txt"), RetryStore())  # type: ignore[arg-type]
    assert not manager._can_manage_auth(job())


def test_browser_refresh_error_does_not_crash_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    manager = DownloadManager(options(tmp_path), RetryStore())  # type: ignore[arg-type]
    monkeypatch.setattr(
        "mangadl.manager.refresh_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("chrome unavailable")),
    )
    event = {"job_id": 1, "attempt_id": "attempt-1", "url": job()["canonical_url"], "data": {}}

    assert not manager._retry_after_auth(1, event, job(1), "403")
    assert "chrome unavailable" in capsys.readouterr().err
