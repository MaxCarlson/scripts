"""Translation catalog + matching helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional

from .config import MatchingConfig
from .utils import fingerprint_text, normalize_whitespace


@dataclass(slots=True)
class CatalogEntry:
    fingerprint: str
    source: str
    language: str
    target_language: str
    text: str
    safe_title: Optional[str] = None
    metadata: Optional[dict] = None


class TranslationCatalog:
    def __init__(self, path: Path, cfg: MatchingConfig | None = None):
        self.path = Path(path)
        self.cfg = cfg or MatchingConfig()
        self.entries: List[CatalogEntry] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                self.entries.append(CatalogEntry(**payload))

    def add(self, entry: CatalogEntry) -> None:
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def find_similar(self, text: str, target_language: str) -> Optional[CatalogEntry]:
        cleaned = normalize_whitespace(text)
        if len(cleaned) < self.cfg.min_chars:
            return None
        fp = fingerprint_text(cleaned, algo=self.cfg.hash_algorithm)
        for entry in self.entries:
            if entry.fingerprint == fp and entry.target_language == target_language:
                return entry
        return None

    def iter_language(self, target_language: str) -> Iterable[CatalogEntry]:
        for entry in self.entries:
            if entry.target_language == target_language:
                yield entry


__all__ = ["TranslationCatalog", "CatalogEntry"]
