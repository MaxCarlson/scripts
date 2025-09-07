import json
from pathlib import Path
import vdedup.video_dedupe as cli


def test_analysis_mode_monkeypatch(tmp_path: Path, monkeypatch):
    # fake _probe_stats so we don't need ffprobe
    def fake_probe(p: Path):
        # encode some numbers based on filename to get deltas
        base = 1000 if "keep" in p.name else 800
        return {
            "size": base * 1024,
            "duration": 3600.0 if "keep" in p.name else 1800.0,
            "width": 1920 if "keep" in p.name else 1280,
            "height": 1080 if "keep" in p.name else 720,
            "overall_bitrate": base * 10,
            "video_bitrate": base * 8,
        }

    monkeypatch.setattr(cli, "_probe_stats", fake_probe)

    # build a report
    rp = tmp_path / "report.json"
    keep = tmp_path / "keep.mp4"
    lose = tmp_path / "lose.mp4"
    keep.write_bytes(b"")  # touch
    lose.write_bytes(b"")
    data = {
        "groups": {
            "hash:abcd": {
                "keep": str(keep),
                "losers": [str(lose)],
                "method": "hash",
                "evidence": {"sha256": "abcd"},
            }
        },
        "summary": {"groups": 1, "losers": 1, "size_bytes": 800 * 1024},
    }
    rp.write_text(json.dumps(data), encoding="utf-8")

    out = cli.render_analysis_for_reports([rp], verbosity=1)
    assert "KEEP:" in out and "LOSE:" in out
    assert "duration" in out
    assert "size" in out
    # overall footer should be present
    assert "Overall totals:" in out
    assert "Duplicates (groups): 1" in out
    assert "Videos to delete" in out
    assert "Space to save" in out
