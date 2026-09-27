"""Run gallery-dl in scratch while honoring files already in the library.

This adapter exists only in a MangaDL worker subprocess. It does not change
the installed gallery-dl executable or any ordinary gallery-dl invocation.
"""

from __future__ import annotations

import sys
from pathlib import Path


def library_path_for(
    realpath: str, partial: Path, library: Path, category: str
) -> Path | None:
    """Translate a gallery-dl scratch filename to its eventual library path."""
    try:
        relative = Path(realpath).resolve().relative_to(partial.resolve())
    except (OSError, ValueError):
        return None
    parts = relative.parts
    if category and len(parts) >= 3 and parts[0] == category:
        return library.joinpath(*parts[1:])
    return library / relative


def install_library_existence_check(
    partial: Path, library: Path, category: str
) -> None:
    """Keep gallery-dl's scratch checks and add the corresponding library check."""
    from gallery_dl.path import PathFormat
    from gallery_dl.job import DownloadJob

    original_exists = PathFormat.exists

    def exists(pathfmt: PathFormat) -> bool:
        if original_exists(pathfmt):
            return True
        target = library_path_for(pathfmt.realpath, partial, library, category)
        if target is None:
            return False
        try:
            return target.is_file() and target.stat().st_size > 0
        except OSError:
            return False

    PathFormat.exists = exists
    original_initialize = DownloadJob.initialize

    def initialize(job: DownloadJob, kwdict=None) -> None:
        original_initialize(job, kwdict)
        if job.archive is not None:
            # An already-present library file is a successful skip. Persist
            # its key so a later non-scratch run does not download it again.
            job._archive_write_skip = True

    DownloadJob.initialize = initialize


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) < 4 or values[3] != "--":
        raise SystemExit(
            "gallery scratch adapter requires PARTIAL LIBRARY CATEGORY -- gallery-dl arguments"
        )
    partial = Path(values[0]).expanduser().resolve()
    library = Path(values[1]).expanduser().resolve()
    category = values[2]
    install_library_existence_check(partial, library, category)
    import gallery_dl

    sys.argv = [sys.argv[0], *values[4:]]
    return gallery_dl.main()


if __name__ == "__main__":
    raise SystemExit(main())
