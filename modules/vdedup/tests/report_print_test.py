import json
from pathlib import Path
from vdedup.report import pretty_print_reports, collect_exclusions

def test_pretty_and_exclusions(tmp_path: Path):
    # create a tiny report
    rp = tmp_path / "r.json"
    data = {
        "summary": {"groups": 1, "losers": 1, "size_bytes": 1234, "by_method": {"hash": 1}},
        "groups": {
            "hash:deadbeef": {
                "keep": str(tmp_path / "keep.mp4"),
                "losers": [str(tmp_path / "lose.mp4")],
                "method": "hash",
                "evidence": {"sha256": "deadbeef"},
            }
        }
    }
    rp.write_text(json.dumps(data), encoding="utf-8")

    # pretty print
    text = pretty_print_reports([rp], verbosity=1)
    assert "Groups:" in text
    assert "By method:" in text

    # exclusions
    losers = collect_exclusions([rp])
    assert (tmp_path / "lose.mp4").resolve() in losers
