"""Configuration dataclasses for the translations module."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

DEFAULT_EXTENSIONS = (".mp4", ".mkv", ".webm", ".avi")
DEFAULT_LANGS = ("en",)
JAPANESE_PRIORITY_MODELS = (
    "faster-whisper-large-v3",
    "openai-gpt-whisper-large",
)


@dataclass(slots=True)
class TranscriberConfig:
    name: str = "faster-whisper"
    model_size: str = "large-v3"
    language: Optional[str] = None
    initial_prompt: Optional[str] = None
    temperature: float = 0.0
    use_vad: bool = True
    batch_size: int = 8
    best_of: int = 3


@dataclass(slots=True)
class TranslatorConfig:
    name: str = "deepl"
    target_languages: Sequence[str] = field(default_factory=lambda: DEFAULT_LANGS)
    glossary_path: Optional[Path] = None
    allow_machine_only: bool = True
    max_length: int = 180


@dataclass(slots=True)
class PipelineConfig:
    sources: Sequence[Path]
    tmp_dir: Path
    catalog_path: Optional[Path] = None
    overwrite: bool = False
    extensions: Sequence[str] = field(default_factory=lambda: DEFAULT_EXTENSIONS)
    transcriber: TranscriberConfig = field(default_factory=TranscriberConfig)
    translator: TranslatorConfig = field(default_factory=TranslatorConfig)
    export_srt: bool = True
    export_vtt: bool = True
    export_json: bool = True
    write_safe_titles: bool = True

    def iter_sources(self) -> Iterable[Path]:
        for src in self.sources:
            src = Path(src)
            if src.is_file():
                yield src
            elif src.is_dir():
                for ext in self.extensions:
                    yield from src.rglob(f"*{ext}")


@dataclass(slots=True)
class MatchingConfig:
    min_chars: int = 120
    max_chars: int = 600
    reduce_whitespace: bool = True
    hash_algorithm: str = "sha256"


__all__ = [
    "TranscriberConfig",
    "TranslatorConfig",
    "PipelineConfig",
    "MatchingConfig",
    "DEFAULT_EXTENSIONS",
    "DEFAULT_LANGS",
    "JAPANESE_PRIORITY_MODELS",
]
