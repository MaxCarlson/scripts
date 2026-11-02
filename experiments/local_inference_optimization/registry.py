"""Versioned feature-profile schema and registry for inference optimization (P05)."""

from __future__ import annotations

import math
import re
from typing import Any

from .contracts import (
    MAX_ITEMS,
    _id,
    _mapping,
    _version,
    canonical_bytes,
)

FEATURE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
PARAM_TYPES = {"int", "float", "str", "bool"}
FEATURE_DEF_SCHEMA = "lio-feature-def-v1"


def _feature_id(value: Any) -> str:
    if not isinstance(value, str) or not FEATURE_ID_RE.fullmatch(value):
        raise ValueError(f"invalid feature identifier: {value!r}")
    return value


def _semver(value: Any) -> str:
    if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
        raise ValueError(f"invalid semantic version: {value!r}")
    return value


def validate_parameter_spec(name: str, spec: dict[str, Any]) -> None:
    _feature_id(name)
    _mapping(spec, ("type",), ("bounds", "default"))
    param_type = spec["type"]
    if param_type not in PARAM_TYPES:
        raise ValueError(f"unsupported parameter type: {param_type!r}")

    bounds = spec.get("bounds")
    default = spec.get("default")

    if param_type in {"int", "float"}:
        if bounds is not None:
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                raise ValueError(f"numeric bounds must be a (min, max) pair for {name}")
            min_val, max_val = bounds
            expected_type = int if param_type == "int" else (int, float)
            if not isinstance(min_val, expected_type) or not isinstance(
                max_val, expected_type
            ):
                raise ValueError(f"bounds type mismatch for {name}")
            if min_val > max_val:
                raise ValueError(f"min bound exceeds max bound for {name}")
            if isinstance(min_val, float) and not math.isfinite(min_val):
                raise ValueError(f"non-finite bound for {name}")
            if isinstance(max_val, float) and not math.isfinite(max_val):
                raise ValueError(f"non-finite bound for {name}")

        if default is not None:
            expected_type = int if param_type == "int" else (int, float)
            if not isinstance(default, expected_type) or (isinstance(default, bool)):
                raise ValueError(f"default value type mismatch for {name}")
            if isinstance(default, float) and not math.isfinite(default):
                raise ValueError(f"non-finite default for {name}")
            if bounds is not None and not (bounds[0] <= default <= bounds[1]):
                raise ValueError(
                    f"default {default} outside bounds {bounds} for {name}"
                )

    elif param_type == "str":
        if bounds is not None:
            if not isinstance(bounds, (list, tuple)) or not bounds:
                raise ValueError(
                    f"string bounds must be a non-empty enum list for {name}"
                )
            if any(not isinstance(opt, str) or not opt for opt in bounds):
                raise ValueError(f"invalid enum value in bounds for {name}")
            if len(set(bounds)) != len(bounds):
                raise ValueError(f"duplicate enum values in bounds for {name}")

        if default is not None:
            if not isinstance(default, str):
                raise ValueError(f"default value type mismatch for {name}")
            if bounds is not None and default not in bounds:
                raise ValueError(f"default {default!r} not in enum {bounds} for {name}")

    elif param_type == "bool":
        if bounds is not None:
            raise ValueError(f"boolean parameters do not accept bounds for {name}")
        if default is not None and not isinstance(default, bool):
            raise ValueError(f"boolean default must be a bool for {name}")


def validate_feature_def(feature: dict[str, Any]) -> dict[str, Any]:
    _mapping(
        feature,
        (
            "schema",
            "feature_id",
            "version",
            "scope",
            "description",
            "parameters",
            "dependencies",
            "conflicts",
            "backend_capabilities",
            "reload_required",
        ),
    )
    _version(feature["schema"], FEATURE_DEF_SCHEMA)
    _feature_id(feature["feature_id"])
    _semver(feature["version"])

    if (
        not isinstance(feature["description"], str)
        or not 0 < len(feature["description"]) <= 512
    ):
        raise ValueError("invalid feature description")

    scope = feature["scope"]
    if scope not in {"load_time", "request_time"}:
        raise ValueError(f"invalid feature scope: {scope!r}")

    if not isinstance(feature["reload_required"], bool):
        raise ValueError("reload_required must be a boolean")

    # Scope and reload invariant: request-time features cannot require model reload
    if scope == "request_time" and feature["reload_required"]:
        raise ValueError("request_time feature cannot require model reload")

    params = feature["parameters"]
    if not isinstance(params, dict) or len(params) > MAX_ITEMS:
        raise ValueError("invalid parameters mapping")
    for name, spec in params.items():
        validate_parameter_spec(name, spec)

    deps = feature["dependencies"]
    if not isinstance(deps, list) or len(deps) > MAX_ITEMS:
        raise ValueError("invalid dependencies list")
    for dep in deps:
        if not isinstance(dep, str) or not dep:
            raise ValueError("invalid dependency identifier")
        # Allowed formats: feature_id or backend:name>=version
        if ":" in dep:
            _id(
                dep.replace(">=", "_")
                .replace(">", "_")
                .replace("=", "_")
                .replace("<", "_")
            )
        else:
            _feature_id(dep)

    conflicts = feature["conflicts"]
    if not isinstance(conflicts, list) or len(conflicts) > MAX_ITEMS:
        raise ValueError("invalid conflicts list")
    for conf in conflicts:
        _feature_id(conf)
    if feature["feature_id"] in conflicts:
        raise ValueError(f"feature {feature['feature_id']} cannot conflict with itself")

    caps = feature["backend_capabilities"]
    if not isinstance(caps, list) or len(caps) > MAX_ITEMS:
        raise ValueError("invalid backend_capabilities list")
    for cap in caps:
        _feature_id(cap)

    canonical_bytes(feature)
    return feature


STANDARD_FEATURES: list[dict[str, Any]] = [
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "context",
        "version": "1.0.0",
        "scope": "load_time",
        "description": "Context window token capacity allocated during model load.",
        "parameters": {
            "context": {
                "type": "int",
                "bounds": [1, 1048576],
                "default": 4096,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": [],
        "reload_required": True,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "output_limit",
        "version": "1.0.0",
        "scope": "request_time",
        "description": "Maximum generation output token budget.",
        "parameters": {
            "output_limit": {
                "type": "int",
                "bounds": [1, 131072],
                "default": 4096,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": [],
        "reload_required": False,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "temperature",
        "version": "1.0.0",
        "scope": "request_time",
        "description": "Sampling temperature for output randomness.",
        "parameters": {
            "temperature": {
                "type": "float",
                "bounds": [0.0, 2.0],
                "default": 0.0,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": [],
        "reload_required": False,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "top_p",
        "version": "1.0.0",
        "scope": "request_time",
        "description": "Nucleus sampling probability threshold.",
        "parameters": {
            "top_p": {
                "type": "float",
                "bounds": [0.0, 1.0],
                "default": 1.0,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": [],
        "reload_required": False,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "top_k",
        "version": "1.0.0",
        "scope": "request_time",
        "description": "Top-k vocabulary truncation cutoff (0 disables).",
        "parameters": {
            "top_k": {
                "type": "int",
                "bounds": [0, 1000],
                "default": 0,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": [],
        "reload_required": False,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "batch_size",
        "version": "1.0.0",
        "scope": "load_time",
        "description": "Evaluation batch size for prompt processing.",
        "parameters": {
            "batch_size": {
                "type": "int",
                "bounds": [1, 4096],
                "default": 512,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": [],
        "reload_required": True,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "flash_attention",
        "version": "1.0.0",
        "scope": "load_time",
        "description": "Enable Flash Attention kernel acceleration during load.",
        "parameters": {
            "flash_attention": {
                "type": "bool",
                "default": False,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": ["flash_attention"],
        "reload_required": True,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "gpu_kv_cache",
        "version": "1.0.0",
        "scope": "load_time",
        "description": "Offload KV cache memory to GPU VRAM.",
        "parameters": {
            "gpu_kv_cache": {
                "type": "bool",
                "default": True,
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": ["gpu_kv_cache"],
        "reload_required": True,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "reasoning",
        "version": "1.0.0",
        "scope": "request_time",
        "description": "Reasoning effort and thinking budget mode.",
        "parameters": {
            "reasoning": {
                "type": "str",
                "bounds": ["off", "none", "low", "medium", "high", "xhigh"],
                "default": "off",
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": [],
        "reload_required": False,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "speculation_mode",
        "version": "1.0.0",
        "scope": "load_time",
        "description": "Speculative decoding operating mode.",
        "parameters": {
            "speculation_mode": {
                "type": "str",
                "bounds": ["off", "mtp", "draft_model"],
                "default": "off",
            }
        },
        "dependencies": [],
        "conflicts": [],
        "backend_capabilities": ["speculative_decoding"],
        "reload_required": True,
    },
    {
        "schema": FEATURE_DEF_SCHEMA,
        "feature_id": "max_draft_tokens",
        "version": "1.0.0",
        "scope": "load_time",
        "description": "Maximum draft speculation token lookahead.",
        "parameters": {
            "max_draft_tokens": {
                "type": "int",
                "bounds": [1, 64],
                "default": 4,
            }
        },
        "dependencies": ["speculation_mode"],
        "conflicts": [],
        "backend_capabilities": ["speculative_decoding"],
        "reload_required": True,
    },
]


class FeatureRegistry:
    """Thread-safe, versioned registry of inference features and validation constraints."""

    def __init__(self, include_defaults: bool = True) -> None:
        self._features: dict[str, dict[str, Any]] = {}
        if include_defaults:
            for feat in STANDARD_FEATURES:
                self.register(feat)

    def register(self, feature_def: dict[str, Any]) -> None:
        validated = validate_feature_def(feature_def)
        fid = validated["feature_id"]
        self._features[fid] = validated

    def get(self, feature_id: str) -> dict[str, Any]:
        if feature_id not in self._features:
            raise KeyError(f"unknown feature: {feature_id!r}")
        return self._features[feature_id]

    def has(self, feature_id: str) -> bool:
        return feature_id in self._features

    def list_features(self) -> list[str]:
        return sorted(self._features.keys())

    def get_feature_for_param(self, param_name: str) -> dict[str, Any] | None:
        for feat in self._features.values():
            if param_name in feat["parameters"]:
                return feat
        return None

    def validate_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(settings, dict):
            raise ValueError("settings must be a dictionary")

        # 1. Parameter presence and bounds validation
        active_feature_ids: set[str] = set()
        for name, value in settings.items():
            feat = self.get_feature_for_param(name)
            if feat is None:
                raise ValueError(f"unknown setting parameter: {name!r}")

            spec = feat["parameters"][name]
            param_type = spec["type"]
            bounds = spec.get("bounds")

            if param_type == "int":
                if type(value) is not int:
                    raise ValueError(
                        f"expected int for {name}, got {type(value).__name__}"
                    )
                if bounds and not (bounds[0] <= value <= bounds[1]):
                    raise ValueError(f"value {value} for {name} out of bounds {bounds}")

            elif param_type == "float":
                if type(value) not in (int, float):
                    raise ValueError(
                        f"expected float for {name}, got {type(value).__name__}"
                    )
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"non-finite value for {name}")
                if bounds and not (bounds[0] <= float(value) <= bounds[1]):
                    raise ValueError(f"value {value} for {name} out of bounds {bounds}")

            elif param_type == "str":
                if not isinstance(value, str):
                    raise ValueError(
                        f"expected str for {name}, got {type(value).__name__}"
                    )
                if bounds and value not in bounds:
                    raise ValueError(f"value {value!r} for {name} not in enum {bounds}")

            elif param_type == "bool":
                if not isinstance(value, bool):
                    raise ValueError(
                        f"expected bool for {name}, got {type(value).__name__}"
                    )

            active_feature_ids.add(feat["feature_id"])

        # 2. Dependency validation
        for fid in active_feature_ids:
            feat = self._features[fid]
            for dep in feat["dependencies"]:
                # If dependency is another feature
                if ":" not in dep and dep not in active_feature_ids:
                    raise ValueError(
                        f"feature {fid} requires missing dependency: {dep}"
                    )

        # 3. Conflict validation
        for fid in sorted(active_feature_ids):
            feat = self._features[fid]
            for conf in sorted(feat["conflicts"]):
                if conf in active_feature_ids:
                    raise ValueError(f"conflicting features detected: {fid} and {conf}")

        return settings

    def get_required_capabilities(self, settings: dict[str, Any]) -> list[str]:
        required: set[str] = set()
        for name in settings:
            feat = self.get_feature_for_param(name)
            if feat:
                required.update(feat["backend_capabilities"])
        return sorted(required)

    def requires_reload(self, settings: dict[str, Any]) -> bool:
        for name in settings:
            feat = self.get_feature_for_param(name)
            if feat and feat.get("reload_required", False):
                return True
        return False
