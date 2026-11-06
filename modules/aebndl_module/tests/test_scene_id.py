"""Offline regression tests for resolving AEBN scene IDs to ordinals."""

import json
import subprocess
import sys

import pytest

from aebn_dl.cli import main
from aebn_dl.downloader import Downloader
from aebn_dl.models import Scene
from aebn_dl.movie_scraper import Movie


def movie_html(scene_ids):
    sections = []
    for scene_id in scene_ids:
        scene_attr = "" if scene_id is None else f' id="scene-{scene_id}"'
        sections.append(f'<section{scene_attr}><li class="dts-scene-strip-stars"></li></section>')
    sections = "".join(sections)
    return f"""
    <html><body>
      <div class="dts-section-page-heading-title"><h1>Fixture Movie</h1></div>
      <div class="section-detail-list-item-duration">unused</div>
      <div class="section-detail-list-item-duration">01:00:00</div>
      <div class="dts-studio-name-wrapper"><a>Fixture Studio</a></div>
      <section id="dtsPanelStarsDetailMovie"><a title="Performer"></a></section>
      {sections}
    </body></html>
    """.encode()


class FakeResponse:
    def __init__(self, content, status_error=None):
        self.content = content
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def make_movie(scene_ids):
    session = FakeSession([FakeResponse(movie_html(scene_ids))])
    movie = Movie("https://straight.aebn.com/straight/movies/123/fixture", session)
    return movie, session


@pytest.mark.parametrize(
    ("scene_ids", "scene_id", "ordinal"),
    [
        (["1303588", "1303589", "1303590"], "1303588", 1),
        (["1303588", "1303589", "1303590"], "1303589", 2),
        (["1303588", "1303589", "1303590"], "1303590", 3),
        (["1279786", "1279787", "1000000", "1279789"], "1279786", 1),
        (["1279786", "1279787", "1000000", "1279789"], "1279787", 2),
        (["1279786", "1279787", "1000000", "1279789"], "1279789", 4),
        (["1314455", "1314459", "1000001", "1314457"], "1314455", 1),
        (["1314455", "1314459", "1000001", "1314457"], "1314459", 2),
        (["1314455", "1314459", "1000001", "1314457"], "1314457", 4),
        (["1166233", "1166234", "1166235"], "1166233", 1),
        (["1166233", "1166234", "1166235"], "1166234", 2),
        (["1166233", "1166234", "1166235"], "1166235", 3),
        (["1153946", "1153947", "1153948", "1153949"], "1153946", 1),
        (["1153946", "1153947", "1153948", "1153949"], "1153947", 2),
        (["1153946", "1153947", "1153948", "1153949"], "1153948", 3),
        (["1153946", "1153947", "1153948", "1153949"], "1153949", 4),
        (["1171752", "1171753", "1171754", "1171755"], "1171754", 3),
    ],
)
def test_movie_resolves_fixture_scene_id_to_document_ordinal(scene_ids, scene_id, ordinal):
    movie, _session = make_movie(scene_ids)

    assert [scene.scene_id for scene in movie.scenes] == scene_ids
    assert movie.scene_ordinal_for_id(scene_id) == ordinal


def test_scene_model_keeps_existing_initialization_compatible():
    scene = Scene(performers=["Performer"])

    assert scene.scene_id is None


def test_downloader_keeps_existing_positional_arguments_compatible(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    downloader = Downloader("https://straight.aebn.com/straight/movies/123/fixture", None, 2, 7, no_part=True)

    assert downloader.scene_n == 2
    assert downloader.start_segment == 7
    assert downloader.scene_id is None


def test_movie_scrape_marks_malformed_scene_id_metadata():
    movie, _session = make_movie(["not-a-number"])

    assert movie.scenes[0].scene_id is None


def test_scene_without_performer_metadata_retains_ordinal():
    content = movie_html(["123", "456"]).replace(
        b'<section id="scene-123"><li class="dts-scene-strip-stars"></li></section>',
        b'<section id="scene-123"></section>',
    )
    movie = Movie("https://straight.aebn.com/straight/movies/123/fixture", FakeSession([FakeResponse(content)]))
    assert len(movie.scenes) == 2
    assert movie.scenes[0].performers == []
    assert movie.scene_ordinal_for_id("456") == 2


@pytest.mark.parametrize(
    ("scene_ids", "wanted_id", "message"),
    [
        (["123", "123"], "123", "(?i)duplicate"),
        (["123", "bad"], "123", "(?i)malformed"),
        ([None, "123"], "123", "(?i)missing"),
        (["123"], "999", "not found"),
    ],
)
def test_scene_id_resolution_rejects_invalid_or_ambiguous_metadata(scene_ids, wanted_id, message):
    movie, _session = make_movie([scene_id or "123" for scene_id in scene_ids])
    for scene, scene_id in zip(movie.scenes, scene_ids):
        scene.scene_id = scene_id

    with pytest.raises(ValueError, match=message):
        movie.scene_ordinal_for_id(wanted_id)


def test_movie_scrape_propagates_network_and_http_errors():
    with pytest.raises(OSError, match="network unavailable"):
        Movie(
            "https://straight.aebn.com/straight/movies/123/fixture",
            FakeSession([OSError("network unavailable")]),
        )

    with pytest.raises(RuntimeError, match="http error"):
        Movie(
            "https://straight.aebn.com/straight/movies/123/fixture",
            FakeSession([FakeResponse(b"", RuntimeError("http error"))]),
        )


def test_timeline_scene_count_must_match_movie_scene_count():
    movie, session = make_movie(["123", "456"])
    session.responses.append(FakeResponse(b'<div class="scroller" data-time-start="0" data-time-duration="10"></div>'))

    with pytest.raises(ValueError, match="scene count"):
        movie.calculate_scenes_boundaries(10)


def test_timeline_http_error_is_propagated():
    movie, session = make_movie(["123"])
    session.responses.append(FakeResponse(b"", RuntimeError("timeline http error")))

    with pytest.raises(RuntimeError, match="timeline http error"):
        movie.calculate_scenes_boundaries(10)


def test_downloader_reports_resolved_scene_id_and_ordinal(monkeypatch, capsys):
    movie, _session = make_movie(["900001", "900002", "1171754", "900004"])
    instance = Downloader(
        "https://straight.aebn.com/straight/movies/276944/natural-beauties-16#scene-1171754",
        scene_id="1171754",
        json_output=True,
        no_part=True,
    )
    monkeypatch.setattr(instance, "_initialize_download", lambda: None)
    monkeypatch.setattr(instance, "_scrape_movie_info", lambda: movie)
    monkeypatch.setattr(instance, "_find_existing_output", lambda _movie: "already-downloaded.mp4")

    instance.run()

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    selected = next(event for event in events if event["event"] == "scene_selected")
    assert selected["scene_id"] == "1171754"
    assert selected["scene_ordinal"] == 3


@pytest.mark.parametrize("flag", ["-I", "--scene-id"])
def test_scene_id_cli_flag_is_passed_to_downloader(monkeypatch, flag):
    captured = {}

    class FakeDownloader:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return None

    monkeypatch.setattr("aebn_dl.cli.Downloader", FakeDownloader)

    main(["https://straight.aebn.com/straight/movies/123/fixture", flag, "456"])

    assert captured["scene_id"] == "456"
    assert captured["scene_n"] is None


def test_legacy_scene_flag_remains_supported(monkeypatch):
    captured = {}

    class FakeDownloader:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return None

    monkeypatch.setattr("aebn_dl.cli.Downloader", FakeDownloader)

    main(["https://straight.aebn.com/straight/movies/123/fixture", "-s", "3"])

    assert captured["scene_n"] == 3
    assert captured["scene_id"] is None


def test_cli_rejects_simultaneous_scene_number_and_id():
    with pytest.raises(SystemExit) as error:
        main(["https://straight.aebn.com/straight/movies/123/fixture", "-s", "3", "-I", "456"])

    assert error.value.code == 2


def test_cli_returns_nonzero_when_scene_id_resolution_fails(monkeypatch):
    monkeypatch.setattr("aebn_dl.cli.download_movie", lambda _args: (_ for _ in ()).throw(ValueError("unknown scene ID")))

    assert main(["https://straight.aebn.com/straight/movies/123/fixture", "-I", "999"]) == 1


def test_module_cli_exits_nonzero_for_unresolved_scene():
    code = ("import runpy, sys; from importlib.machinery import PathFinder; "
            "sys.meta_path.remove(PathFinder); sys.meta_path.insert(1, PathFinder); "
            "from aebn_dl.downloader import Downloader; "
            "Downloader.run = lambda self: (_ for _ in ()).throw(ValueError('unknown scene ID')); "
            "sys.argv = ['aebn_dl.cli', 'https://straight.aebn.com/straight/movies/123/fixture', '-I', '999']; "
            "runpy.run_module('aebn_dl.cli', run_name='__main__')")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode != 0
    assert "unknown scene ID" in result.stderr
