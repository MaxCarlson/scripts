#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import math
from procparsers.yt_dlp import parse_line

def test_meta_line_parsing():
    d = parse_line("TDMETA\tabc123\tCool Title Here")
    assert d and d["event"] == "meta"
    assert d["id"] == "abc123"
    assert d["title"] == "Cool Title Here"

def test_meta_with_unicode_and_tabs():
    d = parse_line("TDMETA\täbc\tTi\t tle – 漢字")
    assert d and d["event"] == "meta"
    assert d["id"] == "äbc"
    assert d["title"] == "Ti\t tle – 漢字"

def test_destination_parsing():
    d = parse_line("[download] Destination: /tmp/output/title.mp4")
    assert d and d["event"] == "destination"
    assert d["path"].endswith("title.mp4")

def test_already_variants():
    d1 = parse_line("[download] File is already downloaded and merged")
    d2 = parse_line("[download] myfile.mp4 has already been downloaded")
    d3 = parse_line("[download] myfile.webm has already been downloaded and merged")
    assert d1 and d1["event"] == "already"
    assert d2 and d2["event"] == "already"
    assert d3 and d3["event"] == "already"

def test_progress_eta_form_mib():
    d = parse_line("[download]  10.0% of 50.00MiB at 2.00MiB/s ETA 00:37")
    assert d and d["event"] == "progress"
    assert math.isclose(d["percent"], 10.0, rel_tol=1e-6)
    assert d["total"] == 50 * 1024 * 1024
    assert d["downloaded"] == 5 * 1024 * 1024  # 10% of 50 MiB
    assert d["speed_bps"] == 2 * 1024 * 1024
    # For yt-dlp we interpret ETA as MM:SS, so 00:37 -> 37s (downloader uses this for progress)
    assert d["eta_s"] == 37

def test_progress_eta_form_lowercase_units():
    d = parse_line("[download]  25.5% of 10.00mB at 1.00mib/s ETA 01:00")
    # NB: lowercase nonsense; our parser upper-cases units to handle these
    assert d and d["event"] == "progress"
    assert d["total"] == 10 * 1000 * 1000
    # 25.5% of 10MB -> 2.55MB
    assert d["downloaded"] == int(round(0.255 * 10 * 1000 * 1000))
    # speed 'mib/s' -> 1MiB/s -> 1048576 bps
    assert d["speed_bps"] == 1024 * 1024
    assert d["eta_s"] == 60

def test_progress_in_form_100pct():
    d = parse_line("[download] 100% of 25.00MB in 00:30")
    assert d and d["event"] == "progress"
    assert d["percent"] == 100.0
    assert d["total"] == 25 * 1000 * 1000
    assert d["downloaded"] == 25 * 1000 * 1000
    assert d["eta_s"] == 0  # treat 'in 00:30' as completion

def test_noise_lines_return_none():
    assert parse_line("[Merger] Merging formats into \"title.mp4\"") is None
    assert parse_line("WARNING: something something") is None
    assert parse_line("[subtitle] Downloading") is None

def test_ansi_stripping_before_match():
    # include ANSI color codes around a valid destination line
    ansi = "\x1b[32m[download]\x1b[0m Destination: /tmp/ok.mp4\x1b[0m"
    d = parse_line(ansi)
    assert d and d["event"] == "destination"
    assert d["path"].endswith("ok.mp4")
