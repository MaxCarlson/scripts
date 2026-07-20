import pytest

from mangadl.backends import HDPornComicsBackend, GalleryDlBackend, backend_classification, choose_backend


def test_gallery_dl_recognizes_nhentai() -> None:
    assert GalleryDlBackend().score("https://nhentai.net/g/123/") == 100
    assert choose_backend("https://nhentai.net/g/123/") == "gallery-dl"


def test_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        choose_backend("https://example.com", "missing")


def test_hdporncomics_manhwa_routes_without_executable() -> None:
    url = "https://www.hdporncomics.com/manhwa/a-title/"
    assert HDPornComicsBackend().score(url) == 200
    assert choose_backend(url) == "hdporncomics"
    assert backend_classification(url, "hdporncomics") == "manhwa"


@pytest.mark.parametrize(
    "url",
    [
        "https://hdporncomics.com.example/manhwa/title/",
        "https://not-hdporncomics.com/manhwa/title/",
        "https://hdporncomics.com/comic/title/",
    ],
)
def test_hdporncomics_rejects_deceptive_or_non_manhwa_urls(url: str) -> None:
    assert HDPornComicsBackend().score(url) == 0
