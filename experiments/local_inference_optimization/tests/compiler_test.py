import copy
import pytest

from local_inference_optimization.compiler import (
    compile_plan,
    is_baseline_equivalent,
    validate_plan,
)

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
