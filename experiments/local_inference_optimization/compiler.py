"""Deterministic configuration compiler and backend parameter mapping (P06)."""

from __future__ import annotations

import hashlib
from typing import Any

from .contracts import (
    MAX_ITEMS,
    _id,
    _mapping,
    _sha,
    _version,
    canonical_bytes,
    validate_model,
    validate_variant,
    variant_fingerprint,
)
from .registry import FeatureRegistry

PLAN_SCHEMA = "lio-plan-v1"
SUPPORTED_API_TYPES = {"lmstudio_rest_v1", "lmstudio_openai_v1", "opencode_v1"}


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    _mapping(
        plan,
        (
            "schema",
            "plan_id",
            "variant_sha256",
            "target_model",
            "backend",
            "status",
            "reload_required",
            "load_operations",
            "request_operations",
            "resource_delta",
            "blockers",
            "evidence_records",
            "plan_sha256",
        ),
    )
    _version(plan["schema"], PLAN_SCHEMA)
    _id(plan["plan_id"])
    _sha(plan["variant_sha256"])
    validate_model(plan["target_model"])

    backend = plan["backend"]
    _mapping(backend, ("identity", "version", "api_type"))
    _id(backend["identity"])
    _id(backend["version"])
    if backend["api_type"] not in SUPPORTED_API_TYPES:
        raise ValueError(f"unsupported backend api_type: {backend['api_type']!r}")

    status = plan["status"]
    if status not in {"compiled", "unsupported", "rejected"}:
        raise ValueError(f"invalid plan status: {status!r}")

    if not isinstance(plan["reload_required"], bool):
        raise ValueError("reload_required must be a boolean")

    for op_list_key in ("load_operations", "request_operations"):
        op_list = plan[op_list_key]
        if not isinstance(op_list, list) or len(op_list) > MAX_ITEMS:
            raise ValueError(f"invalid {op_list_key} list")
        for op in op_list:
            _mapping(op, ("target", "field", "value", "stage"))
            _id(op["target"])
            _id(op["field"])
            if op["stage"] != "planned":
                raise ValueError(
                    "all compiled plan operations must have stage 'planned'"
                )

    res_delta = plan["resource_delta"]
    _mapping(res_delta, ("vram_bytes_estimated", "uncertainty"))
    if res_delta["uncertainty"] not in {"measured", "estimated", "unknown"}:
        raise ValueError("invalid resource_delta uncertainty")

    blockers = plan["blockers"]
    if not isinstance(blockers, list) or len(blockers) > MAX_ITEMS:
        raise ValueError("invalid blockers list")
    for b in blockers:
        if not isinstance(b, str) or not b:
            raise ValueError("invalid blocker description")

    evidence = plan["evidence_records"]
    if not isinstance(evidence, list) or len(evidence) > MAX_ITEMS:
        raise ValueError("invalid evidence_records list")
    for ev in evidence:
        _mapping(ev, ("field", "stage", "value", "status", "source"))
        if ev["stage"] not in {"requested", "planned"}:
            raise ValueError(
                "plan evidence records can only be 'requested' or 'planned'"
            )
        if ev["stage"] == "effective":
            raise ValueError("compiler plan must NEVER emit 'effective' evidence")

    _sha(plan["plan_sha256"])

    # Verify plan_sha256 matches canonical bytes of plan excluding plan_sha256
    plan_copy = {k: v for k, v in plan.items() if k != "plan_sha256"}
    expected_hash = hashlib.sha256(canonical_bytes(plan_copy)).hexdigest()
    if plan["plan_sha256"] != expected_hash:
        raise ValueError(
            f"plan_sha256 mismatch: expected {expected_hash}, got {plan['plan_sha256']}"
        )

    return plan


def compile_plan(
    variant: dict[str, Any],
    backend_info: dict[str, Any],
    backend_capabilities: list[dict[str, Any]] | None = None,
    registry: FeatureRegistry | None = None,
    timestamp: str = "2026-11-02T00:00:00Z",
) -> dict[str, Any]:
    """Deterministically compile a variant configuration into a non-mutating plan (P06)."""
    validate_variant(variant)
    _mapping(backend_info, ("identity", "version", "api_type"))
    _id(backend_info["identity"])
    _id(backend_info["version"])
    api_type = backend_info["api_type"]
    if api_type not in SUPPORTED_API_TYPES:
        raise ValueError(f"unsupported backend api_type: {api_type!r}")

    if registry is None:
        registry = FeatureRegistry(include_defaults=True)

    backend_capabilities = backend_capabilities or []
    cap_status_map: dict[str, str] = {}
    for cap in backend_capabilities:
        if isinstance(cap, dict) and "name" in cap and "status" in cap:
            cap_status_map[cap["name"]] = cap["status"]

    # 1. Gather all requested settings from variant
    requested_settings: dict[str, Any] = {
        "context": variant["context"],
        "output_limit": variant["output_limit"],
        "reasoning": variant["reasoning"],
    }
    for k, v in variant.get("sampling", {}).items():
        requested_settings[k] = v
    for k, v in variant.get("features", {}).items():
        requested_settings[k] = v

    # 2. Validate against registry constraints (bounds, types, dependencies, conflicts)
    registry.validate_settings(requested_settings)

    # 3. Capability gating
    required_caps = registry.get_required_capabilities(requested_settings)
    blockers: list[str] = []
    plan_status = "compiled"

    for cap_name in required_caps:
        cap_status = cap_status_map.get(cap_name, "unknown")
        if cap_status == "unknown":
            blockers.append(
                f"capability_unknown: backend capability {cap_name!r} status is unknown"
            )
            if plan_status != "unsupported":
                plan_status = "rejected"
        elif cap_status == "unsupported":
            blockers.append(
                f"capability_unsupported: backend does not support capability {cap_name!r}"
            )
            plan_status = "unsupported"

    # 4. Deterministic Backend Mapping
    load_ops: list[dict[str, Any]] = []
    request_ops: list[dict[str, Any]] = []

    model_alias = variant["model"]["alias"]

    if api_type in {"lmstudio_rest_v1", "lmstudio_openai_v1"}:
        # LM Studio model load operations
        load_ops.append(
            {
                "target": "lmstudio_load",
                "field": "model",
                "value": model_alias,
                "stage": "planned",
            }
        )
        load_ops.append(
            {
                "target": "lmstudio_load",
                "field": "echo_load_config",
                "value": True,
                "stage": "planned",
            }
        )
        load_ops.append(
            {
                "target": "lmstudio_load",
                "field": "context_length",
                "value": requested_settings["context"],
                "stage": "planned",
            }
        )
        if "batch_size" in requested_settings:
            load_ops.append(
                {
                    "target": "lmstudio_load",
                    "field": "eval_batch_size",
                    "value": requested_settings["batch_size"],
                    "stage": "planned",
                }
            )
        if "flash_attention" in requested_settings:
            load_ops.append(
                {
                    "target": "lmstudio_load",
                    "field": "flash_attention",
                    "value": requested_settings["flash_attention"],
                    "stage": "planned",
                }
            )
        if "gpu_kv_cache" in requested_settings:
            load_ops.append(
                {
                    "target": "lmstudio_load",
                    "field": "offload_kv_cache_to_gpu",
                    "value": requested_settings["gpu_kv_cache"],
                    "stage": "planned",
                }
            )
        if (
            "speculation_mode" in requested_settings
            and requested_settings["speculation_mode"] != "off"
        ):
            load_ops.append(
                {
                    "target": "lmstudio_load",
                    "field": "speculation_mode",
                    "value": requested_settings["speculation_mode"],
                    "stage": "planned",
                }
            )
        if "max_draft_tokens" in requested_settings:
            load_ops.append(
                {
                    "target": "lmstudio_load",
                    "field": "max_draft_tokens",
                    "value": requested_settings["max_draft_tokens"],
                    "stage": "planned",
                }
            )

        # Request operations: native chat vs openai completions
        if api_type == "lmstudio_rest_v1":
            target_chat = "lmstudio_chat"
            request_ops.append(
                {
                    "target": target_chat,
                    "field": "max_output_tokens",
                    "value": requested_settings["output_limit"],
                    "stage": "planned",
                }
            )
        else:
            target_chat = "openai_chat"
            request_ops.append(
                {
                    "target": target_chat,
                    "field": "max_tokens",
                    "value": requested_settings["output_limit"],
                    "stage": "planned",
                }
            )

        if "temperature" in requested_settings:
            request_ops.append(
                {
                    "target": target_chat,
                    "field": "temperature",
                    "value": requested_settings["temperature"],
                    "stage": "planned",
                }
            )
        if "top_p" in requested_settings:
            request_ops.append(
                {
                    "target": target_chat,
                    "field": "top_p",
                    "value": requested_settings["top_p"],
                    "stage": "planned",
                }
            )
        if "top_k" in requested_settings:
            request_ops.append(
                {
                    "target": target_chat,
                    "field": "top_k",
                    "value": requested_settings["top_k"],
                    "stage": "planned",
                }
            )
        if requested_settings.get("reasoning") != "off":
            request_ops.append(
                {
                    "target": target_chat,
                    "field": "reasoning_effort",
                    "value": requested_settings["reasoning"],
                    "stage": "planned",
                }
            )

    elif api_type == "opencode_v1":
        # OpenCode provider/model layer mapping
        load_ops.append(
            {
                "target": "opencode_provider",
                "field": "model",
                "value": model_alias,
                "stage": "planned",
            }
        )
        request_ops.append(
            {
                "target": "opencode_model",
                "field": "context_length",
                "value": requested_settings["context"],
                "stage": "planned",
            }
        )
        request_ops.append(
            {
                "target": "opencode_model",
                "field": "output_limit",
                "value": requested_settings["output_limit"],
                "stage": "planned",
            }
        )
        if requested_settings.get("reasoning") != "off":
            request_ops.append(
                {
                    "target": "opencode_model",
                    "field": "reasoning",
                    "value": requested_settings["reasoning"],
                    "stage": "planned",
                }
            )
        if "temperature" in requested_settings:
            request_ops.append(
                {
                    "target": "opencode_model",
                    "field": "temperature",
                    "value": requested_settings["temperature"],
                    "stage": "planned",
                }
            )

    # Deterministic sorting
    load_ops.sort(key=lambda op: (op["target"], op["field"]))
    request_ops.sort(key=lambda op: (op["target"], op["field"]))
    blockers.sort()

    reload_required = registry.requires_reload(requested_settings)

    # 5. Build Evidence Records (requested and planned only, NEVER effective)
    evidence_records: list[dict[str, Any]] = []
    for k, v in sorted(requested_settings.items()):
        evidence_records.append(
            {
                "field": k,
                "stage": "requested",
                "value": v,
                "status": "reported",
                "source": "variant_config",
            }
        )
        evidence_records.append(
            {
                "field": k,
                "stage": "planned",
                "value": v,
                "status": "reported",
                "source": "configuration_compiler",
            }
        )

    v_sha = variant_fingerprint(variant)
    plan_body = {
        "schema": PLAN_SCHEMA,
        "plan_id": f"plan-{v_sha[:16]}-{backend_info['api_type']}",
        "variant_sha256": v_sha,
        "target_model": variant["model"],
        "backend": backend_info,
        "status": plan_status,
        "reload_required": reload_required,
        "load_operations": load_ops,
        "request_operations": request_ops,
        "resource_delta": {
            "vram_bytes_estimated": None,
            "uncertainty": "unknown",
        },
        "blockers": blockers,
        "evidence_records": evidence_records,
    }

    # Compute canonical plan fingerprint
    plan_hash = hashlib.sha256(canonical_bytes(plan_body)).hexdigest()
    plan_body["plan_sha256"] = plan_hash

    return validate_plan(plan_body)


def is_baseline_equivalent(
    plan: dict[str, Any],
    baseline_variant: dict[str, Any] | None,
) -> dict[str, Any]:
    """Check if a compiled plan is semantically identical to baseline (no-op check)."""
    if baseline_variant is None:
        return {
            "equivalent": False,
            "missing_baseline": True,
            "deltas": [],
            "reason": "missing baseline reference evidence",
        }

    validate_plan(plan)
    validate_variant(baseline_variant)

    baseline_settings: dict[str, Any] = {
        "context": baseline_variant["context"],
        "output_limit": baseline_variant["output_limit"],
        "reasoning": baseline_variant["reasoning"],
    }
    for k, v in baseline_variant.get("sampling", {}).items():
        baseline_settings[k] = v
    for k, v in baseline_variant.get("features", {}).items():
        baseline_settings[k] = v

    deltas: list[dict[str, Any]] = []
    for ev in plan["evidence_records"]:
        if ev["stage"] == "planned":
            field = ev["field"]
            val = ev["value"]
            base_val = baseline_settings.get(field)
            if val != base_val:
                deltas.append(
                    {
                        "field": field,
                        "planned_value": val,
                        "baseline_value": base_val,
                    }
                )

    deltas.sort(key=lambda d: d["field"])
    return {
        "equivalent": len(deltas) == 0,
        "missing_baseline": False,
        "deltas": deltas,
        "reason": "plan is identical to baseline"
        if not deltas
        else "plan introduces non-baseline settings",
    }
