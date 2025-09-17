#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import math
from procparsers.yt_dlp import parse_line

def _ib(n_mb):
    # helper to compute MiB to bytes as an int
    return int(round(n_mb * 1024 * 1024))

def test_progress_with_tilde_total_and_eta():
    s = "[download]   8.6% of ~ 713.54MiB at   25.16MiB/s ETA 00:28"
    d = parse_line(s)
    assert d and d["event"] == "progress"
    assert math.isclose(d["percent"], 8.6, rel_tol=1e-6)
    assert d["total"] == _ib(713.54)   # avoid float==int pitfalls
    # speed: 25.16 MiB/s
    assert int(d["speed_bps"]) == _ib(25.16)
    assert d["eta_s"] == 28

def test_progress_bare_100pct_line_no_eta():
    d = parse_line("[download] 100% of  348.09MiB")
    assert d and d["event"] == "progress"
    assert d["percent"] == 100.0
    assert d["total"] == _ib(348.09)
    assert d["downloaded"] == _ib(348.09)
    assert d["eta_s"] == 0  # treat bare 100% as completion

def test_already_then_100pct_sequence_is_parsed():
    d1 = parse_line("[download] stars\\x\\y.mp4 has already been downloaded")
    d2 = parse_line("[download] 100% of  394.18MiB")
    assert d1 and d1["event"] == "already"
    assert d2 and d2["event"] == "progress" and d2["percent"] == 100.0

def test_eta_unknown_is_tolerated():
    d = parse_line("[download]   2.5% of ~ 605.00MiB at   12.08MiB/s ETA Unknown")
    assert d and d["event"] == "progress"
    assert d["eta_s"] is None
