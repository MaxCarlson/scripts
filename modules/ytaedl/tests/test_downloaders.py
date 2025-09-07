"""
Tests for the downloaders.py module.
"""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytaedl.downloaders import (
    AebnDownloader,
    DownloaderConfig,
    YtDlpDownloader,
    get_downloader,
)

from ytaedl.models import DownloaderConfig, DownloadItem, FinishEvent, DownloadStatus


@pytest.fixture
def config(tmp_path: Path) -> DownloaderConfig:
    return DownloaderConfig(
        work_dir=tmp_path / "work",
        archive_path=tmp_path / "archive.txt",
        timeout_seconds=10,
    )


def test_get_downloader_factory(config: DownloaderConfig):
    """Test that the factory returns the correct downloader instance."""
    aebn_downloader = get_downloader("http://aebn.com/movie/1", config)
    assert isinstance(aebn_downloader, AebnDownloader)

    yt_downloader = get_downloader("http://example.com/video/1", config)
    assert isinstance(yt_downloader, YtDlpDownloader)


@patch("ytaedl.downloaders.subprocess.Popen")
def test_ytdlp_downloader_success(
    mock_popen: MagicMock, config: DownloaderConfig, tmp_path: Path
):
    """Test the YtDlpDownloader for a successful download."""
    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = ["[download] Destination: video.mp4", ""]
    mock_proc.wait.return_value = 0  # Correctly mock the return value of wait()
    mock_popen.return_value = mock_proc

    item = DownloadItem(id=0, url="http://example.com/video/1", output_dir=tmp_path)
    downloader = YtDlpDownloader(config)
    events = list(downloader.download(item))
    finish_event = next(e for e in events if isinstance(e, FinishEvent))
    result = finish_event.result

    assert result.status == DownloadStatus.COMPLETED
    assert result.error_message is None
    mock_popen.assert_called_once()


@patch("ytaedl.downloaders.subprocess.Popen")
def test_aebn_downloader_with_scene(
    mock_popen: MagicMock, config: DownloaderConfig, tmp_path: Path
):
    """Test the AebnDownloader with a URL that has a scene index."""
    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = ["Success", ""]
    mock_proc.wait.return_value = 0
    mock_popen.return_value = mock_proc

    item = DownloadItem(
        id=0, url="http://aebn.com/movie/1#scene-7", output_dir=tmp_path
    )
    downloader = AebnDownloader(config)
    list(downloader.download(item))

    mock_popen.assert_called_once()
    cmd_args = mock_popen.call_args[0][0]
    assert "aebndl" in cmd_args
    assert "-s" in cmd_args
    assert "7" in cmd_args


@patch("ytaedl.downloaders.subprocess.Popen")
def test_downloader_already_exists(
    mock_popen: MagicMock, config: DownloaderConfig, tmp_path: Path
):
    """Test the case where the downloader reports the file already exists."""
    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = [
        "[download] video.mp4 has already been downloaded",
        "",
    ]
    mock_proc.wait.return_value = 0
    mock_popen.return_value = mock_proc

    item = DownloadItem(id=0, url="http://example.com/video/1", output_dir=tmp_path)
    downloader = YtDlpDownloader(config)
    events = list(downloader.download(item))
    finish_event = next(e for e in events if isinstance(e, FinishEvent))
    result = finish_event.result

    assert result.status == DownloadStatus.ALREADY_EXISTS


@patch("ytaedl.downloaders.subprocess.Popen")
def test_downloader_failure(
    mock_popen: MagicMock, config: DownloaderConfig, tmp_path: Path
):
    """Test a failed download due to a non-zero exit code."""
    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = ["ERROR: Video not found", ""]
    mock_proc.wait.return_value = 1  # Set the non-zero exit code
    mock_popen.return_value = mock_proc

    item = DownloadItem(id=0, url="http://example.com/video/1", output_dir=tmp_path)
    downloader = YtDlpDownloader(config)
    events = list(downloader.download(item))
    finish_event = next(e for e in events if isinstance(e, FinishEvent))
    result = finish_event.result

    assert result.status == DownloadStatus.FAILED
    assert "non-zero exit code: 1" in result.error_message


@patch("ytaedl.downloaders.subprocess.Popen")
def test_aebn_downloader_failure_error_string(mock_popen: MagicMock, tmp_path: Path):
    """
    Ensure AebnDownloader reports the exact error string expected:
    'non-zero exit code: <rc>'.
    """
    cfg = DownloaderConfig(
        work_dir=tmp_path / "work",
        archive_path=tmp_path / "archive.txt",
        timeout_seconds=10,
    )

    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = ["Some error", ""]
    mock_proc.wait.return_value = 2  # non-zero
    mock_popen.return_value = mock_proc

    item = DownloadItem(
        id=1, url="http://aebn.com/movie/1#scene-7", output_dir=tmp_path
    )

    events = list(AebnDownloader(cfg).download(item))
    finish = next(e for e in events if isinstance(e, FinishEvent))
    assert finish.result.status == DownloadStatus.FAILED
    assert finish.result.error_message == "non-zero exit code: 2"
