from pathlib import Path

from mangadl.covers import service
from mangadl.covers.models import SeriesPageMetadata


def test_post_download_cover_does_not_claim_an_unrelated_changed_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "library"
    unrelated = destination / "Completely Different Series"
    unrelated.mkdir(parents=True)
    metadata = SeriesPageMetadata(
        source_url="https://manga18fx.com/manga/example/",
        canonical_url="https://manga18fx.com/manga/example/",
        source_host="manga18fx.com",
        title="Example Series",
        alternate_titles=(),
        cover_url="https://manga18fx.com/cover.jpg",
    )
    monkeypatch.setattr(service, "snapshot_top_level", lambda _: {unrelated: (1, 1)})
    monkeypatch.setattr(service, "fetch_series_metadata", lambda *args, **kwargs: metadata)

    result = service.install_download_cover(
        metadata.canonical_url,
        destination,
        before={},
        cookies=None,
    )

    assert result.status == "folder_not_found"
    assert result.folder is None
