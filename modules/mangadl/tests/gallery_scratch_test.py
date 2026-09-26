from __future__ import annotations

from pathlib import Path

from gallery_dl.path import PathFormat
from gallery_dl.job import DownloadJob

from mangadl.gallery_scratch import install_library_existence_check, library_path_for
from mangadl.scratch import promote_gallery_partial


def test_library_mapping_matches_gallery_promotion_layout(tmp_path: Path) -> None:
    partial = tmp_path / "ssd" / "partial"
    library = tmp_path / "library"
    assert library_path_for(
        str(partial / "site" / "Series" / "001.jpg"), partial, library, "site"
    ) == (library / "Series" / "001.jpg")
    assert library_path_for(
        str(partial / "site" / "cover.jpg"), partial, library, "site"
    ) == (library / "site" / "cover.jpg")
    assert library_path_for(
        str(partial / "other" / "Series" / "001.jpg"), partial, library, "site"
    ) == (library / "other" / "Series" / "001.jpg")
    assert (
        library_path_for(str(tmp_path / "outside.jpg"), partial, library, "site")
        is None
    )


def test_gallery_existence_check_uses_library_before_download(
    tmp_path: Path, monkeypatch
) -> None:
    partial = tmp_path / "ssd" / "partial"
    library = tmp_path / "library"
    existing = library / "Series" / "001.jpg"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"already downloaded")
    monkeypatch.setattr(PathFormat, "exists", lambda _self: False)
    monkeypatch.setattr(DownloadJob, "initialize", DownloadJob.initialize)
    install_library_existence_check(partial, library, "site")
    pathfmt = object.__new__(PathFormat)
    pathfmt.realpath = str(partial / "site" / "Series" / "001.jpg")
    assert pathfmt.exists()
    pathfmt.realpath = str(partial / "site" / "Series" / "002.jpg")
    assert not pathfmt.exists()
    existing.write_bytes(b"")
    pathfmt.realpath = str(partial / "site" / "Series" / "001.jpg")
    assert not pathfmt.exists()


def test_gallery_existing_file_skip_is_archived_for_non_scratch_resume(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(PathFormat, "exists", PathFormat.exists)

    def fake_initialize(job, _kwdict=None):
        job.archive = object()
        job._archive_write_skip = False

    monkeypatch.setattr(DownloadJob, "initialize", fake_initialize)
    install_library_existence_check(tmp_path / "partial", tmp_path / "library", "site")
    job = object.__new__(DownloadJob)
    job.initialize()
    assert job._archive_write_skip


def test_gallery_promotion_uses_same_mapping(tmp_path: Path) -> None:
    root = tmp_path / "ssd" / "_partial"
    partial = root / "owner"
    nested = partial / "site" / "Series" / "001.jpg"
    direct = partial / "site" / "cover.jpg"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"image")
    direct.write_bytes(b"cover")
    library = tmp_path / "library"

    promote_gallery_partial(partial, library, root, "site")

    assert (library / "Series" / "001.jpg").read_bytes() == b"image"
    assert (library / "site" / "cover.jpg").read_bytes() == b"cover"
    assert not partial.exists()
