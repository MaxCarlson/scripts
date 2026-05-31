"""ZIP archive helpers — detect and extract bootable image files."""
from __future__ import annotations

import zipfile
from pathlib import Path

# Recognised raw/bootable image extensions.
IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".img", ".iso", ".bin", ".raw", ".vhd", ".vhdx", ".vmdk", ".qcow2",
})


def is_zip(path: Path) -> bool:
    """Return True when *path* is a ZIP archive (checked via magic bytes)."""
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"PK\x03\x04"
    except OSError:
        return False


def extract_image_from_zip(zip_path: Path, extract_dir: Path | None = None) -> Path:
    """Extract the single bootable image from *zip_path*.

    *extract_dir* defaults to the directory that contains the ZIP.
    The extracted file is written flat (no subdirectory nesting) into *extract_dir*.

    Raises
    ------
    ValueError
        If the archive contains zero or more than one recognised image file.
    """
    target_dir = extract_dir if extract_dir is not None else zip_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        zf_handle = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile:
        raise IOError(
            f"{zip_path.name} is not a valid ZIP file (magic bytes check passed but "
            "the central directory is missing or corrupt). "
            "The download may be incomplete — delete the file and retry."
        )
    with zf_handle as zf:
        image_entries = [
            e for e in zf.infolist()
            if not e.is_dir() and Path(e.filename).suffix.lower() in IMAGE_EXTENSIONS
        ]

        if not image_entries:
            all_names = [e.filename for e in zf.infolist() if not e.is_dir()]
            raise ValueError(
                f"No bootable image file found inside {zip_path.name}. "
                f"Archive contents: {', '.join(all_names) or '(empty)'}. "
                f"Recognised extensions: {', '.join(sorted(IMAGE_EXTENSIONS))}."
            )

        if len(image_entries) > 1:
            found = ", ".join(e.filename for e in image_entries)
            raise ValueError(
                f"Multiple image files found in {zip_path.name}: {found}. "
                "Extract manually and supply the path with -i / --image-path."
            )

        entry = image_entries[0]
        out_path = target_dir / Path(entry.filename).name
        # The zip may have been downloaded with the same name as the image inside it
        # (e.g. -i foo.img for a zip whose inner entry is also foo.img).  Opening
        # the same file for write while the zip is still open for read causes
        # WinError 32 on Windows.  Disambiguate the output name in that case.
        if out_path.resolve() == zip_path.resolve():
            out_path = target_dir / f"{out_path.stem}_extracted{out_path.suffix}"
        chunk = 4 * 1024 * 1024
        with zf.open(entry) as src, out_path.open("wb") as dst:
            try:
                while True:
                    data = src.read(chunk)
                    if not data:
                        break
                    dst.write(data)
            except EOFError:
                out_path.unlink(missing_ok=True)
                raise IOError(
                    f"ZIP archive {zip_path.name} is truncated or corrupt "
                    "(the download may be incomplete). Delete the file and retry."
                )

    return out_path
