import copy
import pytest

from local_inference_optimization.registry import (
    FEATURE_DEF_SCHEMA,
    FeatureRegistry,
    validate_feature_def,
)

SAMPLE_FEATURE = {
    "schema": FEATURE_DEF_SCHEMA,
    "feature_id": "test_param",
    "version": "1.0.0",
    "scope": "request_time",
    "description": "Test feature definition.",
    "parameters": {
        "test_param": {
            "type": "float",
            "bounds": [0.0, 1.0],
            "default": 0.5,
        }
    },
    "dependencies": [],
    "conflicts": [],
    "backend_capabilities": [],
    "reload_required": False,
}


def test_valid_feature_definition():
    feat = copy.deepcopy(SAMPLE_FEATURE)
    assert validate_feature_def(feat) == feat


def test_invalid_feature_schema_rejected():
    feat = copy.deepcopy(SAMPLE_FEATURE)
    feat["schema"] = "lio-feature-def-v2"
    with pytest.raises(ValueError, match="unsupported schema"):
        validate_feature_def(feat)


def test_invalid_feature_id_rejected():
    feat = copy.deepcopy(SAMPLE_FEATURE)
    feat["feature_id"] = "INVALID ID WITH SPACES"
    with pytest.raises(ValueError, match="invalid feature identifier"):
        validate_feature_def(feat)


def test_invalid_semver_rejected():
    feat = copy.deepcopy(SAMPLE_FEATURE)
    feat["version"] = "v1"
    with pytest.raises(ValueError, match="invalid semantic version"):
        validate_feature_def(feat)


def test_request_time_cannot_require_reload():
    feat = copy.deepcopy(SAMPLE_FEATURE)
    feat["scope"] = "request_time"
    feat["reload_required"] = True
    with pytest.raises(
        ValueError, match="request_time feature cannot require model reload"
    ):
        validate_feature_def(feat)


def test_self_conflict_rejected():
    feat = copy.deepcopy(SAMPLE_FEATURE)
    feat["conflicts"] = ["test_param"]
    with pytest.raises(ValueError, match="cannot conflict with itself"):
        validate_feature_def(feat)


def test_parameter_bounds_and_type_validation():
    feat = copy.deepcopy(SAMPLE_FEATURE)
    # Min bound exceeds max bound
    feat["parameters"]["test_param"]["bounds"] = [2.0, 1.0]
    with pytest.raises(ValueError, match="min bound exceeds max bound"):
        validate_feature_def(feat)

    # Default out of bounds
    feat = copy.deepcopy(SAMPLE_FEATURE)
    feat["parameters"]["test_param"]["default"] = 1.5
    with pytest.raises(ValueError, match="outside bounds"):
        validate_feature_def(feat)

    # Boolean with bounds rejected
    feat = copy.deepcopy(SAMPLE_FEATURE)
    feat["parameters"]["test_param"] = {"type": "bool", "bounds": [0, 1]}
    with pytest.raises(ValueError, match="boolean parameters do not accept bounds"):
        validate_feature_def(feat)


def test_registry_lookup_and_unknown_rejection():
    reg = FeatureRegistry(include_defaults=True)
    assert reg.has("context")
    assert reg.has("temperature")
    assert not reg.has("nonexistent_feature")

    with pytest.raises(KeyError, match="unknown feature"):
        reg.get("nonexistent_feature")


def test_registry_parameter_validation_and_bounds():
    reg = FeatureRegistry(include_defaults=True)
    # Valid settings
    validated = reg.validate_settings(
        {"context": 8192, "temperature": 0.7, "top_p": 0.95}
    )
    assert validated["context"] == 8192
    assert validated["temperature"] == 0.7

    # Unknown parameter rejected
    with pytest.raises(ValueError, match="unknown setting parameter"):
        reg.validate_settings({"unsupported_knob": 123})

    # Out of bounds rejected
    with pytest.raises(ValueError, match="out of bounds"):
        reg.validate_settings({"temperature": 5.0})

    # Type mismatch rejected
    with pytest.raises(ValueError, match="expected int"):
        reg.validate_settings({"context": "8192"})


def test_registry_dependency_validation():
    reg = FeatureRegistry(include_defaults=True)
    # max_draft_tokens depends on speculation_mode
    with pytest.raises(
        ValueError, match="requires missing dependency: speculation_mode"
    ):
        reg.validate_settings({"max_draft_tokens": 4})

    # When speculation_mode is present, validation succeeds
    valid = reg.validate_settings({"speculation_mode": "mtp", "max_draft_tokens": 4})
    assert valid["max_draft_tokens"] == 4


def test_registry_conflict_validation():
    reg = FeatureRegistry(include_defaults=False)
    feat_a = copy.deepcopy(SAMPLE_FEATURE)
    feat_a["feature_id"] = "feat_a"
    feat_a["conflicts"] = ["feat_b"]
    feat_a["parameters"] = {"param_a": {"type": "bool", "default": False}}

    feat_b = copy.deepcopy(SAMPLE_FEATURE)
    feat_b["feature_id"] = "feat_b"
    feat_b["conflicts"] = ["feat_a"]
    feat_b["parameters"] = {"param_b": {"type": "bool", "default": False}}

    reg.register(feat_a)
    reg.register(feat_b)

    with pytest.raises(
        ValueError, match="conflicting features detected: feat_a and feat_b"
    ):
        reg.validate_settings({"param_a": True, "param_b": True})


def test_registry_capability_extraction_and_reload():
    reg = FeatureRegistry(include_defaults=True)
    caps = reg.get_required_capabilities(
        {"flash_attention": True, "speculation_mode": "mtp", "max_draft_tokens": 4}
    )
    assert caps == ["flash_attention", "speculative_decoding"]

    assert reg.requires_reload({"context": 16384}) is True
    assert reg.requires_reload({"temperature": 0.5}) is False
