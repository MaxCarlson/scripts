import json

import pytest

from kavita.client import KavitaClient, KavitaConfig, KavitaError


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class _Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _Response(response)


def _client(opener):
    return KavitaClient(KavitaConfig("http://kavita:5000", "secret"), opener=opener)


def test_auth_key_header_and_series_pagination():
    opener = _Opener([[{"id": 1}], []])
    client = _client(opener)
    assert client.list_series(page_size=1) == [{"id": 1}]
    assert opener.requests[0][0].get_header("X-api-key") == "secret"
    assert opener.requests[0][0].full_url.endswith("/api/series/v2?pageNumber=1&pageSize=1")


def test_collection_add_defaults_to_preview_without_http_writes():
    opener = _Opener([])
    result = _client(opener).add_series_to_collection("Shelf", [4, 4])
    assert result == {"action": "add_to_collection", "collection": "Shelf", "series_ids": [4], "applied": False}
    assert opener.requests == []


def test_collection_add_creates_then_adds_series():
    opener = _Opener([[], None, [{"id": 9, "title": "Shelf"}], None])
    result = _client(opener).add_series_to_collection("Shelf", [4], apply=True)
    assert result["applied"] is True
    assert [request.get_method() for request, _ in opener.requests] == ["GET", "POST", "GET", "POST"]
    assert json.loads(opener.requests[1][0].data) == {
        "collectionTagId": 0,
        "collectionTagTitle": "Shelf",
        "seriesIds": [],
    }
    assert json.loads(opener.requests[3][0].data)["seriesIds"] == [4]


def test_create_reading_list_previews_and_applies_explicitly():
    preview_opener = _Opener([])
    assert _client(preview_opener).create_reading_list("Read next")["applied"] is False
    assert preview_opener.requests == []
    opener = _Opener([[], {"id": 5, "title": "Read next"}])
    result = _client(opener).create_reading_list("Read next", apply=True)
    assert result["id"] == 5
    assert [request.get_method() for request, _ in opener.requests] == ["POST", "POST"]
    assert opener.requests[0][0].full_url.endswith("/api/readinglist/lists?pageNumber=1&pageSize=500&includePromoted=false")
    assert json.loads(opener.requests[1][0].data) == {"title": "Read next"}


def test_add_series_to_existing_reading_list_uses_supported_endpoint():
    opener = _Opener([[{"id": 5, "title": "Read next"}], None])
    result = _client(opener).add_series_to_reading_list("Read next", [10], apply=True)
    assert result["applied"] is True
    assert opener.requests[1][0].full_url.endswith("/api/readinglist/update-by-multiple-series")
    assert json.loads(opener.requests[1][0].data) == {"readingListId": 5, "seriesIds": [10]}


def test_config_reads_named_environment_variable():
    assert KavitaConfig.from_env("http://kavita", api_key_env="MY_KEY", environ={"MY_KEY": "value"}).api_key == "value"
    with pytest.raises(ValueError, match="API key is empty"):
        KavitaConfig.from_env("http://kavita", environ={})


@pytest.mark.parametrize("url", ["kavita:5000", "ftp://kavita", "http://user:password@kavita", "http://kavita?key=secret"])
def test_config_rejects_invalid_or_secret_bearing_base_urls(url):
    with pytest.raises(ValueError, match="URL"):
        KavitaConfig(url, "secret")


def test_api_error_message_does_not_include_api_key():
    from urllib.error import HTTPError

    opener = _Opener([HTTPError("url", 403, "denied", {}, None)])
    with pytest.raises(KavitaError, match="HTTP 403") as error:
        _client(opener).list_collections()
    assert "secret" not in str(error.value)
