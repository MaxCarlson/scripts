#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import math
from procparsers.yt_dlp import parse_line

def test_progress_with_tilde_total_and_eta():
    # From your log: "~ 713.54MiB" and normal ETA
    s = "[download]   8.6% of ~ 713.54MiB at   25.16MiB/s ETA 00:28"
    d = parse_line(s)
    assert d and d["event"] == "progress"
    assert math.isclose(d["percent"], 8.6, rel_tol=1e-6)
    assert d["total"] == 713.54 * 1024 * 1024
    # speed 25.16MiB/s
    assert d["speed_bps"] == 25.16 * 1024 * 1024
    assert d["eta_s"] == 28

def test_progress_100pct_without_in_clause():
    # From your "already" runs: completion line without "in 00:.."
    s = "[download] 100% of  348.09MiB"
    d = parse_line(s)
    assert d and d["event"] == "progress"
    assert d["percent"] == 100.0
    assert d["total"] == int(348.09 * 1024 * 1024)
    assert d["downloaded"] == d["total"]
    # no explicit "in ..." present -> treat as done
    assert d["eta_s"] == 0

def test_already_downloaded_path_form():
    # From your "already here" examples
    s = "[download] stars\\aliceleo\\I almost CHOKED myself to death with this HUGE DICK! But it was REALLY worth it!.mp4 has already been downloaded"
    d = parse_line(s)
    assert d and d["event"] == "already"
