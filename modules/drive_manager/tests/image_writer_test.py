"""Tests for image_writer.resolve_image_path and downloads.download_to_cache."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from drive_manager.downloads import download_to_cache
from drive_manager.image_writer import resolve_image_path


# ── download_to_cache ──────────────────────────────────────────────────────────

def _fake_urlopen(data: bytes = b"IMG"):
    """Return a context-manager mock that yields chunks of `data` via read()."""
    mock_response = MagicMock()
    # shutil.copyfileobj calls read(length) until empty bytes
    mock_response.read.side_effect = [data, b""]
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    # headers.get("Content-Length") must return None so size check is skipped
    mock_response.headers.get.return_value = None
    return mock_response


def test_download_to_cache_default_location(tmp_path):
    """Without target_path, file lands in the default cache dir."""
    with patch("drive_manager.downloads.urllib.request.urlopen", return_value=_fake_urlopen(b"DATA")) as mock_open:
        result = download_to_cache("https://example.com/ubuntu.iso", cache_dir=tmp_path)
    assert result == tmp_path / "ubuntu.iso"
    assert result.read_bytes() == b"DATA"
    req = mock_open.call_args[0][0]
    assert req.full_url == "https://example.com/ubuntu.iso"
    assert "Mozilla" in req.get_header("User-agent")
    assert req.get_header("Accept-encoding") == "identity"
    assert "Chrome" in req.get_header("User-agent")


def test_download_to_cache_explicit_target_path(tmp_path):
    """target_path overrides cache dir and filename."""
    target = tmp_path / "subdir" / "custom.img"
    with patch("drive_manager.downloads.urllib.request.urlopen", return_value=_fake_urlopen(b"IMGDATA")):
        result = download_to_cache("https://example.com/memtest86.zip", target_path=target)
    assert result == target
    assert result.read_bytes() == b"IMGDATA"
    assert target.parent.is_dir()


def test_download_to_cache_creates_parent_dirs(tmp_path):
    """Parent directories of target_path are created if they don't exist."""
    target = tmp_path / "a" / "b" / "c" / "image.img"
    with patch("drive_manager.downloads.urllib.request.urlopen", return_value=_fake_urlopen(b"X")):
        download_to_cache("https://example.com/x.img", target_path=target)
    assert target.exists()


# ── resolve_image_path ─────────────────────────────────────────────────────────

def test_resolve_image_path_local_only(tmp_path):
    """Only image_path given → returns it (must exist)."""
    img = tmp_path / "local.img"
    img.write_bytes(b"\x00" * 512)
    result = resolve_image_path(img, None)
    assert result == img.resolve()


def test_resolve_image_path_local_missing_raises(tmp_path):
    """Only image_path given but missing → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        resolve_image_path(tmp_path / "missing.img", None)


def test_resolve_image_path_url_only_downloads_to_cache(tmp_path):
    """Only URL given → downloads to default cache, returns downloaded path."""
    with patch("drive_manager.image_writer.download_to_cache") as mock_dl:
        downloaded = tmp_path / "ubuntu.iso"
        downloaded.write_bytes(b"ISO")
        mock_dl.return_value = downloaded
        result = resolve_image_path(None, "https://example.com/ubuntu.iso")
    mock_dl.assert_called_once_with("https://example.com/ubuntu.iso", target_path=None)
    assert result == downloaded.resolve()


def test_resolve_image_path_url_with_image_path_downloads_to_target(tmp_path):
    """Both URL and image_path given → URL is downloaded to image_path location."""
    target = tmp_path / "custom.img"
    with patch("drive_manager.image_writer.download_to_cache") as mock_dl:
        mock_dl.return_value = target
        target.write_bytes(b"IMG")  # simulate download completing
        result = resolve_image_path(target, "https://example.com/memtest86.zip")
    mock_dl.assert_called_once_with("https://example.com/memtest86.zip", target_path=target)
    assert result == target.resolve()


def test_resolve_image_path_url_only_image_path_ignored_when_missing(tmp_path):
    """URL+nonexistent image_path: URL is downloaded (path does not need to pre-exist)."""
    target = tmp_path / "does_not_exist_yet.img"
    with patch("drive_manager.image_writer.download_to_cache") as mock_dl:
        mock_dl.return_value = target
        target.write_bytes(b"DOWNLOADED")  # simulate download
        result = resolve_image_path(target, "https://example.com/boot.iso")
    assert result == target.resolve()
    mock_dl.assert_called_once()


def test_resolve_image_path_neither_raises():
    with pytest.raises(ValueError, match="Either image_path or image_url"):
        resolve_image_path(None, None)


def test_resolve_image_path_checksum_pass(tmp_path):
    import hashlib
    data = b"image data"
    img = tmp_path / "boot.img"
    img.write_bytes(data)
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    result = resolve_image_path(img, None, checksum=digest)
    assert result == img.resolve()


def test_resolve_image_path_checksum_fail(tmp_path):
    img = tmp_path / "boot.img"
    img.write_bytes(b"wrong data")
    with pytest.raises(ValueError, match="Checksum verification failed"):
        resolve_image_path(img, None, checksum="sha256:0000deadbeef")


# ── zip auto-extraction ───────────────────────────────────────────────────────

def _make_zip_with_img(zip_path: Path, img_name: str, img_data: bytes) -> Path:
    import zipfile
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(img_name, img_data)
    return zip_path


def test_resolve_image_path_auto_extracts_zip(tmp_path):
    """A local .zip containing a single image is transparently extracted."""
    img_data = b"\x00" * 512
    z = _make_zip_with_img(tmp_path / "memtest86-usb.zip", "memtest86-usb.img", img_data)
    result = resolve_image_path(z, None)
    assert result.suffix == ".img"
    assert result.read_bytes() == img_data


def test_resolve_image_path_url_zip_extracted(tmp_path):
    """Downloaded zip (via URL) is auto-extracted before being returned."""
    img_data = b"\xAB" * 256
    z = _make_zip_with_img(tmp_path / "memtest86-usb.zip", "memtest86-usb.img", img_data)
    with patch("drive_manager.image_writer.download_to_cache") as mock_dl:
        mock_dl.return_value = z
        result = resolve_image_path(None, "https://www.memtest86.com/downloads/memtest86-usb.zip")
    assert result.suffix == ".img"
    assert result.read_bytes() == img_data


def test_resolve_image_path_zip_with_url_and_explicit_path(tmp_path):
    """URL + -i path: zip downloaded to the given path, then extracted."""
    img_data = b"\xCD" * 128
    zip_target = tmp_path / "download.zip"
    _make_zip_with_img(zip_target, "boot.img", img_data)
    with patch("drive_manager.image_writer.download_to_cache") as mock_dl:
        mock_dl.return_value = zip_target
        result = resolve_image_path(zip_target, "https://example.com/boot.zip")
    assert result.name == "boot.img"
    assert result.read_bytes() == img_data


def test_resolve_image_path_zip_no_image_raises(tmp_path):
    import zipfile
    z = tmp_path / "docs.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("README.txt", "nothing here")
    with pytest.raises(ValueError, match="No bootable image"):
        resolve_image_path(z, None)
