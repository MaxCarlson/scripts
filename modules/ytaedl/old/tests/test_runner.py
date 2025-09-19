"""
Tests for the runner.py module.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytaedl.models import (
    DownloaderConfig,
    DownloadItem,
    DownloadResult,
    DownloadStatus,
    FinishEvent,
    StartEvent,
)
from ytaedl.runner import DownloadRunner
from ytaedl.ui import UIBase


@pytest.fixture
def runner_config(tmp_path: Path) -> DownloaderConfig:
    """Provides a standard DownloaderConfig for tests."""
    return DownloaderConfig(
        work_dir=tmp_path / "work",
        archive_path=tmp_path / "archive.txt",
        parallel_jobs=2,
    )


@pytest.fixture
def mock_ui() -> MagicMock:
    """Provides a mock UI object."""
    return MagicMock(spec=UIBase)


@patch("ytaedl.runner.get_downloader")
def test_runner_skips_archived_urls(
    mock_get_downloader: MagicMock, runner_config: DownloaderConfig, mock_ui: MagicMock, tmp_path: Path
):
    """Verify that the runner skips URLs that are already in the archive."""
    runner_config.archive_path.write_text("http://example.com/archived\n")
    url_file = tmp_path / "urls.txt"
    url_file.write_text("http://example.com/archived\nhttp://example.com/new")

    def download_generator(item):
        yield StartEvent(item=item)
        yield FinishEvent(item=item, result=DownloadResult(item=item, status=DownloadStatus.COMPLETED))

    mock_downloader = MagicMock()
    mock_downloader.download.side_effect = download_generator
    mock_get_downloader.return_value = mock_downloader

    runner = DownloadRunner(runner_config, ui=mock_ui)
    runner.run_from_files([url_file], tmp_path)

    # The downloader should only be called for the non-archived URL
    mock_downloader.download.assert_called_once()
    assert mock_downloader.download.call_args[0][0].url == "http://example.com/new"

    # The UI should have received events only for the new URL
    assert mock_ui.handle_event.call_count == 2
    finish_event = next(c.args[0] for c in mock_ui.handle_event.call_args_list if isinstance(c.args[0], FinishEvent))
    assert finish_event.item.url == "http://example.com/new"


@patch("ytaedl.runner.get_downloader")
def test_runner_handles_duplicates_in_run(
    mock_get_downloader: MagicMock, runner_config: DownloaderConfig, mock_ui: MagicMock, tmp_path: Path
):
    """Verify the runner only downloads a given URL once, even if duplicated in the input."""
    url_file = tmp_path / "urls.txt"
    url_file.write_text("http://example.com/A\nhttp://example.com/A")

    def download_generator(item):
        yield StartEvent(item=item)
        yield FinishEvent(item=item, result=DownloadResult(item=item, status=DownloadStatus.COMPLETED))

    mock_downloader = MagicMock()
    mock_downloader.download.side_effect = download_generator
    mock_get_downloader.return_value = mock_downloader

    runner = DownloadRunner(runner_config, ui=mock_ui)
    runner.run_from_files([url_file], tmp_path)

    # The downloader should only be called once due to the archive lock
    mock_downloader.download.assert_called_once()