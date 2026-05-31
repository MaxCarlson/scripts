from __future__ import annotations

import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def download_to_cache(url: str, cache_dir: Path | None = None) -> Path:
    cache = cache_dir or Path.home() / ".cache" / "drive-manager" / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "download.img"
    target = cache / filename
    with urllib.request.urlopen(url) as response, target.open("wb") as fh:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
    return target
