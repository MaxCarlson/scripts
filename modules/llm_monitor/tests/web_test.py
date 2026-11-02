import pytest

from llm_monitor.web import validate_endpoint


def test_validate_endpoint_accepts_http_base_url_and_strips_trailing_slash():
    assert validate_endpoint("http://127.0.0.1:1234/") == "http://127.0.0.1:1234"
    assert validate_endpoint("https://localhost:1234/lmstudio/") == "https://localhost:1234/lmstudio"


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://127.0.0.1:1234",
        "http://user:secret@127.0.0.1:1234",
        "http://127.0.0.1:1234?token=secret",
        "http://127.0.0.1:1234#fragment",
        "not a url",
    ],
)
def test_validate_endpoint_rejects_unsupported_or_sensitive_url_parts(endpoint):
    with pytest.raises(ValueError, match=r"HTTP\(S\) URL"):
        validate_endpoint(endpoint)
