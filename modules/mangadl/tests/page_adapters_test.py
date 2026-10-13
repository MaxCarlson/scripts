from __future__ import annotations

from gallery_dl.extractor.message import Message

from mangadl.page_adapters import ExpectedPages, resolve_expected_pages


def test_gallery_dl_enumeration_uses_page_metadata_without_download_job() -> None:
    class Extractor:
        def __iter__(self):
            yield Message.Directory, "", {"count": 2}
            yield Message.Url, "https://img.example/1.jpg", {"num": 1}
            yield Message.Url, "https://img.example/2.jpg", {"num": 2}

    result = resolve_expected_pages(
        "https://nhentai.net/g/123/",
        extractor_finder=lambda _url: Extractor(),
    )

    assert result == ExpectedPages(2, (1, 2), "nhentai gallery metadata", True)


def test_gallery_dl_enumeration_rejects_non_contiguous_page_ids() -> None:
    class Extractor:
        def __iter__(self):
            yield Message.Url, "https://img.example/1.jpg", {"num": 1}
            yield Message.Url, "https://img.example/3.jpg", {"num": 3}

    result = resolve_expected_pages(
        "https://nhentai.net/g/123/",
        extractor_finder=lambda _url: Extractor(),
    )

    assert result is not None
    assert result.identities == (1, 3)
    assert result.complete_identity_set is False
