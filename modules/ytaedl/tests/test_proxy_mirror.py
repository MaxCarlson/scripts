import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ytaedl.downloader as downloader
import ytaedl.manager as manager


class DummyProc:
    def __init__(self, rc: int = 0):
        self._rc = rc
        self.stdout = None
        self._terminated = False

    def terminate(self):
        self._terminated = True

    def kill(self):
        self._terminated = True

    def wait(self, timeout: float | None = None):
        return self._rc

    def poll(self):
        return self._rc if self._terminated else None


@pytest.fixture(autouse=True)
def _isolate_tmp(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    yield


def _fake_events(path: Path):
    return [
        {"event": "start"},
        {"event": "destination", "path": str(path)},
        {"event": "progress", "downloaded": 50, "total": 100},
        {"event": "finish", "rc": 0},
    ]


def test_run_one_downloads_into_proxy_folder(monkeypatch, tmp_path):
    proxy_dir = tmp_path / "proxy"
    canonical_dir = tmp_path / "canonical"
    work_dir = tmp_path / "work"
    raw_dir = tmp_path / "raw"
    for d in (proxy_dir, canonical_dir, work_dir, raw_dir):
        d.mkdir(parents=True)

    final_proxy_file = proxy_dir / "video.mp4"

    def fake_iter(tool, stdout, raw_log_path=None, heartbeat_secs=None):
        final_proxy_file.write_text("data", encoding="utf-8")
        for evt in _fake_events(final_proxy_file):
            yield evt

    monkeypatch.setattr(downloader, "iter_parsed_events", fake_iter)
    monkeypatch.setattr(downloader.subprocess, "Popen", lambda *a, **k: DummyProc())

    rc, info = downloader._run_one(
        tool="yt-dlp",
        urls=["https://example.com"],
        out_dir=proxy_dir,
        canonical_out_dir=canonical_dir,
        work_dir=work_dir,
        raw_dir=raw_dir,
        url_index=1,
        proglog=downloader.ProgLogger(path=tmp_path / "log.txt", t0=0.0),
        timeout=None,
        retries=0,
        quiet=True,
        dry_run=False,
        progress_freq_s=None,
        max_ndjson_rate=-1,
        stall_seconds=None,
        program_deadline=None,
        max_dl_speed=None,
        max_height=None,
    )

    assert rc == 0
    assert not info.get("already")
    assert final_proxy_file.read_text(encoding="utf-8") == "data"
    assert not list(canonical_dir.glob("**/*"))


def test_run_one_skips_when_canonical_has_file(monkeypatch, tmp_path):
    proxy_dir = tmp_path / "proxy"
    canonical_dir = tmp_path / "canonical"
    work_dir = tmp_path / "work"
    raw_dir = tmp_path / "raw"
    for d in (proxy_dir, canonical_dir, work_dir, raw_dir):
        d.mkdir(parents=True)

    final_proxy_path = proxy_dir / "video.mp4"
    canonical_target = canonical_dir / "video.mp4"
    canonical_target.write_text("existing", encoding="utf-8")

    terminate_called = []

    class Proc(DummyProc):
        def terminate(self):
            terminate_called.append(True)
            super().terminate()

    def fake_iter(tool, stdout, raw_log_path=None, heartbeat_secs=None):
        final_proxy_path.write_text("new", encoding="utf-8")
        for evt in _fake_events(final_proxy_path):
            yield evt

    monkeypatch.setattr(downloader, "iter_parsed_events", fake_iter)
    monkeypatch.setattr(downloader.subprocess, "Popen", lambda *a, **k: Proc())

    rc, info = downloader._run_one(
        tool="yt-dlp",
        urls=["https://example.com"],
        out_dir=proxy_dir,
        canonical_out_dir=canonical_dir,
        work_dir=work_dir,
        raw_dir=raw_dir,
        url_index=1,
        proglog=downloader.ProgLogger(path=tmp_path / "log.txt", t0=0.0),
        timeout=None,
        retries=0,
        quiet=True,
        dry_run=False,
        progress_freq_s=None,
        max_ndjson_rate=-1,
        stall_seconds=None,
        program_deadline=None,
        max_dl_speed=None,
        max_height=None,
    )

    assert rc == 0
    assert info.get("already")
    assert terminate_called
    assert not final_proxy_path.exists()
    assert canonical_target.exists()


def test_manager_start_worker_propagates_proxy_flag(monkeypatch, tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://example.com\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    proxy_root = tmp_path / "proxy"

    captured_cmd: list[list[str]] = []
    fake_proc = MagicMock()

    monkeypatch.setattr(manager.subprocess, "Popen", lambda cmd, **_: captured_cmd.append(cmd) or fake_proc)

    proc = manager._start_worker(
        slot=1,
        urlfile=url_file,
        max_rate=5.0,
        quiet=False,
        archive_dir=None,
        log_dir=log_dir,
        cap_mibs=None,
        proxy_dl_location=str(proxy_root),
        max_resolution=None,
    )

    assert proc is fake_proc
    assert captured_cmd, "expected subprocess command"
    cmd = captured_cmd[0]
    assert "--proxy-dl-location" in cmd
    idx = cmd.index("--proxy-dl-location")
    assert cmd[idx + 1] == str(proxy_root)
