from aebn_dl.manifest_parser import Manifest


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, headers=None, data=None):
        self.posts.append({"url": url, "headers": headers or {}, "data": data})
        return _FakeResponse({"url": "https://media.example/full/manifest.mpd"})


def test_manifest_deliver_request_asks_for_full_movie_not_preview():
    session = _FakeSession()
    manifest = Manifest(
        "https://straight.aebn.com/straight/movies/296902/title",
        total_duration_seconds=3600,
        session=session,
    )

    url = manifest._get_new_manifest_url()

    assert url == "https://media.example/full/manifest.mpd"
    assert session.posts
    assert "isPreview=false" in session.posts[0]["data"]
    assert "isPreview=true" not in session.posts[0]["data"]
