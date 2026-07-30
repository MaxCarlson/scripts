from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError

from .files import changed_folders, snapshot_top_level
from .kavita import KavitaClient, apply_kavita_cover
from .matching import build_folder_url_index, collect_url_folder, match_folder, series_folders
from .models import CoverResult, SeriesPageMetadata
from .scraping import fetch_series_metadata, supports_cover_url
from .storage import with_match, write_cover_for_folder


def install_download_cover(
    url: str,
    destination: Path,
    before: Mapping[Path, tuple[int, int]],
    *,
    cookies: Path | None,
    timeout: float = 45.0,
) -> CoverResult:
    after = snapshot_top_level(destination)
    changed = changed_folders(before, after)
    metadata = fetch_series_metadata(url, cookies=cookies, timeout=timeout)
    candidate, ambiguous = match_folder(url, changed, metadata=metadata)
    if candidate is None:
        candidate, ambiguous = match_folder(url, list(after), metadata=metadata)
    if candidate is None:
        detail = ", ".join(str(item.folder) for item in ambiguous[:5])
        return CoverResult(
            url=metadata.canonical_url,
            status="ambiguous" if ambiguous else "folder_not_found",
            title=metadata.title,
            cover_url=metadata.cover_url,
            message=detail or "download completed but no matching series folder was found",
        )
    result = write_cover_for_folder(
        metadata.canonical_url,
        candidate.folder,
        apply=True,
        cookies=cookies,
        timeout=timeout,
        metadata=metadata,
    )
    return with_match(result, candidate.method, candidate.score)


def _with_input(result: CoverResult, source: str, line: int) -> CoverResult:
    return CoverResult(**{**asdict(result), "source_file": source, "source_line": line})


def process_url_folder(
    urls_folder: Path,
    destinations: Sequence[Path],
    *,
    apply: bool,
    force: bool,
    cookies: Path | None,
    timeout: float,
    kavita_url: str | None = None,
    kavita_api_key: str | None = None,
    apply_kavita: bool = False,
    kavita_path_maps: Sequence[tuple[str, str]] = (),
    progress: Callable[[str], None] | None = None,
) -> tuple[list[CoverResult], list[dict[str, object]], list[Path]]:
    inputs, rejected, files = collect_url_folder(urls_folder)
    folders = series_folders(destinations)
    url_index = build_folder_url_index(folders)
    results: list[CoverResult] = []
    kavita: KavitaClient | None = None
    kavita_series: list[dict[str, Any]] = []
    if apply_kavita:
        if not apply:
            raise ValueError("--apply-kavita requires --apply")
        if not kavita_url or not kavita_api_key:
            raise ValueError("--apply-kavita requires --kavita-url and a non-empty API key environment variable")
        kavita = KavitaClient(kavita_url, kavita_api_key, timeout=timeout, path_maps=kavita_path_maps)
        kavita_series = kavita.list_series()

    for index, item in enumerate(inputs, start=1):
        if progress:
            progress(f"[{index}/{len(inputs)}] {item.canonical_url}")
        if not supports_cover_url(item.canonical_url):
            results.append(
                CoverResult(
                    url=item.canonical_url,
                    status="unsupported",
                    source_file=item.source,
                    source_line=item.line,
                    message="cover scraping is not configured for this host",
                )
            )
            continue
        try:
            direct, candidates = match_folder(item.canonical_url, folders, url_index=url_index)
            metadata: SeriesPageMetadata | None = None
            if direct is None:
                metadata = fetch_series_metadata(item.canonical_url, cookies=cookies, timeout=timeout)
                direct, candidates = match_folder(
                    item.canonical_url,
                    folders,
                    metadata=metadata,
                    url_index=url_index,
                )
            if direct is None:
                status = "ambiguous" if candidates else "not_downloaded"
                results.append(
                    CoverResult(
                        url=item.canonical_url,
                        status=status,
                        title=metadata.title if metadata else None,
                        cover_url=metadata.cover_url if metadata else None,
                        source_file=item.source,
                        source_line=item.line,
                        message=", ".join(str(candidate.folder) for candidate in candidates[:5]),
                    )
                )
                continue

            metadata = metadata or fetch_series_metadata(item.canonical_url, cookies=cookies, timeout=timeout)
            result = write_cover_for_folder(
                item.canonical_url,
                direct.folder,
                apply=apply,
                force=force,
                cookies=cookies,
                timeout=timeout,
                metadata=metadata,
            )
            result = _with_input(with_match(result, direct.method, direct.score), item.source, item.line)
            if kavita is not None and result.cover_file:
                result = apply_kavita_cover(
                    result,
                    direct.folder,
                    kavita_url=kavita_url or "",
                    api_key=kavita_api_key or "",
                    timeout=timeout,
                    path_maps=kavita_path_maps,
                    client=kavita,
                    series_rows=kavita_series,
                )
            results.append(result)
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            results.append(
                CoverResult(
                    url=item.canonical_url,
                    status="failed",
                    source_file=item.source,
                    source_line=item.line,
                    message=str(exc),
                )
            )
    return results, rejected, files
