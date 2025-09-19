"""
Verify get_downloader routes straight.aebn.com/movies/... to AebnDownloader.
"""
from ytaedl.downloaders import get_downloader, AebnDownloader, DownloaderConfig
from pathlib import Path


def test_router_to_aebn_downloader_for_straight_movies(tmp_path: Path):
    cfg = DownloaderConfig(work_dir=tmp_path / "w", archive_path=tmp_path / "a.txt")
    url = "https://straight.aebn.com/straight/movies/195412/foo#scene-919883"
    dl = get_downloader(url, cfg)
    assert isinstance(dl, AebnDownloader)
