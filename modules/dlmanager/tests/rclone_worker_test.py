# -*- coding: utf-8 -*-
import dlmanager.workers.rclone_worker as rclone_worker


def test_parse_stats_message_extracts_bytes():
    msg = "Transferred:   10.000 MiB / 20.000 MiB, 50%, 5.000 MiB/s, ETA 2m0s"
    parsed = rclone_worker.parse_stats_message(msg)
    assert parsed["bytes_done"] == 10 * 1024 * 1024
    assert parsed["bytes_total"] == 20 * 1024 * 1024
    assert parsed["percent"] == 50.0
    assert parsed["bytes_per_s"] == 5 * 1024 * 1024
    assert parsed["eta_seconds"] == 120


def test_parse_stats_message_handles_unknown_eta():
    msg = "Transferred:   1.000 GiB / 2.000 GiB, 25%, 10.000 MiB/s, ETA -"
    parsed = rclone_worker.parse_stats_message(msg)
    assert parsed["eta_seconds"] is None
