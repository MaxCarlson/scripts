#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from procparsers.aebndl import parse_line

def test_aebn_destination():
    d = parse_line("Destination: /videos/scene-001.mp4")
    assert d and d["event"] == "destination"
    assert d["path"].endswith("scene-001.mp4")

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
