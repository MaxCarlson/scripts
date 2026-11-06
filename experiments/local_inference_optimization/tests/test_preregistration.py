import copy

import pytest

from experiments.local_inference_optimization.preregistration import (
    check_result_set_matches_frozen,
    deserialize_preregistration,
    freeze_readiness,
    preregistration_fingerprint,
    randomized_execution_order,
    serialize_preregistration,
    validate_preregistration,
)


def design():
    digest = "a" * 64
    return {
        "schema": "lio-preregistration-v1",
        "experiment_id": "demo-synthetic",
        "study_class": "between_models",
        "research_question": "Synthetic comparison",
        "hypothesis": "No measured claim",
        "primary_endpoint": "strict_task_acceptance",
        "secondary_endpoints": ["duration.wall_ms"],
        "baseline": {"run_id": None, "sealed": None, "fingerprint": None},
        "models": [
            {
                "condition_id": "A",
                "content_sha256": None,
                "quantization": None,
                "identity_quality": "unknown",
            },
            {
                "condition_id": "B",
                "content_sha256": None,
                "quantization": None,
                "identity_quality": "unknown",
            },
        ],
        "task_set": {
            "task_ids": ["task-1"],
            "task_sha256": {"task-1": digest},
            "verifier_sha256": {"task-1": digest},
        },
        "repetitions": 1,
        "randomization_seed": 9,
        "pairing": {
            "unit": "task_repetition",
            "block": "task_id",
            "order": "randomized",
        },
        "execution": {"order": "counterbalanced", "warm_cold": "declared_per_block"},
        "environment": {"host_fingerprint": "unknown", "instrumentation": "unknown"},
        "intervention": {
            "target": "model_identity",
            "allowed_differences": ["model_identity", "quantization"],
        },
        "fixed_conditions": {"prompt_policy": "unknown"},
        "required_evidence_stages": ["observed", "effective"],
        "limits": {"task_timeout_seconds": 60, "resource_limits": {"cpu_seconds": 120}},
        "missing_data": {
            "infrastructure": "exclude_from_scored_denominator",
            "unscored": "retain_diagnostic",
        },
        "exclusions": {"predeclared": []},
        "stopping": {"rule": "fixed_repetitions"},
        "multiplicity": {
            "family_id": "confirmatory-1",
            "method": "holm",
            "confirmatory": True,
        },
        "adoption_criteria": {
            "quality_noninferiority": 0.0,
            "minimum_independent_tasks": 10,
            "review_required": True,
        },
        "analysis_plan": {
            "method": "task_cluster_bootstrap",
            "interval": "percentile_95",
            "cluster_unit": "task_id",
            "seed": 9,
        },
        "decision_statuses": [
            "adopt",
            "experimental",
            "provisional",
            "rejected",
            "superseded",
            "unsupported",
        ],
    }


def test_template_ready_but_baseline_not_invented_and_fingerprint_stable():
    value = design()
    assert validate_preregistration(value) == []
    assert preregistration_fingerprint(value) == preregistration_fingerprint(
        copy.deepcopy(value)
    )
    ready = freeze_readiness(value)
    assert ready["state"] == "template_ready_blocked"
    assert "baseline.unsealed_or_unidentified" in ready["reason_codes"]


def test_fingerprint_detects_design_drift_and_result_mismatch():
    value = design()
    frozen = {
        "schema": "lio-frozen-preregistration-v1",
        "design": value,
        "design_sha256": preregistration_fingerprint(value),
    }
    results = {
        "design_sha256": "b" * 64,
        "task_ids": ["task-1"],
        "randomization_seed": 9,
        "repetitions": 1,
        "task_sha256": value["task_set"]["task_sha256"],
        "verifier_sha256": value["task_set"]["verifier_sha256"],
        "model_identities": [
            {
                key: model[key]
                for key in ("condition_id", "content_sha256", "quantization")
            }
            for model in value["models"]
        ],
        "baseline": value["baseline"],
        "environment": value["environment"],
        "fixed_conditions": value["fixed_conditions"],
        "intervention": value["intervention"],
    }
    assert check_result_set_matches_frozen(frozen, results) == [
        "results.design_fingerprint_mismatch"
    ]
    frozen["design"]["research_question"] = "drift"
    assert check_result_set_matches_frozen(frozen, results) == [
        "results.frozen_design_drift"
    ]


def test_rejects_missing_digests_and_unsupported_fields():
    value = design()
    value["task_set"]["task_sha256"]["task-1"] = "unknown"
    assert "preregistration.task_sha256_invalid" in validate_preregistration(value)
    value["extra"] = True
    assert "preregistration.fields_invalid" in validate_preregistration(value)


def test_fully_identified_design_can_freeze_and_validate_results():
    value = design()
    value["baseline"] = {
        "run_id": "p02-reference",
        "sealed": True,
        "fingerprint": "c" * 64,
    }
    for model in value["models"]:
        model.update(
            content_sha256=("d" if model["condition_id"] == "A" else "e") * 64,
            quantization="Q4_K_M",
            identity_quality="verified",
        )
    value["environment"] = {
        "host_fingerprint": "synthetic-host",
        "instrumentation": "synthetic-monitor-v1",
    }
    value["fixed_conditions"] = {
        "prompt_policy_sha256": "f" * 64,
        "tool_policy_sha256": "a" * 64,
    }
    assert freeze_readiness(value)["state"] == "freeze_ready"
    frozen = {
        "schema": "lio-frozen-preregistration-v1",
        "design": value,
        "design_sha256": preregistration_fingerprint(value),
    }
    descriptor = {
        "design_sha256": frozen["design_sha256"],
        "task_ids": ["task-1"],
        "randomization_seed": 9,
        "repetitions": 1,
        "task_sha256": value["task_set"]["task_sha256"],
        "verifier_sha256": value["task_set"]["verifier_sha256"],
        "model_identities": [
            {
                key: model[key]
                for key in ("condition_id", "content_sha256", "quantization")
            }
            for model in value["models"]
        ],
        "baseline": value["baseline"],
        "environment": value["environment"],
        "fixed_conditions": value["fixed_conditions"],
        "intervention": value["intervention"],
    }
    assert check_result_set_matches_frozen(frozen, descriptor) == []
    descriptor["task_ids"] = ["different-task"]
    assert "results.task_set_mismatch" in check_result_set_matches_frozen(
        frozen, descriptor
    )


def test_within_model_settings_study_requires_same_verified_model_identity():
    value = design()
    value["study_class"] = "within_model_settings"
    value["intervention"] = {
        "target": "model_settings",
        "allowed_differences": ["temperature"],
    }
    value["models"][0].update(
        content_sha256="d" * 64, quantization="Q4_K_M", identity_quality="verified"
    )
    value["models"][1].update(
        content_sha256="e" * 64, quantization="Q4_K_M", identity_quality="verified"
    )
    assert (
        "preregistration.within_model_identity_not_fixed"
        in validate_preregistration(value)
    )


def test_canonical_serialize_round_trip_and_duplicate_key_rejection():
    value = design()
    encoded = serialize_preregistration(value)
    assert deserialize_preregistration(encoded) == value
    with pytest.raises(ValueError, match="duplicate_json_key"):
        deserialize_preregistration('{"duplicate":1,"duplicate":2}')


def test_randomized_execution_order_is_seed_reproducible():
    first = randomized_execution_order(["a", "b", "c"], ["base", "candidate"], 2, 41)
    second = randomized_execution_order(["a", "b", "c"], ["base", "candidate"], 2, 41)
    assert first == second
    assert len(first) == 6
    assert {tuple(row["condition_order"]) for row in first} <= {
        ("base", "candidate"),
        ("candidate", "base"),
    }
