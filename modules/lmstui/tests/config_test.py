import pytest

from lmstui.config import normalize_root_base_url


def test_normalize_root_base_url_root_ok():
    assert normalize_root_base_url("http://example.com:1234") == "http://example.com:1234"


def test_normalize_root_base_url_v1_strips():
    assert normalize_root_base_url("http://example.com:1234/v1") == "http://example.com:1234"


def test_normalize_root_base_url_api_v0_strips():
    assert normalize_root_base_url("http://example.com:1234/api/v0") == "http://example.com:1234"


def test_normalize_root_base_url_invalid():
    with pytest.raises(ValueError):
        normalize_root_base_url("example.com:1234")
