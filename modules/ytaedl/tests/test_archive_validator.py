"""Tests for archive validation and JSON repair-plan handling."""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path
from unittest.mock import patch

from ytaedl import archive_validator
from ytaedl.downloader import _format_archive_line


def _write_archive_line(path: Path, status: str, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _format_archive_line(status, 1.0, "2026-05-30T00:00:00Z", 0.0, "", url),
        encoding="utf-8",
    )


def test_load_archive_urls_parses_status_url_and_ignores_rebuild(tmp_path):
    archive_dir = tmp_path / "archive"
    _write_archive_line(archive_dir / "yt-alpha.txt", "bad-url", "https://example.com/watch?v=1")
    _write_archive_line(archive_dir / "yt-alpha.rebuild.txt", "downloaded", "https://example.com/skip")

    entries = archive_validator.load_archive_urls(archive_dir)

    assert len(entries) == 1
    assert entries[0].archive_status == "bad-url"
    assert entries[0].url == "https://example.com/watch?v=1"
    assert entries[0].archive_line == 1


def test_validate_records_bad_to_viable_mismatch_and_json_plan(tmp_path):
    archive_dir = tmp_path / "archive"
    log_dir = tmp_path / "logs"
    url = "https://example.com/watch?v=1"
    _write_archive_line(archive_dir / "yt-alpha.txt", "bad-url", url)

    with patch("ytaedl.archive_validator._simulate_check") as simulate:
        simulate.return_value.is_duplicate = False
        simulate.return_value.existing_path = None
        simulate.return_value.predicted_name = "Video.mp4"
        summary = archive_validator.validate_archive(
            archive_dir=archive_dir,
            log_dir=log_dir,
            validation_log_dir=tmp_path / "validation-logs",
            download_roots=[tmp_path / "stars"],
            workers=1,
            order="url-file",
            max_seconds=None,
            max_count=None,
            ratio=None,
            count_partials=False,
            simulate_timeout=1,
            cookies_from_browser=None,
            impersonate=None,
            verify_aebn_metadata=False,
            realtime=False,
        )

    assert summary.processed == 1
    assert summary.mismatches[0].transition == "bad-url -> viable"

    plan = archive_validator.build_change_plan(summary, archive_dir=archive_dir, log_dir=log_dir)
    assert plan["changes"][0]["action"] == "remove_archive_entry"
    assert plan["changes"][0]["domain_index_action"] == "remove_finished"


def test_apply_change_plan_removes_viable_archive_entry(tmp_path):
    archive_dir = tmp_path / "archive"
    log_dir = tmp_path / "logs"
    url = "https://example.com/watch?v=1"
    archive_file = archive_dir / "yt-alpha.txt"
    _write_archive_line(archive_file, "bad-url", url)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "version": 1,
                "archive_dir": str(archive_dir),
                "log_dir": str(log_dir),
                "changes": [
                    {
                        "url": url,
                        "archive_file": str(archive_file),
                        "old_status": "bad-url",
                        "new_status": "viable",
                        "action": "remove_archive_entry",
                        "domain_index_action": "remove_finished",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rc = archive_validator.apply_change_plan(plan_path, archive_dir=None, log_dir=None, dry_run=False)

    assert rc == 0
    assert archive_file.read_text(encoding="utf-8") == ""


def test_order_limit_ratio_selects_first_ratio(tmp_path):
    archive_dir = tmp_path / "archive"
    for idx in range(4):
        _write_archive_line(archive_dir / f"yt-{idx}.txt", "bad-url", f"https://example.com/{idx}")

    with patch("ytaedl.archive_validator._simulate_check") as simulate:
        simulate.return_value.is_duplicate = False
        simulate.return_value.existing_path = None
        simulate.return_value.predicted_name = "Video.mp4"
        summary = archive_validator.validate_archive(
            archive_dir=archive_dir,
            log_dir=tmp_path / "logs",
            validation_log_dir=tmp_path / "validation-logs",
            download_roots=[tmp_path / "stars"],
            workers=1,
            order="url-file",
            max_seconds=None,
            max_count=None,
            ratio=0.5,
            count_partials=False,
            simulate_timeout=1,
            cookies_from_browser=None,
            impersonate=None,
            verify_aebn_metadata=False,
            realtime=False,
        )

    assert summary.processed == 2


def test_aebn_folder_mp4_does_not_mark_every_url_preexisting(tmp_path):
    archive_dir = tmp_path / "archive"
    url = "https://straight.aebn.com/straight/movies/266837/stepmoms-teach-sex-20#scene-1150674"
    _write_archive_line(archive_dir / "ae-katie_kush.txt", "bad-url", url)
    download_dir = tmp_path / "stars" / "katie_kush"
    download_dir.mkdir(parents=True)
    (download_dir / "unrelated completed video.mp4").write_bytes(b"mp4")

    summary = archive_validator.validate_archive(
        archive_dir=archive_dir,
        log_dir=tmp_path / "logs",
        validation_log_dir=tmp_path / "validation-logs",
        download_roots=[tmp_path / "stars"],
        workers=1,
        order="url-file",
        max_seconds=None,
        max_count=None,
        ratio=None,
        count_partials=False,
        simulate_timeout=1,
        cookies_from_browser=None,
        impersonate=None,
        verify_aebn_metadata=False,
        realtime=False,
    )

    assert summary.processed == 1
    assert summary.unknown_count == 1
    assert summary.mismatches == []
    assert summary.status_counts["unknown"] == 1


def test_aebn_metadata_check_uses_aebndl_existing_output(monkeypatch, tmp_path):
    entry = archive_validator.ArchiveUrl(
        url="https://straight.aebn.com/straight/movies/266837/stepmoms-teach-sex-20#scene-1150674",
        archive_status="bad-url",
        archive_file=tmp_path / "archive" / "ae-katie_kush.txt",
        archive_line=1,
        archive_text="",
        source_group="ae-katie_kush",
    )
    existing = tmp_path / "stars" / "katie_kush" / "Studio - Title 1080p.mp4"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"x" * 64 * 1024 * 1024)

    class DummyDownloader:
        def __init__(self, **kwargs):
            self.output_dir = kwargs["output_dir"]
            self.logger = None

        def _initialize_download(self):
            return None

        def _scrape_movie_info(self):
            return object()

        def _find_existing_output(self, _movie):
            return str(existing) if Path(self.output_dir) == existing.parent else None

    monkeypatch.setitem(sys.modules, "aebn_dl", type("M", (), {"Downloader": DummyDownloader}))

    result = archive_validator.inspect_url(
        entry,
        download_roots=[tmp_path / "stars"],
        count_partials=False,
        simulate_timeout=1,
        cookies_from_browser=None,
        impersonate=None,
        verify_aebn_metadata=True,
        validation_log_dir=tmp_path / "validation-logs",
    )

    assert result.status == "preexisting"
    assert result.downloader == "aebndl-metadata"
    assert result.present_path == str(existing)


def test_validation_writes_master_and_worker_logs(tmp_path):
    archive_dir = tmp_path / "archive"
    log_dir = tmp_path / "logs"
    validation_log_dir = tmp_path / "validation-logs"
    url = "https://example.com/watch?v=1"
    _write_archive_line(archive_dir / "yt-alpha.txt", "bad-url", url)

    with patch("ytaedl.archive_validator._simulate_check") as simulate:
        simulate.return_value.is_duplicate = False
        simulate.return_value.existing_path = None
        simulate.return_value.predicted_name = "Video.mp4"
        archive_validator.validate_archive(
            archive_dir=archive_dir,
            log_dir=log_dir,
            validation_log_dir=validation_log_dir,
            download_roots=[tmp_path / "stars"],
            workers=1,
            order="url-file",
            max_seconds=None,
            max_count=None,
            ratio=None,
            count_partials=False,
            simulate_timeout=1,
            cookies_from_browser=None,
            impersonate=None,
            verify_aebn_metadata=False,
            realtime=False,
        )

    assert (validation_log_dir / "archive-validate-master.log").exists()
    worker_log = validation_log_dir / "archive-validate-worker-01.log"
    assert worker_log.exists()
    content = worker_log.read_text(encoding="utf-8")
    assert "START worker=01 [Y]" in content
    assert "RESULT worker=01 [Y]" in content


def test_parser_uses_threads_short_for_worker_count():
    args = archive_validator.build_parser().parse_args(["-t", "8"])

    assert args.workers == 8


def test_worker_alias_remains_hidden_but_supported():
    parser = archive_validator.build_parser()
    args = parser.parse_args(["-w", "3"])

    assert args.workers == 3
    assert "--workers" not in parser.format_help()


def test_pop_next_entry_skips_archive_file_already_active(tmp_path):
    active_file = tmp_path / "archive" / "yt-alpha.txt"
    other_file = tmp_path / "archive" / "yt-beta.txt"
    first = archive_validator.ArchiveUrl("https://example.com/1", "bad-url", active_file, 1, "", "yt-alpha")
    second = archive_validator.ArchiveUrl("https://example.com/2", "bad-url", other_file, 1, "", "yt-beta")
    pending = deque([first, second])

    picked = archive_validator._pop_next_entry_exclusive_by_file(pending, {active_file})

    assert picked == second
    assert list(pending) == [first]
