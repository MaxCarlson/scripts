"""Tests for ytaedl log audit helpers."""

from __future__ import annotations

from ytaedl.log_audit import audit_logs, format_audit


def test_log_audit_counts_events_archives_and_flags(tmp_path):
    log_dir = tmp_path / "logs"
    archive_dir = tmp_path / "archive"
    log_dir.mkdir()
    archive_dir.mkdir()

    (log_dir / "dlmanager-20260509-000000-1.log").write_text(
        "\n".join(
            [
                "12:00:00|INFO|[01] FALLBACK_EXHAUSTED url=https://example.com/a",
                "12:00:01|INFO|[02] FALLBACK_EXHAUSTED url=https://example.com/b",
                "12:00:02|INFO|[03] REQUEUE_FAILED url=https://other.test/c",
                "12:00:03|INFO|[04] DEST path=C:/tmp/_TPL_.mp4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (log_dir / "ytaedler-worker-01.log").write_text(
        "0001|1.0|DOWNLOAD_START|url\n0002|2.0|PROGRESS|50%\n0003|3.0|DOWNLOAD_DONE|ok\n",
        encoding="utf-8",
    )
    (log_dir / "domain_index.json").write_text('{"urls": [{"url": "https://example.com/a"}]}', encoding="utf-8")
    (archive_dir / "yt-alpha.txt").write_text(
        "already\t0.0\t2026-05-09T00:00:00\t0\tid\thttps://example.com/a\n"
        "failed\t1.0\t2026-05-09T00:00:01\t0\tid\thttps://example.com/b\n",
        encoding="utf-8",
    )

    summary = audit_logs(log_dir, archive_dir)

    assert summary.manager_logs == 1
    assert summary.worker_logs == 1
    assert summary.event_counts["FALLBACK_EXHAUSTED"] == 2
    assert summary.event_counts["REQUEUE_FAILED"] == 1
    assert summary.archive_status_counts == {"already": 1, "failed": 1}
    assert summary.fallback_exhausted_domains == {"example.com": 2}
    assert len(summary.tpl_destination_hits) == 1
    assert summary.traceback_hits == []
    assert summary.domain_index_present is True
    assert "tpl_hits=1" in format_audit(summary)
