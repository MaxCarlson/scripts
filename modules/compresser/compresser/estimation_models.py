"""Immutable contracts shared by deterministic estimation plans and execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import sys


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RecipeSpec:
    format: str
    mode: str
    quality: int | None
    perceptual_target: float
    encoder: str
    effort: int
    runtime_identity: str = ""
    metadata_policy: str = "preserve"
    alpha_policy: str = "preserve"
    dimension_policy: str = "preserve"
    retained_original_policy: str = "keep-if-larger"

    def __post_init__(self) -> None:
        if not self.format or not self.encoder:
            raise ValueError("Recipe format and encoder are required")
        if not all((self.metadata_policy, self.alpha_policy, self.dimension_policy, self.retained_original_policy)):
            raise ValueError("Recipe preservation policies must be explicit")
        if self.mode not in ("lossless", "lossy", "perceptual"):
            raise ValueError("Invalid recipe mode")
        if self.mode == "lossy" and (self.quality is None or not 1 <= self.quality <= 100):
            raise ValueError("Lossy recipe requires quality from 1 to 100")
        if self.mode != "lossy" and self.quality is not None:
            raise ValueError("Only lossy recipes accept quality")
        if not math.isfinite(self.perceptual_target) or not 0.8 <= self.perceptual_target <= 1.0:
            raise ValueError("Perceptual target must be finite and between 0.80 and 1.00")
        if not 0 <= self.effort <= 6:
            raise ValueError("Recipe effort must be from 0 to 6")

    @property
    def identity(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class EstimationBudget:
    max_images: int = 512
    max_new_encodes: int = 2000
    max_runtime_seconds: float = 300.0
    pilot_images: int = 64

    def __post_init__(self) -> None:
        if self.max_images < 1 or self.max_new_encodes < 1 or self.pilot_images < 1:
            raise ValueError("Estimation image, encode, and pilot budgets must be positive")
        if not math.isfinite(self.max_runtime_seconds) or self.max_runtime_seconds <= 0:
            raise ValueError("Estimation runtime budget must be positive and finite")


@dataclass(frozen=True, slots=True)
class PopulationMember:
    identity: str
    relative_path: str
    size_bytes: int | None
    group: str
    fingerprint: tuple[int | str, ...] = ()
    codec_class: str = "eligible"

    def __post_init__(self) -> None:
        path = Path(self.relative_path)
        if not self.identity or not self.relative_path or path.is_absolute() or ".." in path.parts:
            raise ValueError("Population member identity must be a safe relative path")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("Population member size cannot be negative")


@dataclass(frozen=True, slots=True)
class PopulationView:
    population_id: str
    root: Path
    owner: str
    depth: str
    filters: tuple[str, ...]
    completed: str
    members: tuple[PopulationMember, ...]

    def __post_init__(self) -> None:
        if not self.population_id or self.depth not in ("headers", "files"):
            raise ValueError("Population identity and supported inventory depth are required")
        if self.owner not in ("compresser", "mangadl"):
            raise ValueError("Unsupported population owner")
        identities = [member.identity for member in self.members]
        if len(identities) != len(set(identities)):
            raise ValueError("Population member identities must be unique")

    @property
    def groups(self) -> dict[str, tuple[PopulationMember, ...]]:
        grouped: dict[str, list[PopulationMember]] = {}
        for member in self.members:
            key = f"{member.group}|{member.codec_class}"
            grouped.setdefault(key, []).append(member)
        return {key: tuple(rows) for key, rows in sorted(grouped.items())}


@dataclass(frozen=True, slots=True)
class StratumPlan:
    key: str
    member_count: int
    total_bytes: int | None
    selected_prefix: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecipeQuota:
    recipe_id: str
    per_stratum: tuple[tuple[str, int], ...]

    @property
    def total(self) -> int:
        return sum(count for _, count in self.per_stratum)


@dataclass(frozen=True, slots=True)
class EstimationPlan:
    plan_id: str
    design_identity: str
    population_id: str
    root: Path
    owner: str
    depth: str
    filters: tuple[str, ...]
    inventory_completed: str
    seed: int
    accuracy_pp: float | None
    allow_larger: bool
    recipes: tuple[RecipeSpec, ...]
    budget: EstimationBudget
    strata: tuple[StratumPlan, ...]
    selected_member_ids: tuple[str, ...]
    recipe_quotas: tuple[RecipeQuota, ...]
    design_payload: dict
    coverage_gaps: tuple[str, ...] = ()
    measurements: tuple[dict, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.plan_id or not self.design_identity:
            raise ValueError("Plan ID and immutable design identity are required")
        if len({recipe.identity for recipe in self.recipes}) != len(self.recipes):
            raise ValueError("Plan recipes must be unique")
        if design_digest(self.design_payload) != self.design_identity:
            raise ValueError("Plan immutable design identity does not match its inputs")

    def to_dict(self) -> dict:
        value = asdict(self)
        value["root"] = str(self.root)
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "EstimationPlan":
        if value.get("schema_version") != 1:
            raise ValueError("Unsupported estimation plan schema")
        data = dict(value)
        data["root"] = Path(data["root"])
        data["filters"] = tuple(data["filters"])
        data["recipes"] = tuple(RecipeSpec(**row) for row in data["recipes"])
        data["budget"] = EstimationBudget(**data["budget"])
        data["strata"] = tuple(
            StratumPlan(**{**row, "selected_prefix": tuple(row["selected_prefix"])})
            for row in data["strata"]
        )
        data["selected_member_ids"] = tuple(data["selected_member_ids"])
        data["recipe_quotas"] = tuple(
            RecipeQuota(**{**row, "per_stratum": tuple(tuple(item) for item in row["per_stratum"])})
            for row in data["recipe_quotas"]
        )
        data["coverage_gaps"] = tuple(data.get("coverage_gaps", ()))
        data["measurements"] = tuple(data.get("measurements", ()))
        return cls(**data)


def design_digest(value: object) -> str:
    """Stable SHA-256 identity for immutable design inputs."""
    return _digest(value)


def current_runtime_identity() -> str:
    """Identity of the non-encoding runtime contract available at plan time."""
    import PIL
    from PIL import features

    jpegtran = shutil.which("jpegtran")
    jpegtran_identity = None
    if jpegtran:
        stamp = Path(jpegtran).stat()
        jpegtran_identity = (str(Path(jpegtran).resolve()), stamp.st_size, stamp.st_mtime_ns)

    return _digest(
        {
            "planner_schema": 1,
            "python": platform.python_implementation() + " " + platform.python_version(),
            "pillow": PIL.__version__,
            "jpeg": features.version_codec("jpg"),
            "webp": features.version_module("webp"),
            "zlib": features.version_codec("zlib"),
            "avif": features.version_module("avif") if "avif" in features.get_supported_modules() else None,
            "jpegtran": jpegtran_identity,
            "platform": sys.platform,
        }
    )
