from pathlib import Path

from vdedup.models import VideoMeta
from vdedup.report import write_report
from vdedup.report_models import load_report_documents


def _video_meta(path: Path, duration: float) -> VideoMeta:
    return VideoMeta(
        path=path,
        size=100,
        mtime=0.0,
        duration=duration,
        width=1920,
        height=1080,
        container="mp4",
        vcodec="h264",
        acodec="aac",
        overall_bitrate=1000,
        video_bitrate=900,
    )


def test_write_report_persists_overlap_metadata(tmp_path: Path) -> None:
    keep = _video_meta(tmp_path / "keep.mp4", duration=120.0)
    loser = _video_meta(tmp_path / "clip.mp4", duration=30.0)
    winners = {"subset:1": (keep, [loser])}
    metadata = {
        "subset:1": {
            "detector": "subset-phash",
            "overlap_hints": {
                str(keep.path): 42.0,
                str(loser.path): 0.0,
            },
        }
    }
    report_path = tmp_path / "subset-report.json"
    write_report(report_path, winners, metadata=metadata)

    docs = load_report_documents([report_path])
    assert docs, "Report document should load"
    group = docs[0].groups[0]
    assert group.keep.overlap_hint == 42.0
    assert group.losers[0].overlap_hint == 0.0
