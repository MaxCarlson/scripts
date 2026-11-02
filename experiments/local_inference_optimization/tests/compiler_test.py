import copy
import hashlib
import pytest

from local_inference_optimization.compiler import (
    compile_plan,
    is_baseline_equivalent,
    validate_plan,
)
from local_inference_optimization.contracts import canonical_bytes

DIGEST = "a" * 64
SAMPLE_VARIANT = {
    "schema": "lio-variant-v1",
    "model": {
        "alias": "qwen2.5-coder-7b",
        "file_identity": {"status": "weak", "size_bytes": 4800000000, "sha256": None},
        "quantization": "q4_k_m",
    },
    "context": 8192,
    "output_limit": 2048,
    "reasoning": "off",
    "sampling": {"temperature": 0.2, "top_p": 0.9},
    "features": {"flash_attention": True},
    "prompt_policy": "strict-v1",
    "config_sha256": DIGEST,
}

BACKEND_LMSTUDIO_REST = {
    "identity": "lmstudio",
    "version": "0.3.0",
    "api_type": "lmstudio_rest_v1",
}

BACKEND_LMSTUDIO_OPENAI = {
    "identity": "lmstudio",
    "version": "0.3.0",
    "api_type": "lmstudio_openai_v1",
}


def test_deterministic_plan_fingerprint():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan1 = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    plan2 = compile_plan(
        copy.deepcopy(SAMPLE_VARIANT),
        copy.deepcopy(BACKEND_LMSTUDIO_REST),
        backend_capabilities=copy.deepcopy(caps),
    )

    assert plan1["plan_sha256"] == plan2["plan_sha256"]
    assert plan1["status"] == "compiled"
    assert plan1["reload_required"] is True


def test_controlled_feature_changes_alter_plan_hash():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan1 = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )

    var2 = copy.deepcopy(SAMPLE_VARIANT)
    var2["context"] = 16384
    plan2 = compile_plan(var2, BACKEND_LMSTUDIO_REST, backend_capabilities=caps)

    assert plan1["plan_sha256"] != plan2["plan_sha256"]


def test_lmstudio_native_vs_openai_parameter_naming_distinction():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan_native = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    plan_openai = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_OPENAI, backend_capabilities=caps
    )

    # In native chat REST API: max_output_tokens
    native_fields = {
        op["field"]: op["value"] for op in plan_native["request_operations"]
    }
    assert "max_output_tokens" in native_fields
    assert "max_tokens" not in native_fields
    assert native_fields["max_output_tokens"] == 2048

    # In OpenAI-compatible completions API: max_tokens
    openai_fields = {
        op["field"]: op["value"] for op in plan_openai["request_operations"]
    }
    assert "max_tokens" in openai_fields
    assert "max_output_tokens" not in openai_fields
    assert openai_fields["max_tokens"] == 2048


def test_lmstudio_native_load_operations():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )

    load_ops = {op["field"]: op["value"] for op in plan["load_operations"]}
    assert load_ops["model"] == "qwen2.5-coder-7b"
    assert load_ops["context_length"] == 8192
    assert load_ops["flash_attention"] is True
    assert load_ops["echo_load_config"] is True


def test_unknown_capability_fails_closed_as_rejected():
    # flash_attention is requested, but backend capabilities are empty (unknown)
    plan = compile_plan(SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=[])
    assert plan["status"] == "rejected"
    assert any("capability_unknown" in b for b in plan["blockers"])


def test_unsupported_capability_fails_closed_as_unsupported():
    # flash_attention explicitly unsupported
    caps = [{"name": "flash_attention", "status": "unsupported"}]
    plan = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    assert plan["status"] == "unsupported"
    assert any("capability_unsupported" in b for b in plan["blockers"])


def test_no_op_baseline_equivalence():
    baseline_var = {
        "schema": "lio-variant-v1",
        "model": copy.deepcopy(SAMPLE_VARIANT["model"]),
        "context": 4096,
        "output_limit": 4096,
        "reasoning": "off",
        "sampling": {"temperature": 0.0, "top_p": 1.0},
        "features": {},
        "prompt_policy": "strict-v1",
        "config_sha256": DIGEST,
    }
    # Variant matching baseline exactly
    plan = compile_plan(baseline_var, BACKEND_LMSTUDIO_REST, backend_capabilities=[])
    check = is_baseline_equivalent(plan, baseline_var)
    assert check["equivalent"] is True
    assert check["deltas"] == []

    # Optimized variant compared to baseline
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan_opt = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    check_opt = is_baseline_equivalent(plan_opt, baseline_var)
    assert check_opt["equivalent"] is False
    assert len(check_opt["deltas"]) > 0


def test_missing_baseline_evidence_explicitly_reported():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    check = is_baseline_equivalent(plan, None)
    assert check["equivalent"] is False
    assert check["missing_baseline"] is True
    assert "missing baseline reference" in check["reason"]


def test_plan_evidence_records_never_emit_effective():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    for record in plan["evidence_records"]:
        assert record["stage"] in {"requested", "planned"}
        assert record["stage"] != "effective"


def test_plan_tampering_fails_validation():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    plan_tampered = copy.deepcopy(plan)
    plan_tampered["load_operations"][0]["value"] = "tampered"
    with pytest.raises(ValueError, match="plan_sha256 mismatch"):
        validate_plan(plan_tampered)


def test_real_plan_hashes_canonical_content_not_empty_digest():
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan = compile_plan(
        SAMPLE_VARIANT, BACKEND_LMSTUDIO_REST, backend_capabilities=caps
    )
    empty_digest = hashlib.sha256(b"").hexdigest()
    # Ensure real plans do NOT hash empty input
    assert plan["plan_sha256"] != empty_digest
    # Ensure plan_sha256 exactly matches canonical bytes of plan body
    plan_copy = {k: v for k, v in plan.items() if k != "plan_sha256"}
    expected = hashlib.sha256(canonical_bytes(plan_copy)).hexdigest()
    assert plan["plan_sha256"] == expected


def test_compiler_does_not_invent_mtp_runtime_control():
    var = copy.deepcopy(SAMPLE_VARIANT)
    var["features"] = {"speculation_mode": "mtp", "max_draft_tokens": 4}
    caps = [{"name": "speculative_decoding", "status": "verified"}]
    plan = compile_plan(var, BACKEND_LMSTUDIO_REST, backend_capabilities=caps)

    # Must fail closed as unsupported because LM Studio has no MTP runtime toggle
    assert plan["status"] == "unsupported"
    assert any("runtime_control_unsupported" in b for b in plan["blockers"])
    # Must NOT invent an MTP load operation
    assert not any(op["field"] == "speculation_mode" for op in plan["load_operations"])


def test_disabled_features_compile_without_capabilities():
    var = copy.deepcopy(SAMPLE_VARIANT)
    var["features"] = {
        "flash_attention": False,
        "speculation_mode": "off",
        "max_draft_tokens": 4,
    }
    # No backend capabilities provided at all (unknown)
    plan = compile_plan(var, BACKEND_LMSTUDIO_REST, backend_capabilities=[])
    # Because all features are disabled, it should compile successfully without capabilities!
    assert plan["status"] == "compiled"
    assert plan["blockers"] == []
    # No load operations emitted for disabled features
    load_fields = [op["field"] for op in plan["load_operations"]]
    assert "flash_attention" not in load_fields
    assert "speculation_mode" not in load_fields
    assert "max_draft_tokens" not in load_fields


def test_openai_chat_rejects_unsupported_top_k():
    var = copy.deepcopy(SAMPLE_VARIANT)
    var["sampling"]["top_k"] = 40
    caps = [{"name": "flash_attention", "status": "verified"}]
    plan = compile_plan(var, BACKEND_LMSTUDIO_OPENAI, backend_capabilities=caps)

    assert plan["status"] == "unsupported"
    assert any("sampling_unsupported" in b for b in plan["blockers"])
    assert not any(op["field"] == "top_k" for op in plan["request_operations"])


def test_opencode_load_vs_request_scopes_and_unsupported_features():
    backend_opencode = {
        "identity": "opencode",
        "version": "1.19.5",
        "api_type": "opencode_v1",
    }
    var = copy.deepcopy(SAMPLE_VARIANT)
    var["features"] = {}  # No host load features
    var["sampling"] = {"temperature": 0.5}

    plan = compile_plan(var, backend_opencode, backend_capabilities=[])
    assert plan["status"] == "compiled"

    # In OpenCode, context_length must be in load_ops, NEVER request_ops
    load_fields = {op["field"]: op["target"] for op in plan["load_operations"]}
    request_fields = {op["field"]: op["target"] for op in plan["request_operations"]}

    assert "context_length" in load_fields
    assert "context_length" not in request_fields
    assert "output_limit" in request_fields

    # Now request unsupported host feature (flash_attention=True)
    var_opt = copy.deepcopy(SAMPLE_VARIANT)
    var_opt["features"] = {"flash_attention": True}
    plan_opt = compile_plan(var_opt, backend_opencode, backend_capabilities=[])
    assert plan_opt["status"] == "unsupported"
    assert any("backend_unsupported" in b for b in plan_opt["blockers"])


def test_no_op_baseline_equivalence_with_explicit_defaults():
    baseline_var = {
        "schema": "lio-variant-v1",
        "model": copy.deepcopy(SAMPLE_VARIANT["model"]),
        "context": 4096,
        "output_limit": 4096,
        "reasoning": "off",
        "sampling": {"temperature": 0.0, "top_p": 1.0},
        "features": {},
        "prompt_policy": "strict-v1",
        "config_sha256": DIGEST,
    }
    candidate_var = copy.deepcopy(baseline_var)
    # Explicitly specify default catalog values
    candidate_var["features"] = {
        "flash_attention": False,
        "speculation_mode": "off",
    }
    candidate_var["sampling"]["top_k"] = 0

    plan = compile_plan(candidate_var, BACKEND_LMSTUDIO_REST, backend_capabilities=[])
    check = is_baseline_equivalent(plan, baseline_var)
    assert check["equivalent"] is True
    assert check["deltas"] == []
