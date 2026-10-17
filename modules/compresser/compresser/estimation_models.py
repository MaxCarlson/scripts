"""Immutable contracts shared by deterministic estimation plans and execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import sys


def _json_value(value: object):
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Unsupported design value: {type(value).__name__}")


def _digest(value: object) -> str:
    encoded = json.dumps(value, default=_json_value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
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
    ordered_member_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecipeQuota:
    recipe_id: str
    per_stratum: tuple[tuple[str, int], ...]

    @property
    def total(self) -> int:
        return sum(count for _, count in self.per_stratum)


@dataclass(frozen=True, slots=True)
class RecipeObservation:
    member_id: str
    recipe_id: str
    fingerprint: tuple[int | str, ...]
    runtime_identity: str
    input_bytes: int
    retained_bytes: int | None
    elapsed_seconds: float
    state: str = "measured"

    def __post_init__(self) -> None:
        if not isinstance(self.fingerprint, tuple):
            object.__setattr__(self, "fingerprint", tuple(self.fingerprint))
        if self.state not in ("measured", "retained_by_policy", "failed", "not_started", "interrupted"):
            raise ValueError("Unsupported observation state")
        if type(self.input_bytes) is not int or self.input_bytes < 0:
            raise ValueError("Observation input bytes must be nonnegative integers")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("Observation elapsed seconds must be finite and nonnegative")
        if self.complete:
            if type(self.retained_bytes) is not int or self.retained_bytes < 0:
                raise ValueError("Complete observations require nonnegative retained bytes")
            if self.state == "retained_by_policy" and self.retained_bytes != self.input_bytes:
                raise ValueError("Retained-by-policy observation must preserve the input byte count")
        elif self.retained_bytes is not None:
            raise ValueError("Incomplete observations cannot report retained bytes")

    @property
    def complete(self) -> bool:
        return self.state in ("measured", "retained_by_policy")

    @property
    def saved_bytes(self) -> int:
        if not self.complete:
            raise ValueError("Incomplete observation has no measured savings")
        return self.input_bytes - self.retained_bytes


@dataclass(frozen=True, slots=True)
class LinearPredictor:
    # Evaluating around an integer origin preserves small differences in large byte sizes.
    origin_x: int = 0
    mean_offset: float = 0.0
    mean_savings: float = 0.0
    slope: float = 0.0
    origin_y: int = 0

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.mean_offset, self.mean_savings, self.slope)):
            raise ValueError("Predictor coefficients must be finite")

    def predict(self, input_bytes: int) -> float:
        return self.origin_y + self.mean_savings + self.slope * ((input_bytes - self.origin_x) - self.mean_offset)

    def residual(self, input_bytes: int, saved_bytes: int) -> float:
        return (
            (saved_bytes - self.origin_y)
            - self.mean_savings
            - self.slope * ((input_bytes - self.origin_x) - self.mean_offset)
        )


@dataclass(frozen=True, slots=True)
class ConfirmationStratum:
    recipe_id: str
    stratum_key: str
    pilot_ids: tuple[str, ...]
    remaining_ids: tuple[str, ...]
    selected_ids: tuple[str, ...]
    predictor: LinearPredictor
    allocation_basis: str
    allocation_weight: float


@dataclass(frozen=True, slots=True)
class ConfirmationDesign:
    plan_identity: str
    pilot_digest: str
    groups: tuple[ConfirmationStratum, ...]
    estimator_revision: int = 1

    @property
    def identity(self) -> str:
        return design_digest(asdict(self))

    def to_dict(self) -> dict:
        return {**asdict(self), "design_identity": self.identity}

    @classmethod
    def from_dict(cls, value: dict) -> "ConfirmationDesign":
        data = dict(value)
        expected = data.pop("design_identity")
        data["groups"] = tuple(
            ConfirmationStratum(
                **{
                    **row,
                    "pilot_ids": tuple(row["pilot_ids"]),
                    "remaining_ids": tuple(row["remaining_ids"]),
                    "selected_ids": tuple(row["selected_ids"]),
                    "predictor": LinearPredictor(**row["predictor"]),
                }
            )
            for row in data["groups"]
        )
        result = cls(**data)
        if result.estimator_revision != 1 or result.identity != expected:
            raise ValueError("Confirmation design identity or estimator revision is invalid")
        return result


@dataclass(frozen=True, slots=True)
class GroupEstimate:
    estimated_saved_bytes: float | int | None
    variance: float | None
    population_count: int
    sample_count: int
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecipeEstimate:
    recipe_id: str
    plan_identity: str
    confirmation_identity: str
    estimated_saved_bytes: float | int | None
    variance: float | None
    total_input_bytes: int
    savings_percent: float | None
    interval: tuple[float, float] | None
    groups: tuple[GroupEstimate, ...]
    gaps: tuple[str, ...]
    interval_kind: str = "approximate_fixed_normal_95"

    @property
    def complete(self) -> bool:
        return self.interval is not None and not self.gaps


@dataclass(frozen=True, slots=True)
class EstimationProgress:
    sequence: int
    stage: str
    phase: str
    active_recipe: str = ""
    completed_sources: int = 0
    total_sources: int = 0
    new_encodes: int = 0
    cache_hits: int = 0
    remaining_trials: int = 0
    remaining_seconds: float = 0.0
    estimates: tuple[RecipeEstimate, ...] = ()
    stopping_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EstimationResult:
    plan: EstimationPlan
    estimates: tuple[RecipeEstimate, ...]
    stopping_reason: str
    stage: str
    cache_hits: int
    new_encodes: int
    newly_admitted_sources: int
    total_observations: int
    last_complete_estimates: tuple[RecipeEstimate, ...] = ()


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
    members: tuple[PopulationMember, ...]
    pilot_member_ids: tuple[str, ...]
    design_payload: dict
    coverage_gaps: tuple[str, ...] = ()
    measurements: tuple[dict, ...] = ()
    schema_version: int = 2
    grouping_revision: int = 2
    ordering_revision: int = 2
    confirmation: ConfirmationDesign | None = None

    def __post_init__(self) -> None:
        if not self.plan_id or not self.design_identity:
            raise ValueError("Plan ID and immutable design identity are required")
        if len({recipe.identity for recipe in self.recipes}) != len(self.recipes):
            raise ValueError("Plan recipes must be unique")
        self.validate_design()

    def validate_design(self) -> None:
        """Check the actual executable fields, rather than trusting a detached digest copy."""
        data = self.to_dict()
        for key in ("plan_id", "design_identity", "design_payload", "measurements", "confirmation"):
            data.pop(key)
        if design_digest(data) != self.design_identity or design_digest(self.design_payload) != self.design_identity:
            raise ValueError("Plan immutable design identity does not match its inputs")
        if self.confirmation is not None and self.confirmation.plan_identity != self.design_identity:
            raise ValueError("Confirmation design belongs to another plan identity")

    @classmethod
    def create(cls, **inputs) -> "EstimationPlan":
        inputs = {"schema_version": 2, "grouping_revision": 2, "ordering_revision": 2, "coverage_gaps": (), **inputs}
        payload = json.loads(json.dumps(inputs, default=_json_value, allow_nan=False))
        identity = design_digest(payload)
        return cls(plan_id=f"plan-{identity[:20]}", design_identity=identity, design_payload=payload, **inputs)

    def to_dict(self) -> dict:
        value = asdict(self)
        value["root"] = str(self.root)
        value["confirmation"] = self.confirmation.to_dict() if self.confirmation is not None else None
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "EstimationPlan":
        if value.get("schema_version") != 2:
            raise ValueError("Unsupported estimation plan schema; rebuild the plan from inventory")
        data = dict(value)
        data["root"] = Path(data["root"])
        data["filters"] = tuple(data["filters"])
        data["recipes"] = tuple(RecipeSpec(**row) for row in data["recipes"])
        data["budget"] = EstimationBudget(**data["budget"])
        data["strata"] = tuple(
            StratumPlan(
                **{
                    **row,
                    "selected_prefix": tuple(row["selected_prefix"]),
                    "ordered_member_ids": tuple(row["ordered_member_ids"]),
                }
            )
            for row in data["strata"]
        )
        data["selected_member_ids"] = tuple(data["selected_member_ids"])
        data["pilot_member_ids"] = tuple(data["pilot_member_ids"])
        data["members"] = tuple(
            PopulationMember(**{**row, "fingerprint": tuple(row["fingerprint"])}) for row in data["members"]
        )
        data["recipe_quotas"] = tuple(
            RecipeQuota(**{**row, "per_stratum": tuple(tuple(item) for item in row["per_stratum"])})
            for row in data["recipe_quotas"]
        )
        data["coverage_gaps"] = tuple(data.get("coverage_gaps", ()))
        data["measurements"] = tuple(
            (
                {**row, "fingerprint": tuple(row["fingerprint"])}
                if isinstance(row, dict) and "fingerprint" in row and not isinstance(row["fingerprint"], tuple)
                else row
            )
            for row in data.get("measurements", ())
        )
        data["confirmation"] = ConfirmationDesign.from_dict(data["confirmation"]) if data.get("confirmation") else None
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
