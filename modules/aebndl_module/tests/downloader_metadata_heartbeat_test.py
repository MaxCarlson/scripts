import json
import os
import time

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


def test_find_existing_output_matches_resolution_variants(tmp_path):
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

    # No files yet
    assert dl._find_existing_output(movie) is None

    # Small file (preview-sized) — should not match
    small = tmp_path / "TestStudio - My Great Movie 1080p.mp4"
    small.write_bytes(b"x" * (10 * 1024 * 1024))  # 10 MiB
    assert dl._find_existing_output(movie) is None

    # Large file (real movie) — should match
    large = tmp_path / "TestStudio - My Great Movie 1440p.mp4"
    large.write_bytes(b"x" * (200 * 1024 * 1024))  # 200 MiB
    assert dl._find_existing_output(movie) == str(large)


def test_run_emits_already_when_output_exists_before_manifest(tmp_path, monkeypatch, capsys):
    class FakeMovie:
        studio_name = ""
        title = "Some Movie"
        performers = []
        scenes = []
        movie_id = "123"

    existing_file = tmp_path / "- Some Movie 1080p.mp4"
    existing_file.write_bytes(b"x" * (300 * 1024 * 1024))  # 300 MiB

    monkeypatch.setattr(downloader_module, "Movie", lambda url, session: FakeMovie())

    dl = Downloader(
        "https://straight.aebn.com/straight/movies/123/some-movie",
        output_dir=str(tmp_path),
        json_output=True,
    )
    # Patch _initialize_download and _process_manifest to verify manifest is NOT called
    manifest_called = []

    monkeypatch.setattr(dl, "_initialize_download", lambda: None)
    monkeypatch.setattr(dl, "_process_manifest", lambda m: manifest_called.append(True))

    dl.run()

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    event_types = [e.get("event") for e in events]
    assert "already" in event_types
    assert "destination" in event_types
    assert not manifest_called, "_process_manifest should not be called when output already exists"
