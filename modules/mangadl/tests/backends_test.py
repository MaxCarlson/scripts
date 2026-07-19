import pytest

from mangadl.backends import GalleryDlBackend, choose_backend


def test_gallery_dl_recognizes_nhentai() -> None:
    assert GalleryDlBackend().score("https://nhentai.net/g/123/") == 100
    assert choose_backend("https://nhentai.net/g/123/") == "gallery-dl"


def test_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        choose_backend("https://example.com", "missing")
