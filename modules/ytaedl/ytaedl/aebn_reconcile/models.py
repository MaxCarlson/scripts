"""Data transfer objects used by the AEBN reconciliation workflow."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InputError:
    source_file: str
    line_number: int
    value: str
    message: str


@dataclass
class SceneRequest:
    site: str
    content_type: str
    movie_id: str
    movie_url: str
    scene_id: str
    original_url: str
    sources: list[tuple[str, int]] = field(default_factory=list)

    @property
    def movie_key(self) -> str:
        return f"{self.site.lower()}|{self.content_type}|{self.movie_id}"


@dataclass
class ParsedInputs:
    requests: list[SceneRequest]
    errors: list[InputError]


@dataclass
class ScanResult:
    database_path: Path
    summary: dict[str, int]
    errors: list[str] = field(default_factory=list)
