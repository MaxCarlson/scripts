from ytaedl.parsers import parse_aebndl_line


def test_parse_aebn_destination():
    line = "Output file name: Dorcel – Luxure 1440p.mp4"
    d = parse_aebndl_line(line)
    assert d and d["event"] == "destination"
    assert d["path"].endswith("1440p.mp4")


def test_parse_aebn_progress_audio():
    line = "Audio download: 4% | 147/3450 [00:15<04:52, 11.30it/s]"
    d = parse_aebndl_line(line)
    assert d and d["event"] == "aebn_progress"
    assert d["stream"] == "audio"
    assert d["segments_done"] == 147
    assert d["segments_total"] == 3450
    assert d["eta_s"] > 0
    assert d["rate_itps"] > 0


def test_parse_aebn_progress_video():
    line = "Video download: 2% | 70/3450 [00:14<24:38, 2.29it/s]"
    d = parse_aebndl_line(line)
    assert d and d["event"] == "aebn_progress"
    assert d["stream"] == "video"
    assert d["segments_done"] == 70
    assert d["segments_total"] == 3450
