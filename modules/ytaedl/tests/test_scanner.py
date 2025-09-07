import types
from pathlib import Path
from ytaedl.scanner import scan_url_file_main, scan_url_file_ae, _ytdlp_expected_filename as real_getname

def test_scan_url_file_main_counts_downloaded(tmp_path, monkeypatch):
    # Arrange: url file with two urls; one maps to existing file.
    url_dir = tmp_path / "files" / "downloads" / "stars"
    out_dir = tmp_path / "stars"
    url_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    uf = url_dir / "test.txt"
    uf.write_text("https://example.com/v/1\nhttps://example.com/v/2\n", encoding="utf-8")
    # Pretend yt-dlp would name files 'one.mp4' and 'two.mp4'
    names = {
        "https://example.com/v/1": (0, "one.mp4"),
        "https://example.com/v/2": (0, "two.mp4"),
    }
    def fake_getname(url: str, template: str = "%(title)s.%(ext)s"):
        return names[url]
    monkeypatch.setattr("ytaedl.scanner._ytdlp_expected_filename", fake_getname)
    # Create only one file as already downloaded
    (out_dir / "test" / "one.mp4").parent.mkdir(parents=True, exist_ok=True)
    (out_dir / "test" / "one.mp4").write_text("x", encoding="utf-8")

    rec = scan_url_file_main(uf, out_dir, {"mp4"})
    assert rec.url_count == 2
    assert rec.downloaded == 1
    assert rec.bad == 0
    assert rec.remaining == 1
    assert rec.viable_checked is True

def test_scan_url_file_ae_counts(tmp_path):
    url_dir = tmp_path / "files" / "downloads" / "ae-stars"
    out_dir = tmp_path / "stars"
    url_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)
    uf = url_dir / "ae.txt"
    # Include two URLs with different slugs
    uf.write_text("https://straight.aebn.com/movie/TITLE#scene-5\nhttps://straight.aebn.com/movie/OTHER#scene-6\n", encoding="utf-8")
    # Create only one expected file
    dest = out_dir / "ae"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "movie-scene-5.mp4").write_text("x", encoding="utf-8")

    rec = scan_url_file_ae(uf, out_dir, {"mp4"})
    assert rec.url_count == 2
    assert rec.downloaded == 1
    assert rec.bad == 0
    assert rec.remaining == 1
    assert rec.viable_checked is False
