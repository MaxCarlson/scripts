"""Offline identity, provenance, registry, and compiler contracts for local inference experiments."""

from .adapters import (
    benchmark_metric,
    legacy_profile_requests,
    monitor_request_observations,
)
from .apply import (
    RECEIPT_SCHEMA,
    apply_plan_to_target,
    rollback_transaction,
    validate_receipt,
)
from .compiler import (
    PLAN_SCHEMA,
    SUPPORTED_API_TYPES,
    compile_plan,
    is_baseline_equivalent,
    validate_plan,
)
from .contracts import (
    canonical_bytes,
    experiment_fingerprint,
    has_verified_model_digest,
    validate_evidence,
    validate_experiment,
    validate_model,
    validate_trial,
    validate_variant,
    variant_fingerprint,
)
from .preregistration import (
    check_result_set_matches_frozen,
    deserialize_preregistration,
    freeze_preregistration,
    freeze_readiness,
    preregistration_fingerprint,
    randomized_execution_order,
    serialize_preregistration,
    validate_preregistration,
)
from .registry import (
    FEATURE_DEF_SCHEMA,
    STANDARD_FEATURES,
    FeatureRegistry,
    validate_feature_def,
)

__all__ = [
    "FEATURE_DEF_SCHEMA",
    "PLAN_SCHEMA",
    "RECEIPT_SCHEMA",
    "STANDARD_FEATURES",
    "SUPPORTED_API_TYPES",
    "FeatureRegistry",
    "apply_plan_to_target",
    "benchmark_metric",
    "canonical_bytes",
    "compile_plan",
    "check_result_set_matches_frozen",
    "deserialize_preregistration",
    "experiment_fingerprint",
    "freeze_preregistration",
    "freeze_readiness",
    "has_verified_model_digest",
    "is_baseline_equivalent",
    "legacy_profile_requests",
    "monitor_request_observations",
    "preregistration_fingerprint",
    "randomized_execution_order",
    "rollback_transaction",
    "serialize_preregistration",
    "validate_evidence",
    "validate_experiment",
    "validate_feature_def",
    "validate_model",
    "validate_plan",
    "validate_preregistration",
    "validate_receipt",
    "validate_trial",
    "validate_variant",
    "variant_fingerprint",
]
