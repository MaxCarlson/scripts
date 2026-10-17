import json

from PIL import Image

from compresser.cli import main


def test_multi_quality_comparison_shares_lossless_baseline(tmp_path, capsys):
    source = tmp_path / "01.png"
    Image.new("RGB", (60, 60), "white").save(source)
    before = source.read_bytes()
    args = ["-i", str(source), "-b", "-Q", "0.9", "0.8", "0.9", "-e", "0", "-J"]
    assert main(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 10
    assert len([r for r in rows if r["mode"] == "lossless"]) == 4
    assert {r["quality"] for r in rows if r["mode"] == "lossy"} == {"q=90", "q=80"}
    assert len({r["strategy"] for r in rows}) == 10
    assert {r["measured_images"] for r in rows} == {1}
    assert source.read_bytes() == before
    assert main(args) == 0
    warm = json.loads(capsys.readouterr().out)
    assert all(r["cache_hits"] == r["measured_images"] for r in warm if not r["failed_count"])


def test_lossy_only_quality_sweep_has_one_png_baseline(tmp_path, capsys):
    source = tmp_path / "01.png"
    Image.new("RGB", (40, 40), "white").save(source)
    assert main(["-i", str(source), "-c", "-m", "lossy", "--qualities", "90", "80", "-e", "0", "-J"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 7
    assert [r["format"] for r in rows].count("png") == 1
