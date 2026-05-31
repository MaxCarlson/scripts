"""Tests for archive.py — is_zip and extract_image_from_zip."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from drive_manager.archive import IMAGE_EXTENSIONS, extract_image_from_zip, is_zip


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_zip(path: Path, members: dict[str, bytes]) -> Path:
    """Write a ZIP at *path* containing {filename: content} members."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


# ── is_zip ────────────────────────────────────────────────────────────────────

def test_is_zip_true(tmp_path):
    z = _make_zip(tmp_path / "a.zip", {"file.txt": b"hello"})
    assert is_zip(z) is True


def test_is_zip_false_for_raw_image(tmp_path):
    img = tmp_path / "boot.img"
    img.write_bytes(b"\xeb\x58\x90" + b"\x00" * 509)  # MBR-style header
    assert is_zip(img) is False


def test_is_zip_false_for_iso(tmp_path):
    iso = tmp_path / "boot.iso"
    iso.write_bytes(b"\x00" * 32768 + b"CD001")
    assert is_zip(iso) is False


def test_is_zip_missing_file(tmp_path):
    assert is_zip(tmp_path / "nonexistent.zip") is False


# ── extract_image_from_zip ────────────────────────────────────────────────────

def test_extract_single_img(tmp_path):
    content = b"\x00" * 1024
    z = _make_zip(tmp_path / "release.zip", {"memtest86-usb.img": content})
    result = extract_image_from_zip(z)
    assert result == tmp_path / "memtest86-usb.img"
    assert result.read_bytes() == content


def test_extract_single_iso(tmp_path):
    z = _make_zip(tmp_path / "ubuntu.zip", {"ubuntu-24.04.iso": b"ISO"})
    result = extract_image_from_zip(z)
    assert result.suffix == ".iso"
    assert result.read_bytes() == b"ISO"


def test_extract_to_explicit_dir(tmp_path):
    out_dir = tmp_path / "extracted"
    z = _make_zip(tmp_path / "boot.zip", {"boot.img": b"BOOT"})
    result = extract_image_from_zip(z, extract_dir=out_dir)
    assert result.parent == out_dir
    assert result.read_bytes() == b"BOOT"


def test_extract_creates_extract_dir(tmp_path):
    out_dir = tmp_path / "new" / "subdir"
    z = _make_zip(tmp_path / "x.zip", {"x.img": b"X"})
    result = extract_image_from_zip(z, extract_dir=out_dir)
    assert out_dir.is_dir()
    assert result.exists()


def test_extract_flat_ignores_zip_subdirs(tmp_path):
    """Image nested inside a zip subdirectory is extracted flat."""
    z = _make_zip(tmp_path / "pkg.zip", {"subdir/image.img": b"NESTED"})
    result = extract_image_from_zip(z)
    assert result.name == "image.img"
    assert result.read_bytes() == b"NESTED"


def test_extract_skips_non_image_files(tmp_path):
    """Non-image files in the archive do not confuse the extractor."""
    z = _make_zip(tmp_path / "pkg.zip", {
        "README.txt": b"read me",
        "CHANGELOG.md": b"changes",
        "memtest.img": b"IMGDATA",
    })
    result = extract_image_from_zip(z)
    assert result.name == "memtest.img"


def test_extract_no_image_raises(tmp_path):
    z = _make_zip(tmp_path / "docs.zip", {"README.txt": b"hello", "notes.md": b"world"})
    with pytest.raises(ValueError, match="No bootable image"):
        extract_image_from_zip(z)


def test_extract_no_image_error_lists_contents(tmp_path):
    z = _make_zip(tmp_path / "docs.zip", {"a.txt": b"", "b.pdf": b""})
    with pytest.raises(ValueError, match="a.txt"):
        extract_image_from_zip(z)


def test_extract_multiple_images_raises(tmp_path):
    z = _make_zip(tmp_path / "multi.zip", {"a.img": b"A", "b.img": b"B"})
    with pytest.raises(ValueError, match="Multiple image files"):
        extract_image_from_zip(z)


def test_extract_multiple_images_error_lists_names(tmp_path):
    z = _make_zip(tmp_path / "multi.zip", {"a.img": b"A", "b.iso": b"B"})
    with pytest.raises(ValueError, match="a.img"):
        extract_image_from_zip(z)


@pytest.mark.parametrize("ext", sorted(IMAGE_EXTENSIONS))
def test_all_recognised_extensions_extracted(tmp_path, ext):
    fname = f"boot{ext}"
    z = _make_zip(tmp_path / "test.zip", {fname: b"DATA"})
    result = extract_image_from_zip(z)
    assert result.suffix.lower() == ext
    assert result.read_bytes() == b"DATA"


def test_extract_corrupt_zip_raises_ioerror(tmp_path):
    """A valid-looking zip whose compressed data is truncated raises IOError."""
    z = _make_zip(tmp_path / "boot.zip", {"boot.img": b"\x00" * 4096})
    # Truncate the file to simulate an incomplete download.
    data = z.read_bytes()
    z.write_bytes(data[: len(data) // 2])
    with pytest.raises((IOError, zipfile.BadZipFile)):
        extract_image_from_zip(z)


def test_extract_bad_zip_file_raises_ioerror(tmp_path):
    """A file whose magic bytes say ZIP but whose body is garbage raises IOError."""
    z = tmp_path / "fake.zip"
    z.write_bytes(b"PK\x03\x04" + b"\xff" * 100)
    with pytest.raises((IOError, zipfile.BadZipFile)):
        extract_image_from_zip(z)


def test_extract_output_collision_disambiguated(tmp_path):
    """When the inner image name matches the zip filename, output is renamed.

    This is the real-world case where the user passes -i foo.img for a URL
    whose zip contains an entry also named foo.img — without disambiguation
    Python would try to open the same file for read (zip) and write (output)
    simultaneously, causing WinError 32 on Windows.
    """
    # Zip saved as foo.img; entry inside is also foo.img.
    zip_path = tmp_path / "foo.img"
    _make_zip(zip_path, {"foo.img": b"IMGDATA"})
    result = extract_image_from_zip(zip_path)
    assert result != zip_path
    assert result.name == "foo_extracted.img"
    assert result.read_bytes() == b"IMGDATA"
    # Original zip (the .img container) is still intact.
    assert zip_path.exists()
