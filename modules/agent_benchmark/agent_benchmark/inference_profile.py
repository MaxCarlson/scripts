"""Validated, reproducible per-experiment OpenCode inference settings."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class InferenceProfile:
    context_length: int
    output_limit: int
    reasoning_mode: str
    reasoning_effort: str | None
    provenance: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "opencode-inference-profile-v1",
            "context_length": self.context_length,
            "output_limit": self.output_limit,
            "reasoning": {"mode": self.reasoning_mode, "effort": self.reasoning_effort,
                          "provenance": self.provenance},
            "sha256": self.sha256,
        }


def load_inference_profile(path: Path) -> InferenceProfile:
    """Load a small allowlisted JSON profile; reject unknown keys to avoid secret capture."""
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"schema", "context_length", "output_limit", "reasoning"}:
        raise ValueError("Inference profile must contain only schema, context_length, output_limit, and reasoning")
    if data["schema"] != "opencode-inference-profile-v1":
        raise ValueError("Unsupported inference profile schema")
    for field in ("context_length", "output_limit"):
        value = data[field]
        if type(value) is not int or value <= 0:
            raise ValueError(f"Inference profile {field} must be a positive integer")
    reasoning = data["reasoning"]
    if not isinstance(reasoning, dict) or set(reasoning) != {"mode", "effort", "provenance"}:
        raise ValueError("Inference profile reasoning must contain only mode, effort, and provenance")
    mode, effort, provenance = reasoning["mode"], reasoning["effort"], reasoning["provenance"]
    if mode not in {"unconfigured", "effort"}:
        raise ValueError("Reasoning mode must be unconfigured or effort")
    if mode == "effort":
        if effort not in {"none", "low", "medium", "high", "xhigh"}:
            raise ValueError("Effort mode requires none, low, medium, high, or xhigh")
    elif effort is not None:
        raise ValueError("Unconfigured or disabled reasoning cannot name an effort")
    expected_provenance = {"unconfigured": "source_config", "effort": "experiment_profile"}[mode]
    if provenance != expected_provenance:
        raise ValueError(f"Reasoning provenance for {mode} must be {expected_provenance}")
    return InferenceProfile(data["context_length"], data["output_limit"], mode, effort, provenance,
                            hashlib.sha256(raw).hexdigest())


def validate_context_match(profile: InferenceProfile, context_length: int) -> None:
    if profile.context_length != context_length:
        raise ValueError(
            f"Inference profile context_length {profile.context_length} does not match requested context {context_length}"
        )
