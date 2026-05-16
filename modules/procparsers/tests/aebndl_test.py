#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from procparsers.aebndl import parse_line


def test_aebn_destination():
    d = parse_line("Destination: /videos/scene-001.mp4")
    assert d and d["event"] == "destination"
    assert d["path"].endswith("scene-001.mp4")


def test_aebn_json_progress_passthrough():
    d = parse_line('{"event":"progress","percent":42.5,"downloaded":1234,"total":5678,"speed_bps":9000}')
    assert d and d["event"] == "progress"
    assert d["percent"] == 42.5
    assert d["downloaded"] == 1234
    assert d["total"] == 5678
    assert d["speed_bps"] == 9000


def test_aebn_json_preview_fallback_passthrough():
    d = parse_line(
        '{"event":"preview_fallback","movie_id":"183004","scene_id":"865807",'
        '"start_seconds":3367,"end_seconds":3397,"format":"DASH"}'
    )
    assert d and d["event"] == "preview_fallback"
    assert d["movie_id"] == "183004"
    assert d["scene_id"] == "865807"
    assert d["start_seconds"] == 3367
    assert d["end_seconds"] == 3397


def test_aebn_json_manifest_error_passthrough():
    d = parse_line(
        '{"event":"manifest_error","error_type":"DeliveryAccessError",'
        '"message":"AEBN full delivery is not available"}'
    )
    assert d and d["event"] == "manifest_error"
    assert d["error_type"] == "DeliveryAccessError"
    assert "full delivery" in d["message"]


def test_aebn_progress_hh_mm():
    # Expect HH:MM semantics: 00:35 -> 35 minutes
    d = parse_line("120/480 segments at 10.5 it/s ETA 00:35")
    assert d and d["event"] == "aebn_progress"
    assert d["segments_done"] == 120
    assert d["segments_total"] == 480
    assert abs(d["rate_itps"] - 10.5) < 1e-6
    assert d["eta_s"] == 35 * 60  # 35 minutes

def test_aebn_progress_hh_mm_ss():
    d = parse_line("5/10 segments at 9.0 it/s ETA 01:02:03")
    assert d and d["event"] == "aebn_progress"
    assert d["segments_done"] == 5
    assert d["segments_total"] == 10
    assert abs(d["rate_itps"] - 9.0) < 1e-6
    assert d["eta_s"] == (1 * 3600 + 2 * 60 + 3)

def test_unmatched_returns_none():
    assert parse_line("some other line") is None
    assert parse_line("") is None
    assert parse_line("ETA 12:34 but no segments prefix") is None
