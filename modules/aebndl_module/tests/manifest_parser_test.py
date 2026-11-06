from aebn_dl.manifest_parser import Manifest
import pytest


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.text = ""

    def json(self):
        return self._payload


class _NonJsonResponse:
    status_code = 403
    headers = {"content-type": "text/html"}
    text = "<html>blocked</html>"

    def json(self):
        import json
        raise json.JSONDecodeError("Expecting value", self.text, 0)


class _FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, headers=None, data=None):
        self.posts.append({"url": url, "headers": headers or {}, "data": data})
        return _FakeResponse({"url": "https://media.example/full/manifest.mpd"})


def test_manifest_deliver_sends_is_preview_true():
    """The deliver request must always use isPreview=true to bypass auth."""
    session = _FakeSession()
    manifest = Manifest(
        "https://straight.aebn.com/straight/movies/296902/title",
        total_duration_seconds=3600,
        session=session,
    )

    url = manifest._get_new_manifest_url()

    assert url == "https://media.example/full/manifest.mpd"
    assert len(session.posts) == 1
    post = session.posts[0]
    assert "deliver" in post["url"]
    assert "isPreview=true" in post["data"]
    # No play-check call should be made
    assert all("play-check" not in p["url"] for p in session.posts)


def test_manifest_deliver_does_not_pass_scene_id():
    """The deliver request should not pass sceneId — full manifest, scene filtering done client-side."""
    session = _FakeSession()
    manifest = Manifest(
        "https://straight.aebn.com/straight/movies/296902/title#scene-123456",
        total_duration_seconds=3600,
        session=session,
    )

    manifest._get_new_manifest_url()

    assert "sceneId" not in session.posts[0]["data"]


def test_manifest_deliver_non_json_response_has_useful_error():
    class Session:
        def post(self, url, headers=None, data=None):
            return _NonJsonResponse()

    manifest = Manifest(
        "https://straight.aebn.com/straight/movies/296902/title",
        total_duration_seconds=3600,
        session=Session(),
    )

    import pytest

    with pytest.raises(RuntimeError) as excinfo:
        manifest._get_new_manifest_url()

    message = str(excinfo.value)
    assert "non-JSON response" in message
    assert "status=403" in message
    assert "blocked" in message


@pytest.mark.parametrize("payload,interval,allowed", [
    ({"startSeconds": 5, "endSeconds": 35, "hasMember": False}, (0, 453), False),
    ({"startSeconds": "0", "endSeconds": "453", "hasMember": True}, (0, 453), True),
    ({"startSeconds": 5, "endSeconds": 35, "hasMember": False}, (10, 30), True),
    ({"startSeconds": None, "endSeconds": 453}, (0, 453), False),
    ({"startSeconds": 0, "endSeconds": "nan"}, (0, 453), False),
    ({"startSeconds": 35, "endSeconds": 5}, (0, 453), False),
])
def test_delivery_window_must_cover_requested_interval(payload, interval, allowed):
    manifest = Manifest("https://straight.aebn.com/straight/movies/123/title", 453, _FakeSession())
    if allowed:
        manifest.validate_delivery_window(payload, *interval)
    else:
        with pytest.raises(ValueError, match="(?i)(preview|access|delivery)"):
            manifest.validate_delivery_window(payload, *interval)


def test_preview_fails_before_manifest_or_segment_fetch():
    class Session(_FakeSession):
        def post(self, *args, **kwargs):
            return _FakeResponse({"url": "https://fixture.invalid/manifest.mpd",
                                  "startSeconds": 5, "endSeconds": 35, "hasMember": False})

        def get(self, *args, **kwargs):
            raise AssertionError("preview-limited delivery must not fetch manifest or segments")

    manifest = Manifest("https://straight.aebn.com/straight/movies/123/title", 453, Session())
    with pytest.raises(ValueError, match="Preview/access limitation"):
        manifest.process_manifest()


def test_full_delivery_window_allows_manifest_processing(monkeypatch):
    class Session(_FakeSession):
        def post(self, *args, **kwargs):
            return _FakeResponse({"url": "https://fixture.invalid/manifest.mpd",
                                  "startSeconds": 0, "endSeconds": 453, "hasMember": True})
        def get(self, url):
            assert url == "https://fixture.invalid/manifest.mpd"
            return type("Response", (), {"content": b"<MPD/>"})()
    manifest = Manifest("https://straight.aebn.com/straight/movies/123/title", 453, Session())
    parsed = []
    monkeypatch.setattr(manifest, "parse_content", parsed.append)
    manifest.process_manifest()
    assert parsed == [b"<MPD/>"]


def test_cli_access_limitation_returns_nonretryable_status(monkeypatch):
    from aebn_dl import cli
    from aebn_dl.manifest_parser import PreviewAccessError
    def fail(args):
        raise PreviewAccessError("preview only")
    monkeypatch.setattr(cli, "download_movie", fail)
    assert cli.main(["https://straight.aebn.com/straight/movies/123/title"]) == 77


def test_cli_fragment_integrity_returns_nonretryable_status(monkeypatch):
    from aebn_dl import cli
    from aebn_dl.downloader import FragmentIntegrityError
    def fail(args):
        raise FragmentIntegrityError("invalid fragment")
    monkeypatch.setattr(cli, "download_movie", fail)
    assert cli.main(["https://straight.aebn.com/straight/movies/123/title"]) == 78


def test_scene_preview_rejected_before_media_and_emits_access_event(capsys):
    import json
    from types import SimpleNamespace
    from aebn_dl.downloader import Downloader
    class Session(_FakeSession):
        def post(self, *args, **kwargs):
            return _FakeResponse({"url": "https://fixture.invalid/manifest.mpd",
                                  "startSeconds": 5, "endSeconds": 35, "hasMember": False})
        def get(self, *args, **kwargs):
            raise AssertionError("media must not be requested")
    dl = Downloader("https://straight.aebn.com/straight/movies/123/title", scene_n=1,
                    json_output=True, no_part=True)
    dl.session = Session()
    scene = SimpleNamespace(start_timing=0, end_timing=453)
    movie = SimpleNamespace(total_duration_seconds=453, scenes=[scene],
                            calculate_scenes_boundaries=lambda duration: None)
    with pytest.raises(ValueError, match="Preview/access limitation"):
        dl._process_manifest(movie)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any(event["event"] == "preview_fallback" for event in events)
    assert not any(event["event"] in {"complete", "already", "segments_complete"} for event in events)


def test_scene_manifest_uses_one_consistent_timeline(monkeypatch):
    from types import SimpleNamespace
    from aebn_dl.downloader import Downloader
    from aebn_dl import downloader as module
    calls = []
    scene = SimpleNamespace(start_timing=10, end_timing=30)
    movie = SimpleNamespace(total_duration_seconds=90, scenes=[scene],
                            calculate_scenes_boundaries=lambda duration: calls.append(duration))
    class FakeManifest:
        def __init__(self, *args, **kwargs):
            self.segment_duration = 2.0
        def process_manifest(self):
            assert self.requested_interval == (10, 30)
    monkeypatch.setattr(module, "Manifest", FakeManifest)
    dl = Downloader("https://straight.aebn.com/straight/movies/123/title", scene_n=1, no_part=True)
    dl._process_manifest(movie)
    assert calls == [1.0]
    assert (scene.start_segment, scene.end_segment) == (5, 15)


def test_manifest_retains_dash_template_offsets_for_fragment_validation(monkeypatch):
    manifest = Manifest("https://straight.aebn.com/straight/movies/123/title", 453, _FakeSession(), 480)
    monkeypatch.setattr(manifest, "_find_best_good_audio_stream", lambda streams: "audio")
    xml = b'''<MPD><Period>
      <AdaptationSet mimeType="video/mp4"><SegmentTemplate timescale="1000000" duration="2000000.0"
        presentationTimeOffset="4000000" startNumber="2"/><Representation id="v" height="480"/></AdaptationSet>
      <AdaptationSet mimeType="audio/mp4"><SegmentTemplate timescale="1000000" duration="2000000.0"
        presentationTimeOffset="4000000" startNumber="2"/></AdaptationSet>
      </Period></MPD>'''
    manifest.parse_content(xml)
    assert manifest.segment_templates["v"] == {"timescale": "1000000", "duration": "2000000.0",
                                                "presentation_time_offset": "4000000", "start_number": "2"}
    assert manifest.segment_templates["a"] == manifest.segment_templates["v"]


@pytest.mark.parametrize("audio_template", [
    '<SegmentTemplate timescale="1" duration="2"><SegmentTimeline><S t="0" d="2"/></SegmentTimeline></SegmentTemplate>',
    '',
])
def test_unsupported_templates_fail_before_audio_probe(monkeypatch, audio_template):
    from aebn_dl.manifest_parser import UnsupportedManifestError
    manifest = Manifest("https://straight.aebn.com/straight/movies/123/title", 453, _FakeSession(), 480)
    monkeypatch.setattr(manifest, "_find_best_good_audio_stream", lambda streams: pytest.fail("must not fetch audio"))
    xml = f'''<MPD><Period>
      <AdaptationSet mimeType="video/mp4"><SegmentTemplate timescale="1" duration="2"/>
        <Representation id="v" height="480"/></AdaptationSet>
      <AdaptationSet mimeType="audio/mp4">{audio_template}</AdaptationSet>
      </Period></MPD>'''
    with pytest.raises(UnsupportedManifestError):
        manifest.parse_content(xml)


def test_audio_probe_stays_within_requested_scene(monkeypatch):
    from aebn_dl import manifest_parser
    requested = []
    class Session:
        def get(self, url):
            requested.append(url)
            return type("Response", (), {"content": b"fixture"})()
    manifest = Manifest("https://straight.aebn.com/straight/movies/123/title", 453, Session())
    manifest.base_stream_url = "https://fixture.invalid"
    manifest.segment_duration = 2
    manifest.total_number_of_data_segments = 227
    manifest.requested_interval = (10, 30)
    monkeypatch.setattr(manifest_parser.utils, "is_valid_media", lambda content: True)
    assert manifest._find_best_good_audio_stream([("rep", 480)]) == "rep"
    assert requested[-1].endswith("/a_rep_10.mp4d")


def test_scene_with_boundary_segments_outside_window_fails_before_audio_probe(monkeypatch):
    manifest = Manifest("https://straight.aebn.com/straight/movies/123/title", 453, _FakeSession(), 480)
    manifest.delivery_metadata = {"startSeconds": 5, "endSeconds": 35}
    manifest.requested_interval = (5, 35)
    monkeypatch.setattr(manifest, "_find_best_good_audio_stream", lambda streams: pytest.fail("must not fetch audio"))
    xml = b'''<MPD><Period><AdaptationSet mimeType="video/mp4">
      <SegmentTemplate timescale="1" duration="2"/><Representation id="v" height="480"/>
      </AdaptationSet></Period></MPD>'''
    with pytest.raises(ValueError, match="(?i)(preview|access|delivery)"):
        manifest.parse_content(xml)
