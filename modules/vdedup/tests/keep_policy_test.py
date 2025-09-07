from pathlib import Path
from vdedup.models import FileMeta, VideoMeta
from vdedup.grouping import choose_winners

def test_choose_winners_prefers_longer():
    a = VideoMeta(path=Path("a.mp4"), size=10, mtime=1, duration=60, width=640, height=360)
    b = VideoMeta(path=Path("b.mp4"), size=20, mtime=2, duration=120, width=640, height=360)
    groups = {"g1": [a, b]}
    winners = choose_winners(groups, ["longer","resolution","video-bitrate","newer","smaller","deeper"])
    assert str(winners["g1"][0].path) == "b.mp4"
