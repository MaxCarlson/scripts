"""
Tests for the url_parser.py module.
"""
import pytest
from ytaedl.url_parser import is_aebn_url, get_url_slug, parse_aebn_scene_controls


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://www.aebn.com/movie/12345", True),
        ("https://straight.aebn.com/movie/67890", True),
        ("http://example.com", False),
        ("https://aebn.net", False),
        ("not a url", False),
    ],
)
def test_is_aebn_url(url, expected):
    assert is_aebn_url(url) == expected


@pytest.mark.parametrize(
    "url, expected_slug",
    [
        ("http://aebn.com/movie/the-movie-title", "the-movie-title"),
        ("http://aebn.com/movie/another-title#scene-5", "another-title-scene-5"),
        ("http://aebn.com/movie/foo?sceneId=12345", "foo-sceneId-12345"),
        ("http://aebn.com/movie/bar/scene/4", "bar-scene-4"),
        ("http://aebn.com/movie/baz?clip=abc&start=60", "baz-clip-abc-start-60"),
    ],
)
def test_get_url_slug(url, expected_slug):
    assert get_url_slug(url) == expected_slug


@pytest.mark.parametrize(
    "url, expected_index, expected_id",
    [
        # Valid index from fragment
        ("http://aebn.com/movie/123#scene-5", "5", "5"),
        # Index too large
        ("http://aebn.com/movie/123#scene-201", None, "201"),
        # Valid index from path
        ("http://aebn.com/movie/123/scene/10", "10", None),
        # Index too large in path
        ("http://aebn.com/movie/123/scenes/300", None, None),
        # ID from query param
        ("http://aebn.com/movie/123?sceneId=98765", None, "98765"),
        # No scene info
        ("http://aebn.com/movie/123", None, None),
        # Scene ID from fragment
        ("http://aebn.com/movie/123#scene-98765", None, "98765"),
    ],
)
def test_parse_aebn_scene_controls(url, expected_index, expected_id):
    controls = parse_aebn_scene_controls(url)
    assert controls.get("scene_index") == expected_index
    assert controls.get("scene_id") == expected_id


"""
Extra coverage for URL slug building edge cases.
"""
from ytaedl.url_parser import get_url_slug


def test_get_url_slug_trailing_slash_and_fragment():
    url = "http://aebn.com/movie/sample-title/scene/4#scene-4"
    # Fragment takes precedence but should still include base 'sample-title'
    assert get_url_slug(url) == "sample-title-scene-4"


def test_get_url_slug_query_order_preserved():
    url = "http://aebn.com/movie/foo?alpha=1&beta=2&gamma=3"
    assert get_url_slug(url) == "foo-alpha-1-beta-2-gamma-3"


def test_is_aebn_url_for_straight_movies():
    url = "https://straight.aebn.com/straight/movies/195412/luxure-the-education-of-my-wife#scene-919883"
    assert is_aebn_url(url) is True


def test_get_url_slug_trailing_slash_and_fragment():
    url = "http://aebn.com/movies/sample-title/scene/4#scene-4"
    # Fragment takes precedence but should still include base 'sample-title'
    assert get_url_slug(url) == "sample-title-scene-4"


def test_get_url_slug_query_order_preserved():
    url = "http://aebn.com/movies/foo?alpha=1&beta=2&gamma=3"
    assert get_url_slug(url) == "foo-alpha-1-beta-2-gamma-3"
