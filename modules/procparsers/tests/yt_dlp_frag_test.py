#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from procparsers.yt_dlp import parse_line


def test_progress_with_frag_and_unknown_eta():
    s = "[download]   0.1% of ~ 112.19MiB at    1.20KiB/s ETA Unknown (frag 0/232)"
    d = parse_line(s)
    assert d and d["event"] == "progress"
    assert d["percent"] == 0.1
    assert d["eta_s"] is None


def test_progress_with_frag_and_eta():
    s = "[download]   1.4% of ~ 339.77MiB at    3.52MiB/s ETA 01:20 (frag 4/232)"
    d = parse_line(s)
    assert d and d["event"] == "progress"
    assert d["percent"] == 1.4
    assert d["eta_s"] == 80

