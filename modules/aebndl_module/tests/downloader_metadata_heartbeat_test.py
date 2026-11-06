import json
import hashlib
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from aebn_dl import downloader as downloader_module
from aebn_dl.downloader import Downloader


class DummyMovie:
    pass


def test_scrape_movie_info_emits_metadata_fetch_while_blocked(monkeypatch, capsys):
    def slow_movie(url, session):
        time.sleep(1.2)
        return DummyMovie()

    monkeypatch.setattr(downloader_module, "Movie", slow_movie)
    dl = Downloader("https://straight.aebn.com/straight/movies/1/example", json_output=True)

    assert isinstance(dl._scrape_movie_info(), DummyMovie)

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert any(event.get("event") == "metadata_fetch" for event in events)


def test_find_existing_output_requires_media_validation(tmp_path, monkeypatch):
    class FakeMovie:
        studio_name = "TestStudio"
        title = "My Great Movie"
        performers = []
        scenes = []

    dl = Downloader(
        "https://straight.aebn.com/straight/movies/1/my-great-movie",
        output_dir=str(tmp_path),
        json_output=True,
    )
    movie = FakeMovie()
    monkeypatch.setattr(
        dl, "_validate_output",
        lambda path, duration: {"valid": Path(path).stat().st_size > 50 * 1024 * 1024, "errors": ["fixture"]},
    )

    # No files yet
    assert dl._find_existing_output(movie) is None

    # Small file (preview-sized) — should not match
    small = tmp_path / "TestStudio - My Great Movie 1080p.mp4"
    small.write_bytes(b"x" * (10 * 1024 * 1024))  # 10 MiB
    with pytest.raises(ValueError, match="invalid and was preserved"):
        dl._find_existing_output(movie)
    small.unlink()

    # Large file (real movie) — should match
    large = tmp_path / "TestStudio - My Great Movie 1440p.mp4"
    large.write_bytes(b"x" * (200 * 1024 * 1024))  # 200 MiB
    assert dl._find_existing_output(movie) == str(large)


@pytest.mark.parametrize("studio,filename", [
    ("", "Movie Scene 2 720p.mp4"),
    ("", "- Movie Scene 2 720p.mp4"),
    ("Studio", "Studio - Movie Scene 2 720p.mp4"),
])
def test_existing_scene_matches_current_and_legacy_names(tmp_path, monkeypatch, studio, filename):
    movie = type("Movie", (), {"studio_name": studio, "title": "Movie"})()
    dl = Downloader("https://straight.aebn.com/straight/movies/1/title", output_dir=str(tmp_path), no_part=True)
    dl.scene_n = 2
    path = tmp_path / filename
    path.write_bytes(b"fixture")
    monkeypatch.setattr(dl, "_validate_output", lambda path, duration: {"valid": True, "errors": []})
    assert dl._find_existing_output(movie, 30) == str(path)


@pytest.mark.parametrize("scene_n,filename", [
    (1, "Movie Scene 10 720p.mp4"),
    (None, "Movie Scene 1 720p.mp4"),
])
def test_existing_output_does_not_match_another_scene_or_movie(tmp_path, monkeypatch, scene_n, filename):
    movie = type("Movie", (), {"studio_name": "", "title": "Movie"})()
    dl = Downloader("https://straight.aebn.com/straight/movies/1/title", output_dir=str(tmp_path), no_part=True)
    dl.scene_n = scene_n
    (tmp_path / filename).write_bytes(b"fixture")
    monkeypatch.setattr(dl, "_validate_output", lambda path, duration: {"valid": True, "errors": []})
    assert dl._find_existing_output(movie, 30) is None


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools unavailable")
@pytest.mark.parametrize("valid", [True, False])
def test_secondary_existing_output_is_independently_validated(tmp_path, monkeypatch, capsys, valid):
    from types import SimpleNamespace
    secondary = tmp_path / "secondary"
    secondary.mkdir()
    candidate = secondary / "Movie 720p.mp4"
    video_duration = 4 if valid else 1
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=160x90:rate=10:duration={video_duration}", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=4", "-c:v", "libx264", "-c:a", "aac",
                    str(candidate)], check=True, capture_output=True, text=True)
    original_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    movie = SimpleNamespace(studio_name="", title="Movie", performers=[], scenes=[],
                            movie_id="123", total_duration_seconds=4)
    dl = Downloader("https://straight.aebn.com/straight/movies/123/title", output_dir=str(tmp_path / "output"),
                    existing_output_dirs=[str(secondary)], json_output=True, no_part=True)
    monkeypatch.setattr(dl, "_initialize_download", lambda: None)
    monkeypatch.setattr(dl, "_scrape_movie_info", lambda: movie)
    monkeypatch.setattr(dl, "_process_manifest", lambda movie: setattr(dl, "manifest", SimpleNamespace(
        total_number_of_data_segments=15, video_stream=SimpleNamespace(height=480))))
    if valid:
        dl.run()
        events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert any(event["event"] == "already" and event["path"] == str(candidate) for event in events)
    else:
        with pytest.raises(ValueError, match="invalid and was preserved"):
            dl.run()
        events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert not any(event["event"] in {"already", "complete"} for event in events)
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == original_hash


def test_run_emits_already_only_after_manifest_validation(tmp_path, monkeypatch, capsys):
    class FakeMovie:
        studio_name = ""
        title = "Some Movie"
        performers = []
        scenes = []
        movie_id = "123"
        total_duration_seconds = 1800

    existing_file = tmp_path / "- Some Movie 1080p.mp4"
    existing_file.write_bytes(b"x" * (300 * 1024 * 1024))  # 300 MiB

    monkeypatch.setattr(downloader_module, "Movie", lambda url, session: FakeMovie())

    dl = Downloader(
        "https://straight.aebn.com/straight/movies/123/some-movie",
        output_dir=str(tmp_path),
        json_output=True,
    )
    # Existing output requires current manifest and duration metadata.
    manifest_called = []

    monkeypatch.setattr(dl, "_initialize_download", lambda: None)
    def prepare_manifest(_movie):
        manifest_called.append(True)
        dl.manifest = type(
            "ManifestStub", (),
            {"total_number_of_data_segments": 1, "video_stream": type("VideoStub", (), {"height": 480})()},
        )()

    monkeypatch.setattr(dl, "_process_manifest", prepare_manifest)
    monkeypatch.setattr(dl, "_find_existing_output", lambda _movie, _duration=None: str(existing_file))
    monkeypatch.setattr(dl, "_validate_output", lambda _path, _duration: {"valid": True, "evidence": {}})

    dl.run()

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    event_types = [e.get("event") for e in events]
    assert "already" in event_types
    assert "destination" in event_types
    assert manifest_called, "_process_manifest must run before validating an existing output"
