import json
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
