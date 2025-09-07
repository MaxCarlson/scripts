# file: tests/test_video_dedupe.py
import json
from pathlib import Path
import pytest
import video_dedupe as vd


@pytest.fixture()
def temp_tree(tmp_path: Path):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (a / "f1.mp4").write_bytes(b"hello world")
    (b / "f2.mp4").write_bytes(b"hello world")
    (a / "meta1.mkv").write_bytes(b"x" * 123)
    (b / "meta2.mkv").write_bytes(b"y" * 456)
    (a / "u1.txt").write_text("unique")
    return tmp_path


def test_iter_files_and_hash(temp_tree: Path):
    files = list(vd.iter_files(temp_tree, pattern=None, max_depth=None))
    assert len(files) == 5
    f1 = temp_tree / "A" / "f1.mp4"
    f2 = temp_tree / "B" / "f2.mp4"
    h1 = vd.sha256_file(f1)
    h2 = vd.sha256_file(f2)
    assert h1 is not None and h1 == h2


def test_hash_grouping(temp_tree: Path, monkeypatch: pytest.MonkeyPatch):
    g = vd.Grouper(mode="hash")

    def fake_hash(p: Path):
        if p.name in ("f1.mp4", "f2.mp4"):
            return "H"
        return f"h-{p.name}"

    monkeypatch.setattr(vd, "sha256_file", fake_hash)

    files = list(vd.iter_files(temp_tree, None, None))
    groups = g.collect(files)
    grouped = [v for v in groups.values() if len(v) > 1]
    assert len(grouped) == 1
    names = sorted(m.path.name for m in grouped[0])
    assert names == ["f1.mp4", "f2.mp4"]


def test_meta_grouping_with_tolerance(temp_tree: Path, monkeypatch: pytest.MonkeyPatch):
    def fake_probe(path: Path):
        st = path.stat()
        common = dict(path=path, size=st.st_size, mtime=st.st_mtime,
                      duration=None, width=None, height=None,
                      container="matroska", vcodec="h264", acodec="aac",
                      overall_bitrate=1_000_000, video_bitrate=900_000,
                      sha256=None, phash_signature=None)
        if path.name == "meta1.mkv":
            common.update(duration=100.0, width=1920, height=1080)
        elif path.name == "meta2.mkv":
            common.update(duration=102.0, width=1920, height=1080)
        else:
            return vd.VideoMeta(path=path, size=st.st_size, mtime=st.st_mtime)
        return vd.VideoMeta(**common)

    monkeypatch.setattr(vd, "probe_video", fake_probe)

    g = vd.Grouper(mode="meta", duration_tolerance=3.0, same_res=True)
    files = list(vd.iter_files(temp_tree, None, None))
    groups = g.collect(files)
    found = []
    for members in groups.values():
        names = sorted(m.path.name for m in members)
        if names == ["meta1.mkv", "meta2.mkv"]:
            found.append(names)
    assert len(found) == 1


def test_choose_winners_policy(temp_tree: Path):
    a = vd.VideoMeta(path=temp_tree/"A"/"x.mp4", size=10, mtime=10, duration=90, width=1280, height=720,
                     vcodec="h264", acodec=None, overall_bitrate=2_000_000, video_bitrate=1_500_000, container="mp4")
    b = vd.VideoMeta(path=temp_tree/"B"/"x.mp4", size=20, mtime=20, duration=95, width=1920, height=1080,
                     vcodec="h264", acodec=None, overall_bitrate=3_000_000, video_bitrate=2_200_000, container="mp4")
    groups = {"meta:0": [a, b]}

    winners = vd.choose_winners(groups, keep_order=["longer", "resolution", "video_bitrate", "newer"])
    keep, losers = winners["meta:0"]
    assert keep is b
    assert losers == [a]


def test_delete_or_backup_dry_run_and_report(temp_tree: Path, tmp_path: Path):
    f1 = vd.FileMeta(path=temp_tree/"A"/"f1.mp4", size=11, mtime=1)
    f2 = vd.FileMeta(path=temp_tree/"B"/"f2.mp4", size=11, mtime=1)
    groups = {"hash:H": [f1, f2]}
    winners = vd.choose_winners(groups, keep_order=["newer"])

    c, s = vd.delete_or_backup([l for (_, ls) in winners.values() for l in ls],
                               dry_run=True, force=True, backup_dir=None, base_root=temp_tree)
    assert c == 1 and s == 11

    rpath = tmp_path / "report.json"
    vd.write_report(rpath, winners)
    data = json.loads(rpath.read_text())
    assert data["summary"]["groups"] == 1
    assert data["summary"]["losers"] == 1


def test_backup_move(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    f = base / "u1.txt"
    f.write_text("unique")
    backup = tmp_path / "quarantine"
    dest = vd.ensure_backup_move(f, backup, base)
    assert dest.exists()
    assert dest.read_text() == "unique"
    assert not f.exists()
