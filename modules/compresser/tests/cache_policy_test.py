import json

from PIL import Image

from compresser.cli import main


def test_automatic_cache_use_refresh_and_off(tmp_path, capsys):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (40, 40), "white").save(gallery / "01.png")
    args = ["-i", str(gallery), "-f", "webp", "-e", "0", "-J"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["cache"]["file"] and first["cache_hits"] == 0
    assert main(args) == 0
    warm = json.loads(capsys.readouterr().out)
    assert warm["cache_hits"] == 1
    assert main(args + ["-k", "refresh"]) == 0
    fresh = json.loads(capsys.readouterr().out)
    assert fresh["cache_hits"] == 0 and fresh["cache"]["policy"] == "refresh"
    assert main(args + ["-k", "off"]) == 0
    disabled = json.loads(capsys.readouterr().out)
    assert disabled["cache"]["file"] is None and disabled["cache_hits"] == 0
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["cache_hits"] == 1
