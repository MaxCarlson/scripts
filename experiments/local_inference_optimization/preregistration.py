"""Versioned offline preregistration and freeze checks for LIO studies.

This additive contract deliberately does not change lio-experiment-v1 or
comparison-conditions-v1. A design may be freeze-ready as a template while an
actual freeze remains blocked by unsealed baseline or unknown runtime identity.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
from typing import Any

from .contracts import MAX_BYTES, canonical_bytes

_SHA = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {
    "adopt",
    "provisional",
    "experimental",
    "unsupported",
    "rejected",
    "superseded",
}


def validate_preregistration(value: object) -> list[str]:
    """Return stable machine-readable validation errors; never invent missing evidence."""
    if not isinstance(value, dict):
        return ["preregistration.not_object"]
    required = {
        "schema",
        "experiment_id",
        "study_class",
        "research_question",
        "hypothesis",
        "primary_endpoint",
        "secondary_endpoints",
        "baseline",
        "models",
        "task_set",
        "repetitions",
        "randomization_seed",
        "pairing",
        "execution",
        "environment",
        "intervention",
        "fixed_conditions",
        "required_evidence_stages",
        "limits",
        "missing_data",
        "exclusions",
        "stopping",
        "multiplicity",
        "adoption_criteria",
        "analysis_plan",
        "decision_statuses",
    }
    if set(value) != required:
        return ["preregistration.fields_invalid"]
    try:
        encoded = canonical_bytes(value)
        if len(encoded) > MAX_BYTES:
            return ["preregistration.too_large"]
    except (TypeError, ValueError):
        return ["preregistration.not_canonical_json"]
    errors: list[str] = []
    if value["schema"] != "lio-preregistration-v1":
        errors.append("preregistration.schema_unsupported")
    if not _bounded_text(value["experiment_id"], 256):
        errors.append("preregistration.experiment_id_invalid")
    if not isinstance(value["study_class"], str) or value["study_class"] not in {
        "between_models",
        "within_model_settings",
    }:
        errors.append("preregistration.study_class_invalid")
    for name in ("research_question", "hypothesis", "primary_endpoint"):
        if not _bounded_text(value[name], 4096):
            errors.append(f"preregistration.{name}_missing")
    if value["primary_endpoint"] != "strict_task_acceptance":
        errors.append("preregistration.primary_endpoint_unsupported")
    if (
        not isinstance(value["secondary_endpoints"], list)
        or len(value["secondary_endpoints"]) > 64
    ):
        errors.append("preregistration.secondary_endpoints_invalid")
    if not isinstance(value["baseline"], dict) or set(value["baseline"]) != {
        "run_id",
        "sealed",
        "fingerprint",
    }:
        errors.append("preregistration.baseline_invalid")
    elif value["baseline"]["run_id"] is not None and not _bounded_text(
        value["baseline"]["run_id"], 256
    ):
        errors.append("preregistration.baseline_run_id_invalid")
    elif (
        value["baseline"]["sealed"] is not None
        and type(value["baseline"]["sealed"]) is not bool
    ):
        errors.append("preregistration.baseline_seal_invalid")
    elif value["baseline"]["fingerprint"] is not None and not _valid_sha(
        value["baseline"]["fingerprint"]
    ):
        errors.append("preregistration.baseline_fingerprint_invalid")
    models = value["models"]
    if not isinstance(models, list) or not 2 <= len(models) <= 16:
        errors.append("preregistration.models_invalid")
    else:
        condition_ids = []
        for model in models:
            if (
                not isinstance(model, dict)
                or set(model)
                != {
                    "condition_id",
                    "content_sha256",
                    "quantization",
                    "identity_quality",
                }
                or not _bounded_text(model.get("condition_id"), 128)
                or not isinstance(model.get("identity_quality"), str)
                or model.get("identity_quality") not in {"verified", "weak", "unknown"}
                or (
                    model.get("content_sha256") is not None
                    and not _valid_sha(model["content_sha256"])
                )
                or (
                    model.get("quantization") is not None
                    and not _bounded_text(model["quantization"], 256)
                )
            ):
                errors.append("preregistration.model_identity_invalid")
                break
            condition_ids.append(model["condition_id"])
        if len(condition_ids) != len(set(condition_ids)):
            errors.append("preregistration.model_condition_ids_duplicate")
    tasks = value["task_set"]
    if not isinstance(tasks, dict) or set(tasks) != {
        "task_ids",
        "task_sha256",
        "verifier_sha256",
    }:
        errors.append("preregistration.task_set_invalid")
    else:
        ids = tasks["task_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 256
            or any(not _bounded_text(item, 256) for item in ids)
            or len(set(ids)) != len(ids)
        ):
            errors.append("preregistration.task_ids_invalid")
        for field in ("task_sha256", "verifier_sha256"):
            if (
                not isinstance(tasks[field], dict)
                or set(tasks[field]) != set(ids)
                or any(not _valid_sha(digest) for digest in tasks[field].values())
            ):
                errors.append(f"preregistration.{field}_invalid")
    if type(value["repetitions"]) is not int or not 1 <= value["repetitions"] <= 1000:
        errors.append("preregistration.repetitions_invalid")
    if (
        type(value["randomization_seed"]) is not int
        or not 0 <= value["randomization_seed"] < 2**63
    ):
        errors.append("preregistration.seed_invalid")
    for field in (
        "pairing",
        "execution",
        "environment",
        "intervention",
        "fixed_conditions",
        "limits",
        "missing_data",
        "exclusions",
        "stopping",
        "multiplicity",
        "adoption_criteria",
        "analysis_plan",
    ):
        if not isinstance(value[field], dict) or not value[field]:
            errors.append(f"preregistration.{field}_invalid")
    nested_required = {
        "pairing": {"unit", "block", "order"},
        "execution": {"order", "warm_cold"},
        "environment": {"instrumentation"},
        "intervention": {"target", "allowed_differences"},
        "limits": {"task_timeout_seconds", "resource_limits"},
        "missing_data": {"infrastructure", "unscored"},
        "exclusions": {"predeclared"},
        "stopping": {"rule"},
        "multiplicity": {"confirmatory", "family_id", "method"},
        "adoption_criteria": {
            "quality_noninferiority",
            "minimum_independent_tasks",
            "review_required",
        },
        "analysis_plan": {"method", "interval", "cluster_unit"},
    }
    for field, keys in nested_required.items():
        if isinstance(value[field], dict) and not keys.issubset(value[field]):
            errors.append(f"preregistration.{field}_fields_missing")
    for field, keys in {
        "pairing": ("unit", "block", "order"),
        "execution": ("order", "warm_cold"),
        "stopping": ("rule",),
        "analysis_plan": ("method", "interval", "cluster_unit"),
    }.items():
        if isinstance(value[field], dict) and any(
            not _bounded_text(value[field].get(key), 256) for key in keys
        ):
            errors.append(f"preregistration.{field}_values_invalid")
    intervention = value["intervention"]
    if isinstance(intervention, dict) and "allowed_differences" in intervention:
        allowed = intervention["allowed_differences"]
        if (
            not isinstance(allowed, list)
            or not allowed
            or any(not _bounded_text(item, 256) for item in allowed)
        ):
            errors.append("preregistration.allowed_differences_invalid")
    limits = value["limits"]
    if isinstance(limits, dict) and "task_timeout_seconds" in limits:
        timeout = limits["task_timeout_seconds"]
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            errors.append("preregistration.task_timeout_invalid")
        resources = limits.get("resource_limits")
        if (
            not isinstance(resources, dict)
            or not resources
            or any(
                not isinstance(n, (int, float))
                or isinstance(n, bool)
                or not math.isfinite(n)
                or n <= 0
                for n in resources.values()
            )
        ):
            errors.append("preregistration.resource_limits_invalid")
    adoption = value["adoption_criteria"]
    if (
        isinstance(adoption, dict)
        and {"quality_noninferiority", "minimum_independent_tasks", "review_required"}
        <= adoption.keys()
    ):
        margin, minimum, review = (
            adoption["quality_noninferiority"],
            adoption["minimum_independent_tasks"],
            adoption["review_required"],
        )
        if (
            not isinstance(margin, (int, float))
            or isinstance(margin, bool)
            or not math.isfinite(margin)
            or margin < 0
            or margin > 1
            or type(minimum) is not int
            or minimum < 1
            or type(review) is not bool
        ):
            errors.append("preregistration.adoption_criteria_invalid")
    multiplicity = value["multiplicity"]
    if (
        isinstance(multiplicity, dict)
        and {"confirmatory", "family_id", "method"} <= multiplicity.keys()
    ):
        if (
            type(multiplicity["confirmatory"]) is not bool
            or not isinstance(multiplicity["method"], str)
            or multiplicity["method"] not in {"holm", "none", "exploratory"}
            or (
                multiplicity["confirmatory"]
                and not _bounded_text(multiplicity["family_id"], 256)
            )
        ):
            errors.append("preregistration.multiplicity_invalid")
    if not isinstance(value["required_evidence_stages"], list) or any(
        not isinstance(item, str)
        or item not in {"requested", "planned", "observed", "effective"}
        for item in value["required_evidence_stages"]
    ):
        errors.append("preregistration.evidence_stages_invalid")
    elif not {"observed", "effective"}.issubset(value["required_evidence_stages"]):
        errors.append("preregistration.observed_effective_evidence_required")
    if value["decision_statuses"] != sorted(_STATUSES):
        errors.append("preregistration.decision_statuses_invalid")
    if value["study_class"] == "between_models" and not isinstance(
        value["intervention"], dict
    ):
        errors.append("preregistration.model_intervention_required")
    if value["study_class"] == "between_models" and isinstance(
        value["intervention"], dict
    ):
        if value["intervention"].get("target") != "model_identity" or not value[
            "intervention"
        ].get("allowed_differences"):
            errors.append("preregistration.model_intervention_not_declared")
    if (
        value["study_class"] == "within_model_settings"
        and isinstance(models, list)
        and len(models) >= 2
    ):
        identities = [m.get("content_sha256") for m in models if isinstance(m, dict)]
        if (
            len(identities) != len(models)
            or not identities
            or not all(_valid_sha(x) for x in identities)
            or any(x != identities[0] for x in identities[1:])
            or any(
                m.get("identity_quality") != "verified"
                for m in models
                if isinstance(m, dict)
            )
        ):
            errors.append("preregistration.within_model_identity_not_fixed")
        quantizations = [m.get("quantization") for m in models if isinstance(m, dict)]
        if len(quantizations) != len(models) or any(
            q != quantizations[0] for q in quantizations[1:]
        ):
            errors.append("preregistration.within_model_quantization_changed")
        if (
            not isinstance(value["intervention"], dict)
            or value["intervention"].get("target") != "model_settings"
            or not value["intervention"].get("allowed_differences")
        ):
            errors.append("preregistration.settings_intervention_not_declared")
    return errors


def preregistration_fingerprint(value: object) -> str:
    errors = validate_preregistration(value)
    if errors:
        raise ValueError(",".join(errors))
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def serialize_preregistration(value: object) -> bytes:
    """Return bounded canonical JSON bytes for archival and transport."""
    errors = validate_preregistration(value)
    if errors:
        raise ValueError(",".join(errors))
    return canonical_bytes(value)


def deserialize_preregistration(payload: bytes | str) -> dict[str, Any]:
    """Load a bounded preregistration and reject duplicate JSON object keys."""
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        raw = payload
    else:
        raise ValueError("preregistration.payload_invalid")
    if len(raw) > MAX_BYTES:
        raise ValueError("preregistration.too_large")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("preregistration.duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("preregistration.json_invalid") from exc
    errors = validate_preregistration(value)
    if errors:
        raise ValueError(",".join(errors))
    return value


def randomized_execution_order(
    task_ids: list[str], condition_ids: list[str], repetitions: int, seed: int
) -> list[dict[str, Any]]:
    """Create deterministic randomized task/repetition blocks and arm order."""
    if (
        not isinstance(task_ids, list)
        or not isinstance(condition_ids, list)
        or not task_ids
        or not condition_ids
        or any(not _bounded_text(item, 256) for item in task_ids)
        or any(not _bounded_text(item, 256) for item in condition_ids)
        or len(set(task_ids)) != len(task_ids)
        or len(set(condition_ids)) != len(condition_ids)
        or type(repetitions) is not int
        or repetitions < 1
        or type(seed) is not int
        or not 0 <= seed < 2**63
    ):
        raise ValueError("randomization.design_invalid")
    blocks = [
        {"task_id": task, "repetition": repetition}
        for task in task_ids
        for repetition in range(repetitions)
    ]
    if len(blocks) * len(condition_ids) > 8192:
        raise ValueError("randomization.design_too_large")
    rng = random.Random(seed)
    rng.shuffle(blocks)
    schedule = []
    for block in blocks:
        order = list(condition_ids)
        rng.shuffle(order)
        schedule.append({**block, "condition_order": order})
    return [{**item, "sequence_index": index} for index, item in enumerate(schedule)]


def freeze_readiness(value: object) -> dict[str, Any]:
    """Distinguish a well-formed template from an actually frozen study."""
    errors = validate_preregistration(value)
    if errors:
        return {"state": "invalid", "reason_codes": errors, "fingerprint": None}
    assert isinstance(value, dict)
    fp = preregistration_fingerprint(value)
    missing = []
    if (
        value["baseline"]["sealed"] is not True
        or not value["baseline"]["run_id"]
        or not value["baseline"]["fingerprint"]
    ):
        missing.append("baseline.unsealed_or_unidentified")
    if any(
        m["identity_quality"] != "verified"
        or not m["content_sha256"]
        or not m["quantization"]
        for m in value["models"]
    ):
        missing.append("model.identity_or_quantization_unverified")
    if value["study_class"] == "between_models":
        identity_pairs = {
            (m["content_sha256"], m["quantization"]) for m in value["models"]
        }
        if len(identity_pairs) != len(value["models"]):
            missing.append("model.between_model_intervention_not_distinct")
    if (
        "instrumentation" not in value["environment"]
        or not _established_tree(value["environment"])
        or not _established_tree(value["fixed_conditions"])
    ):
        missing.append("conditions.runtime_or_fixed_identity_missing")
    return {
        "state": "freeze_ready" if not missing else "template_ready_blocked",
        "reason_codes": missing,
        "fingerprint": fp,
    }


def freeze_preregistration(value: object) -> dict[str, Any]:
    readiness = freeze_readiness(value)
    if readiness["state"] != "freeze_ready":
        raise ValueError(
            ",".join(readiness["reason_codes"]) or "preregistration.invalid"
        )
    return {
        "schema": "lio-frozen-preregistration-v1",
        "design": copy.deepcopy(value),
        "design_sha256": readiness["fingerprint"],
    }


def check_result_set_matches_frozen(frozen: object, results: object) -> list[str]:
    """Check immutable design identity against run descriptors before analysis."""
    if (
        not isinstance(frozen, dict)
        or set(frozen) != {"schema", "design", "design_sha256"}
        or frozen.get("schema") != "lio-frozen-preregistration-v1"
    ):
        return ["results.frozen_design_invalid"]
    design = frozen["design"]
    if (
        validate_preregistration(design)
        or preregistration_fingerprint(design) != frozen["design_sha256"]
    ):
        return ["results.frozen_design_drift"]
    if not isinstance(results, dict):
        return ["results.descriptor_invalid"]
    errors = []
    if results.get("design_sha256") != frozen["design_sha256"]:
        errors.append("results.design_fingerprint_mismatch")
    if results.get("task_ids") != design["task_set"]["task_ids"]:
        errors.append("results.task_set_mismatch")
    if results.get("randomization_seed") != design["randomization_seed"]:
        errors.append("results.randomization_seed_mismatch")
    if results.get("repetitions") != design["repetitions"]:
        errors.append("results.repetition_plan_mismatch")
    for field in ("baseline", "environment", "fixed_conditions", "intervention"):
        if results.get(field) != design[field]:
            errors.append(f"results.{field}_mismatch")
    for field in ("task_sha256", "verifier_sha256"):
        if results.get(field) != design["task_set"][field]:
            errors.append(f"results.{field}_mismatch")
    expected_models = [
        {key: model[key] for key in ("condition_id", "content_sha256", "quantization")}
        for model in design["models"]
    ]
    if results.get("model_identities") != expected_models:
        errors.append("results.model_identity_mismatch")
    return errors


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _bounded_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value.strip()) <= maximum
        and "\x00" not in value
    )


def _established_tree(value: object) -> bool:
    if isinstance(value, dict):
        return bool(value) and all(
            _bounded_text(key, 256) and _established_tree(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return bool(value) and all(_established_tree(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in {
            "unknown",
            "unverified",
            "pending",
            "unavailable",
            "tbd",
        }
    return value is not None and type(value) in {bool, int, float}
