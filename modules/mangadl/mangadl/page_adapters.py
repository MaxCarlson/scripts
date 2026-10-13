"""Read-only expected-page enumeration for proven source backends."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .backends import gallery_dl_scope

_NHENTAI = re.compile(r"^https?://(?:www\.)?nhentai\.net/g/(\d+)/?$")
MAX_EXPECTED_PAGES = 20_000


@dataclass(frozen=True, slots=True)
class ExpectedPages:
    count: int
    identities: tuple[int, ...] | None
    evidence: str
    complete_identity_set: bool


def resolve_expected_pages(
    url: str,
    *,
    progress: Callable[[str], None] | None = None,
    extractor_finder: Callable[[str], Any] | None = None,
) -> ExpectedPages | None:
    """Enumerate source page IDs without constructing a gallery-dl download job.

    Extractor iteration may request source metadata/API pages, but it does not
    fetch image payloads or open/mutate a download archive. Broad collection
    routes and non-gallery extractors deliberately remain unsupported.
    """
    scope = gallery_dl_scope(url)
    if scope is None or scope.broad_collection or scope.subcategory != "gallery":
        return None
    finder = extractor_finder
    if finder is None:
        from gallery_dl import extractor

        finder = extractor.find
    instance = finder(url)
    if instance is None:
        return None
    from gallery_dl.extractor.message import Message

    numbers: list[int] = []
    for kind, _source, data in instance:
        if kind != Message.Url or not isinstance(data, dict):
            continue
        number = data.get("num")
        if number is None:
            continue
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        if number > 0:
            numbers.append(number)
        if len(numbers) > MAX_EXPECTED_PAGES:
            raise ValueError(f"source exceeded the {MAX_EXPECTED_PAGES:,}-page audit limit")
        if progress and len(numbers) and len(numbers) % 500 == 0:
            progress(f"Enumerated {len(numbers):,} expected source pages")
    if not numbers:
        return None
    unique = tuple(sorted(set(numbers)))
    complete = len(unique) == len(numbers) and unique == tuple(range(1, unique[-1] + 1))
    if not complete:
        return ExpectedPages(len(numbers), unique, f"{scope.category}/{scope.subcategory}: non-contiguous page IDs", False)
    evidence = "nhentai gallery metadata" if _NHENTAI.fullmatch(url) else f"gallery-dl {scope.category}/{scope.subcategory} page IDs"
    return ExpectedPages(len(unique), unique, evidence, True)
