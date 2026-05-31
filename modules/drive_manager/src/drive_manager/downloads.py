from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# Mimic a real browser session — some CDNs / download portals reject requests
# that lack these headers or block non-browser Accept values.
_DOWNLOAD_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/octet-stream,application/zip,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    # Force the server to send raw (un-gzip'd) bytes so we write the real file.
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def download_to_cache(url: str, cache_dir: Path | None = None, target_path: Path | None = None) -> Path:
    if target_path is not None:
        target = Path(target_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        cache = cache_dir or Path.home() / ".cache" / "drive-manager" / "downloads"
        cache.mkdir(parents=True, exist_ok=True)
        parsed = urlparse(url)
        filename = Path(parsed.path).name or "download.img"
        target = cache / filename

    req = urllib.request.Request(url, headers=_DOWNLOAD_HEADERS)
    with urllib.request.urlopen(req) as response, target.open("wb") as fh:
        expected = _content_length(response)
        shutil.copyfileobj(response, fh, length=1024 * 1024)

    actual = target.stat().st_size
    if expected is not None and actual != expected:
        target.unlink(missing_ok=True)
        raise IOError(
            f"Download incomplete: expected {expected:,} bytes, got {actual:,} bytes from {url}. "
            "The server may require a browser session — try downloading manually."
        )
    return target


def _content_length(response) -> int | None:
    try:
        val = response.headers.get("Content-Length")
        return int(val) if val else None
    except (TypeError, ValueError):
        return None
