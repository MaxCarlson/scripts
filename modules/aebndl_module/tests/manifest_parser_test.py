from aebn_dl.manifest_parser import Manifest


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
