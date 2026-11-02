import copy
import pytest
from local_inference_optimization.contracts import (
    experiment_fingerprint,
    validate_evidence,
    variant_fingerprint,
)

DIGEST = "a" * 64
EXPERIMENT = {
    "schema": "lio-experiment-v1",
    "study_id": "study-1",
    "task_set": {"id": "tasks", "sha256": DIGEST},
    "baseline_ref": "baseline-1",
    "fixed": {"context": 4096, "temperature": 0},
    "dimensions": ["temperature"],
    "repetitions": 2,
    "randomization": {"method": "counterbalanced", "seed": 12},
    "success_criterion": "strict_accepted_task",
    "rejection_criterion": "infra_or_unverified",
}
VARIANT = {
    "schema": "lio-variant-v1",
    "model": {
        "alias": "model",
        "file_identity": {"status": "weak", "size_bytes": 128, "sha256": None},
        "quantization": "q4",
    },
    "context": 4096,
    "output_limit": 512,
    "reasoning": "off",
    "sampling": {"temperature": 0},
    "features": {},
    "prompt_policy": "prompt-v1",
    "config_sha256": DIGEST,
}


def test_fingerprints_canonical_and_changed_conditions():
    assert experiment_fingerprint(EXPERIMENT) == experiment_fingerprint(
        dict(reversed(list(EXPERIMENT.items())))
    )
    changed = copy.deepcopy(VARIANT)
    changed["context"] += 1
    assert variant_fingerprint(VARIANT) != variant_fingerprint(changed)


def test_requested_is_not_effective():
    evidence = {
        "schema": "lio-evidence-v1",
        "experiment_id": "e",
        "variant_sha256": DIGEST,
        "run_id": "r",
        "trial_id": "t",
        "producer": {"name": "fixture", "version": "1"},
        "observations": [
            {
                "field": "temperature",
                "stage": "requested",
                "value": 0,
                "status": "reported",
                "source": "profile",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    }
    result = validate_evidence(evidence)
    assert result["effective"] == {}


def test_verified_model_requires_digest():
    value = copy.deepcopy(VARIANT)
    value["model"]["file_identity"]["status"] = "verified"
    with pytest.raises(ValueError):
        variant_fingerprint(value)


def evidence_base():
    return {
        "schema": "lio-evidence-v1",
        "experiment_id": "e",
        "variant_sha256": DIGEST,
        "run_id": "r",
        "trial_id": "t",
        "producer": {"name": "fixture", "version": "1"},
        "observations": [],
    }


@pytest.mark.parametrize("schema", ["lio-evidence-v2", "unknown"])
def test_reject_unknown_evidence_schema(schema):
    e = evidence_base()
    e["schema"] = schema
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_effective_requires_correlated_observed_runtime():
    e = evidence_base()
    e["observations"] = [
        {
            "field": "temperature",
            "stage": "effective",
            "value": 0,
            "status": "verified",
            "source": "backend_runtime",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_sensitive_extra_evidence_rejected():
    e = evidence_base()
    e["authorization"] = "secret"
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_realistic_large_model_size_is_valid():
    value = copy.deepcopy(VARIANT)
    value["model"]["file_identity"]["size_bytes"] = 16810714336
    assert variant_fingerprint(value)


def test_unknown_backend_capability_stays_unknown():
    e = evidence_base()
    e["capabilities"] = [{"name": "mtp", "status": "unknown", "source": "offline"}]
    assert validate_evidence(e)["evidence"]["capabilities"][0]["status"] == "unknown"


def test_trial_identity_is_separate_from_variant():
    from local_inference_optimization.contracts import validate_trial

    t = {
        "schema": "lio-trial-v1",
        "experiment_sha256": DIGEST,
        "variant_sha256": variant_fingerprint(VARIANT),
        "run_id": "run1",
        "trial_id": "trial1",
        "task_id": "task",
        "repetition": 0,
        "evidence_ref": "evidence1",
        "source_revision": "b" * 40,
        "workspace_sha256": DIGEST,
    }
    assert validate_trial(t)["variant_sha256"] == variant_fingerprint(VARIANT)
    t["trial_id"] = "trial2"
    assert validate_trial(t)["variant_sha256"] == variant_fingerprint(VARIANT)


def test_verified_runtime_evidence_needs_backend_identity():
    e = evidence_base()
    obs = {
        "field": "temperature",
        "stage": "observed",
        "value": 0,
        "status": "verified",
        "source": "backend_runtime",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    e["observations"] = [obs, dict(obs, stage="effective")]
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_paths_not_part_of_variant_fingerprint():
    v = copy.deepcopy(VARIANT)
    v["model"]["file_identity"]["file_path"] = "C:/models/one.gguf"
    a = variant_fingerprint(v)
    v["model"]["file_identity"]["file_path"] = "D:/models/one.gguf"
    assert variant_fingerprint(v) == a


def test_legacy_profile_adapter_preserves_requested_only():
    from local_inference_optimization.adapters import legacy_profile_requests

    profile = {
        "schema": "opencode-inference-profile-v1",
        "context_length": 4096,
        "output_limit": 512,
        "reasoning": {
            "mode": "unconfigured",
            "effort": None,
            "provenance": "source_config",
        },
        "sha256": DIGEST,
    }
    observations = legacy_profile_requests(profile, "2026-01-01T00:00:00Z")
    assert {o["field"] for o in observations} == {"context", "output_limit"}
    assert all(o["stage"] == "requested" for o in observations)
    assert (
        validate_evidence(dict(evidence_base(), observations=observations))["effective"]
        == {}
    )


def test_legacy_profile_adapter_rejects_unrecognized_keys():
    from local_inference_optimization.adapters import legacy_profile_requests

    with pytest.raises(ValueError):
        legacy_profile_requests(
            {"schema": "opencode-inference-profile-v1", "token": "secret"},
            "2026-01-01T00:00:00Z",
        )


@pytest.mark.parametrize(
    "status,sha,expected",
    [
        ("weak", None, False),
        ("unknown", None, False),
        ("verified", DIGEST, True),
    ],
)
def test_model_identity_strength(status, sha, expected):
    from local_inference_optimization.contracts import has_verified_model_digest

    v = copy.deepcopy(VARIANT)
    v["model"]["file_identity"] = {
        "status": status,
        "size_bytes": None if status == "unknown" else 128,
        "sha256": sha,
    }
    assert has_verified_model_digest(v) is expected


def test_duplicate_and_contradictory_observations_rejected():
    e = evidence_base()
    obs = {
        "field": "temperature",
        "stage": "requested",
        "value": 0,
        "status": "reported",
        "source": "profile",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    e["observations"] = [obs, copy.deepcopy(obs)]
    with pytest.raises(ValueError):
        validate_evidence(e)
    e["observations"] = [dict(obs, status="unknown")]
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_bounded_and_sensitive_evidence_rejected():
    e = evidence_base()
    e["observations"] = [{}] * 257
    with pytest.raises(ValueError):
        validate_evidence(e)
    e = evidence_base()
    e["raw_prompt"] = "private"
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_existing_legacy_profile_round_trip(tmp_path):
    import importlib.util
    import json
    import sys
    from pathlib import Path
    from local_inference_optimization.adapters import legacy_profile_requests

    path = (
        Path(__file__).resolve().parents[3]
        / "modules/agent_benchmark/agent_benchmark/inference_profile.py"
    )
    spec = importlib.util.spec_from_file_location("p03_legacy_profile", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    f = tmp_path / "profile.json"
    f.write_text(
        json.dumps(
            {
                "schema": "opencode-inference-profile-v1",
                "context_length": 4096,
                "output_limit": 512,
                "reasoning": {
                    "mode": "effort",
                    "effort": "medium",
                    "provenance": "experiment_profile",
                },
            }
        )
    )
    result = legacy_profile_requests(
        module.load_inference_profile(f).to_dict(), "2026-01-01T00:00:00Z"
    )
    assert [x["field"] for x in result] == ["context", "output_limit", "reasoning"]


def test_monitor_forwarded_request_never_becomes_effective():
    from local_inference_optimization.adapters import monitor_request_observations

    evidence = {
        "value": {
            "provider": "provider",
            "model": "model",
            "parameters": {"temperature": 0.1, "top_p": 0.9},
        },
        "source": "external_request_capture",
        "verification_status": "verified",
    }
    normalized = monitor_request_observations(evidence, "2026-01-01T00:00:00Z")
    assert normalized["status"] == "verified"
    observations = normalized["observations"]
    result = validate_evidence(dict(evidence_base(), observations=observations))
    assert result["effective"] == {}
    assert {o["source"] for o in observations} == {"external_request_capture"}


def test_unverified_monitor_data_is_not_forwarded():
    from local_inference_optimization.adapters import monitor_request_observations

    assert monitor_request_observations(
        {"value": None, "source": "unavailable", "verification_status": "unavailable"},
        "2026-01-01T00:00:00Z",
    ) == {"status": "unavailable", "observations": []}


def test_benchmark_metric_compatible_with_core():
    from local_inference_optimization.adapters import benchmark_metric

    metric = {
        "value": 12.5,
        "unit": "ms",
        "source": "timer",
        "quality": "measured",
        "reason": None,
    }
    e = evidence_base()
    e["metrics"] = [benchmark_metric("duration", metric)]
    assert validate_evidence(e)["evidence"]["metrics"][0]["quality"] == "measured"


@pytest.mark.parametrize("bad_field", [[], {}, None, 7])
def test_malformed_observation_field_is_rejected(bad_field):
    e = evidence_base()
    e["observations"] = [
        {
            "field": bad_field,
            "stage": "requested",
            "value": 0,
            "status": "reported",
            "source": "profile",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_matching_runtime_attestation_requires_independent_observation():
    e = evidence_base()
    obs = {
        "field": "temperature",
        "stage": "observed",
        "value": 0,
        "status": "verified",
        "source": "backend_runtime",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    e["backend"] = {"identity": "backend", "version": "1"}
    e["artifacts"] = [{"id": "receipt", "sha256": DIGEST}]
    e["observations"] = [obs, dict(obs, stage="effective")]
    assert validate_evidence(e)["effective"] == {"temperature": 0}
    e["observations"][1]["value"] = 0.5
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_unavailable_metric_cannot_claim_value():
    e = evidence_base()
    e["metrics"] = [
        {
            "name": "latency",
            "value": 1,
            "unit": "ms",
            "quality": "unavailable",
            "source": "timer",
        }
    ]
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_rejects_bad_schema_and_missing_identity():
    e = copy.deepcopy(EXPERIMENT)
    e["schema"] = "lio-experiment-v2"
    with pytest.raises(ValueError):
        experiment_fingerprint(e)
    v = copy.deepcopy(VARIANT)
    del v["model"]["alias"]
    with pytest.raises(ValueError):
        variant_fingerprint(v)


def test_validation_does_not_use_services(monkeypatch):
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected external operation")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert experiment_fingerprint(EXPERIMENT)
    assert validate_evidence(evidence_base())["effective"] == {}


def test_canonical_bytes_rejects_deep_or_oversized_data():
    from local_inference_optimization.contracts import canonical_bytes

    with pytest.raises(ValueError):
        canonical_bytes({"x": "a" * 300000})
    deep = {}
    current = deep
    for _ in range(20):
        current["x"] = {}
        current = current["x"]
    with pytest.raises(ValueError):
        canonical_bytes(deep)


def test_benchmark_core_metric_adapter_uses_actual_contract():
    from benchmark_core.models import MetricValue
    from local_inference_optimization.adapters import benchmark_metric

    e = evidence_base()
    e["metrics"] = [
        benchmark_metric(
            "latency", MetricValue(12.5, "ms", "timer", "measured").to_dict()
        )
    ]
    assert validate_evidence(e)["evidence"]["metrics"][0]["quality"] == "measured"


def test_capability_verification_needs_runtime_evidence():
    e = evidence_base()
    e["capabilities"] = [{"name": "mtp", "status": "verified", "source": "offline"}]
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_benchmark_metric_adapter_rejects_invalid_quality_and_values():
    from local_inference_optimization.adapters import benchmark_metric

    with pytest.raises(ValueError):
        benchmark_metric(
            "latency",
            {"value": 10, "unit": "ms", "source": "timer", "quality": "unavailable"},
        )


def test_activation_unknown_is_explicit_and_not_effective():
    e = evidence_base()
    e["activation"] = {"status": "unknown", "source": "offline"}
    result = validate_evidence(e)
    assert result["evidence"]["activation"]["status"] == "unknown"
    assert result["effective"] == {}


def test_activation_cannot_be_verified_from_static_source():
    e = evidence_base()
    e["activation"] = {"status": "verified", "source": "static_config"}
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_metric_rejects_unbounded_integers_cleanly():
    from local_inference_optimization.adapters import benchmark_metric

    with pytest.raises(ValueError):
        benchmark_metric(
            "latency",
            {"value": 10**400, "unit": "ms", "source": "timer", "quality": "measured"},
        )


def test_model_alias_accepts_quantization_selector():
    v = copy.deepcopy(VARIANT)
    v["model"]["alias"] = "qwen/qwen3.8-27b@q6_k"
    assert variant_fingerprint(v)


def test_effective_value_cannot_use_stale_observation():
    e = evidence_base()
    obs = {
        "field": "temperature",
        "stage": "observed",
        "value": 0,
        "status": "verified",
        "source": "backend_runtime",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    e["backend"] = {"identity": "backend", "version": "1"}
    e["artifacts"] = [{"id": "receipt", "sha256": DIGEST}]
    e["observations"] = [
        obs,
        dict(obs, stage="effective", timestamp="2026-01-02T00:00:00Z"),
    ]
    with pytest.raises(ValueError):
        validate_evidence(e)


def test_experiment_dimensions_order_invariant_and_sensitivity():
    e1 = copy.deepcopy(EXPERIMENT)
    e1["dimensions"] = ["temperature", "top_p"]
    e2 = copy.deepcopy(EXPERIMENT)
    e2["dimensions"] = ["top_p", "temperature"]
    assert experiment_fingerprint(e1) == experiment_fingerprint(e2)

    # Change fixed setting
    e3 = copy.deepcopy(e1)
    e3["fixed"]["temperature"] = 0.7
    assert experiment_fingerprint(e1) != experiment_fingerprint(e3)

    # Change task_set sha
    e4 = copy.deepcopy(e1)
    e4["task_set"]["sha256"] = "b" * 64
    assert experiment_fingerprint(e1) != experiment_fingerprint(e4)


def test_unsupported_variant_and_trial_schemas():
    from local_inference_optimization.contracts import validate_trial, validate_variant

    v = copy.deepcopy(VARIANT)
    v["schema"] = "lio-variant-v2"
    with pytest.raises(ValueError, match="unsupported schema"):
        validate_variant(v)

    t = {
        "schema": "lio-trial-v2",
        "experiment_sha256": DIGEST,
        "variant_sha256": DIGEST,
        "run_id": "run1",
        "trial_id": "trial1",
        "task_id": "task1",
        "repetition": 0,
        "evidence_ref": "evidence1",
        "source_revision": "a" * 40,
        "workspace_sha256": DIGEST,
    }
    with pytest.raises(ValueError, match="unsupported schema"):
        validate_trial(t)


def test_missing_required_fields_across_contracts():
    from local_inference_optimization.contracts import (
        validate_experiment,
        validate_trial,
        validate_variant,
    )

    # Missing task_set in experiment
    e = copy.deepcopy(EXPERIMENT)
    del e["task_set"]
    with pytest.raises(ValueError, match="missing or unsupported fields"):
        validate_experiment(e)

    # Missing prompt_policy in variant
    v = copy.deepcopy(VARIANT)
    del v["prompt_policy"]
    with pytest.raises(ValueError, match="missing or unsupported fields"):
        validate_variant(v)

    # Missing trial_id in trial
    t = {
        "schema": "lio-trial-v1",
        "experiment_sha256": DIGEST,
        "variant_sha256": DIGEST,
        "run_id": "run1",
        "task_id": "task1",
        "repetition": 0,
        "evidence_ref": "evidence1",
        "source_revision": "a" * 40,
        "workspace_sha256": DIGEST,
    }
    with pytest.raises(ValueError, match="missing or unsupported fields"):
        validate_trial(t)


def test_sensitive_identifiers_and_paths_rejected():
    from local_inference_optimization.contracts import (
        validate_experiment,
        variant_fingerprint,
    )

    e = copy.deepcopy(EXPERIMENT)
    e["study_id"] = "http://malicious.org"
    with pytest.raises(ValueError, match="invalid or sensitive identifier"):
        validate_experiment(e)

    e["study_id"] = "user:secret@study"
    with pytest.raises(ValueError, match="invalid or sensitive identifier"):
        validate_experiment(e)

    v = copy.deepcopy(VARIANT)
    v["model"]["file_identity"]["file_path"] = "/path/with/user:pass@host/model.gguf"
    with pytest.raises(ValueError, match="invalid or sensitive file path"):
        variant_fingerprint(v)


def test_trial_validation_rules():
    from local_inference_optimization.contracts import validate_trial

    t = {
        "schema": "lio-trial-v1",
        "experiment_sha256": DIGEST,
        "variant_sha256": DIGEST,
        "run_id": "run1",
        "trial_id": "trial1",
        "task_id": "task1",
        "repetition": -1,
        "evidence_ref": "evidence1",
        "source_revision": "a" * 40,
        "workspace_sha256": DIGEST,
    }
    with pytest.raises(ValueError, match="invalid repetition"):
        validate_trial(t)

    t["repetition"] = 0
    t["source_revision"] = "not-a-valid-sha"
    with pytest.raises(ValueError, match="invalid source revision"):
        validate_trial(t)


def test_package_exports():
    import local_inference_optimization as lio

    for name in [
        "benchmark_metric",
        "canonical_bytes",
        "experiment_fingerprint",
        "has_verified_model_digest",
        "legacy_profile_requests",
        "monitor_request_observations",
        "validate_evidence",
        "validate_experiment",
        "validate_model",
        "validate_trial",
        "validate_variant",
        "variant_fingerprint",
    ]:
        assert hasattr(lio, name)
