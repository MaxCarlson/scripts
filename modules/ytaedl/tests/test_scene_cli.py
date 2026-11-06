import json

from ytaedl import cli, scene_cli

URL = "https://straight.aebn.com/straight/movies/270491/example"


def test_batch_reuses_movie_and_resolves_ids():
    calls = []
    class Movie:
        title = "Example"
        scenes = [1, 2]
        def scene_ordinal_for_id(self, scene_id):
            return {"1153946": 1, "1153947": 2}[scene_id]
    def factory(url, session):
        calls.append(url)
        return Movie()
    results = scene_cli.inspect_urls([URL + "#scene-1153946", URL + "#scene-1153947", URL], factory, object())
    assert calls == [URL]
    assert [item["scene_ordinal"] for item in results] == [1, 2, None]
    assert results[2]["status"] == "no_scene_requested"
    assert results[0]["scene_count"] == 2


def test_errors_are_explicit_and_nonzero(monkeypatch, capsys):
    class Movie:
        title = "Example"
        scenes = [1]
        def scene_ordinal_for_id(self, scene_id):
            raise ValueError("scene ID not found")
    monkeypatch.setattr(scene_cli, "_session", lambda: object())
    import aebn_dl.movie_scraper
    monkeypatch.setattr(aebn_dl.movie_scraper, "Movie", lambda *_: Movie())
    assert cli.main(["scene", "-u", URL + "#scene-999", "-j"]) == 1
    assert "not found" in json.loads(capsys.readouterr().out)[0]["error"]
    results = scene_cli.inspect_urls(["not a URL", URL + "#scene-nope"], lambda *_: Movie(), object())
    assert all(item["status"] == "error" for item in results)


def test_metadata_failure_is_reported():
    def failed_request(*_args):
        raise OSError("metadata unavailable")
    result = scene_cli.inspect_urls([URL + "#scene-1153946"], failed_request, object())
    assert result[0]["status"] == "error"
    assert result[0]["error"] == "metadata unavailable"


def test_file_preserves_fragments_and_dispatches(monkeypatch, tmp_path, capsys):
    path = tmp_path / "urls.txt"
    path.write_text(URL + "#scene-1153946\n" + URL + "#scene-1153947\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(scene_cli, "inspect_urls", lambda urls: seen.extend(urls) or [{"status": "no_scene_requested", "title": "x", "scene_id": None, "url": urls[0]}])
    assert cli.main(["scene", "-f", str(path), "-j"]) == 0
    assert seen == [URL + "#scene-1153946", URL + "#scene-1153947"]
    assert json.loads(capsys.readouterr().out)[0]["status"] == "no_scene_requested"
