import json

import pytest
from PIL import Image


def make_target(tmp_path):
    target = tmp_path / "book"
    target.mkdir()
    Image.new("RGB", (64, 64), "blue").save(target / "01.png", compress_level=0)
    return target


@pytest.mark.parametrize("manga", [False, True])
@pytest.mark.parametrize("depth", ["headers", "files"])
def test_inventory_creation_and_refresh_save_detailed_report(tmp_path, capsys, manga, depth):
    target = make_target(tmp_path)
    from compresser.cli import main as standalone
    from mangadl.cli import main as mangadl

    main = mangadl if manga else standalone
    flags = (["compress", "-d"] if manga else ["-i"]) + [str(target), "-I", str(tmp_path / "state"), "-l", depth, "-J"]
    for _ in range(2):
        assert main(flags) == 0
        payload = json.loads(capsys.readouterr().out)
        report = payload["report_artifacts"]
        text = __import__("pathlib").Path(report["archive"]).read_text(encoding="utf-8")
        assert "INVENTORY" in text and (".png" if depth == "files" else "PNG") in text and "book" in text
        assert ("unverified" in text.lower()) == (depth == "files")
    suffix = "mangadl" if manga else "compresser"
    ws = tmp_path / "state" / f"book-{suffix}"
    assert (ws / f"book-{suffix}-inventory.sqlite3").exists()
    assert not (ws / f"book-{suffix}-trials.sqlite3").exists()
    assert len(list((ws / "reports").glob("*-inventory.md"))) == 2


@pytest.mark.parametrize("operation", ["analysis", "comparison", "preview"])
def test_json_operations_save_reports_and_implicit_inventory(tmp_path, capsys, operation):
    from compresser.cli import main

    target = make_target(tmp_path)
    flags = ["-i", str(target), "-J", "-e", "0"]
    flags += {
        "analysis": ["-f", "png"],
        "comparison": ["-b", "-Q", "85", "70"],
        "preview": ["-O", "-n", "1", "-f", "webp"],
    }[operation]
    assert main(flags) == 0
    payload = json.loads(capsys.readouterr().out)
    artifact = (payload[0] if isinstance(payload, list) else payload)["report_artifacts"]
    text = __import__("pathlib").Path(artifact["latest"]).read_text(encoding="utf-8")
    assert operation in text.lower() and "\x1b[" not in text
    assert list((tmp_path / "book-compresser" / "reports").glob("*-inventory.md"))


def test_report_failure_returns_error_without_breaking_json(tmp_path, capsys, monkeypatch):
    import compresser.markdown_report as publication
    from compresser.cli import main

    target = make_target(tmp_path)
    monkeypatch.setattr(
        publication, "publish_markdown_report", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    assert main(["-i", str(target), "-l", "-J"]) == 2
    captured = capsys.readouterr()
    assert "disk full" in json.loads(captured.out)["report_artifacts"]["error"]
    assert "Report could not be saved" in captured.err


def test_cancelled_operation_saves_partial_report(tmp_path, capsys, monkeypatch):
    from compresser.cli import main
    from compresser.engine import CompressionEngine

    target = make_target(tmp_path)
    monkeypatch.setattr(CompressionEngine, "compress_batch", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert main(["-i", str(target), "-f", "png", "-N"]) == 130
    text = (tmp_path / "book-compresser" / "reports" / "latest.md").read_text(encoding="utf-8")
    assert "cancelled" in text.lower()


def test_invalid_arguments_create_no_workspace(tmp_path):
    from compresser.cli import main

    target = make_target(tmp_path)
    with pytest.raises(SystemExit):
        main(["-i", str(target), "-w", "-s", "1"])
    assert not (tmp_path / "book-compresser").exists()


def test_applied_write_report_failure_warns_without_undoing_source(tmp_path, capsys, monkeypatch):
    from compresser.cli import main
    import compresser.markdown_report as publication

    target = make_target(tmp_path)
    before = (target / "01.png").read_bytes()
    monkeypatch.setattr(
        publication, "publish_markdown_report", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    assert main(["-i", str(target), "-f", "png", "-w", "-J"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["applied_count"] == 1
    assert "may already have been modified" in captured.err
    assert (target / "01.png").read_bytes() != before


def test_manga_small_sample_trust_cache_scratch_and_report_scope(tmp_path, capsys):
    from mangadl.cli import main
    from pathlib import Path

    target = tmp_path / "library"
    for name in ("one", "two", "three"):
        directory = target / name
        directory.mkdir(parents=True)
        Image.new("RGB", (48, 48), "red").save(directory / "01.png", compress_level=0)
    before = {p: p.read_bytes() for p in target.rglob("*.png")}
    common = ["compress", "-d", str(target), "-I", str(tmp_path / "state"), "-J"]
    assert main(common + ["-l"]) == 0
    capsys.readouterr()
    flags = common + [
        "-U",
        "trust",
        "-b",
        "-Q",
        "85",
        "70",
        "-s",
        "1",
        "-t",
        "2",
        "-B",
        "128",
        "-e",
        "0",
        "-X",
        str(tmp_path / "ssd"),
    ]
    for _ in range(2):
        assert main(flags) == 0
        rows = json.loads(capsys.readouterr().out)
        assert all(row["extrapolation"]["saved_bytes"] is not None for row in rows)
        assert rows[0]["sampling"]["sampled_galleries"] == 1
    assert sum(row["cache_hits"] for row in rows) > 0
    saved = Path(rows[0]["report_artifacts"]["archive"]).read_text(encoding="utf-8")
    assert "Membership refreshed" in saved and "False" in saved
    assert "PHASE WORKER-SECONDS" in saved and "scratch_dir" in saved
    assert {p: p.read_bytes() for p in before} == before
