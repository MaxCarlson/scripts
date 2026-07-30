from __future__ import annotations

import re

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)
METADATA_DIR_NAME = "_mangadl"
SOURCE_MANIFEST_NAME = "source.json"
COVER_APPLIED_NAME = "cover-applied.json"
COVER_PENDING_NAME = "cover-kavita-pending.json"
COVER_STEM = "cover-original"
SCHEMA_VERSION = 1
URL_FILE_RE = re.compile(r"^url.*\.txt$", re.IGNORECASE)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
CONTENT_TYPE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
}
SUPPORTED_COVER_HOSTS = {
    "manga18fx.com",
    "www.manga18fx.com",
    "simply-hentai.com",
    "www.simply-hentai.com",
}
