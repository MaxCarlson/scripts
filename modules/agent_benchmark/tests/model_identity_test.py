from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent_benchmark.identity import (
    ModelIdentityError,
    ModelIdentity,
    model_readiness,
    resolve_lmstudio_identity,
    write_project_model_registration,
)
from agent_benchmark.models_lifecycle import DownloadedModelInfo


def model(key: str, *, display: str = "Friendly name", quantization: str = "Q4_K_M") -> DownloadedModelInfo:
    return DownloadedModelInfo(
        model_key=key,
        display_name=display,
        architecture="test",
        size_bytes=100,
        quantization=quantization,
        max_context_length=4096,
        format="gguf",
        path=key,
    )


def make_identity(key: str, *, display: str = "Friendly name") -> ModelIdentity:
    return ModelIdentity(key, "lmstudio", key, key, display, "Q4_K_M")


def test_resolve_requires_an_exact_lm_studio_key_and_preserves_quantization() -> None:
    resolved = resolve_lmstudio_identity("meta/muse-glimmer", [model("meta/muse-glimmer", quantization="Q4_K_M")])

    assert resolved.requested_id == "meta/muse-glimmer"
    assert resolved.runtime_model_id == "meta/muse-glimmer"
    assert resolved.lms_model_key == "meta/muse-glimmer"
    assert resolved.quantization == "Q4_K_M"


def test_opencode_display_alias_is_not_treated_as_a_model_id() -> None:
    with pytest.raises(ModelIdentityError, match="exact LM Studio model key"):
        resolve_lmstudio_identity("qwen38_23GB", [model("qwen38-27b-q4km")])


def test_duplicate_exact_keys_are_ambiguous() -> None:
    with pytest.raises(ModelIdentityError, match="ambiguous"):
        resolve_lmstudio_identity("same-key", [model("same-key"), model("same-key", quantization="Q6_K")])


def test_distinct_quantized_model_keys_resolve_independently_even_with_same_display_name() -> None:
    q4 = model("qwen38-q4", display="Qwen 3.8 27B", quantization="Q4_K_M")
    q6 = model("qwen38-q6", display="Qwen 3.8 27B", quantization="Q6_K")

    assert resolve_lmstudio_identity("qwen38-q4", [q4, q6]).quantization == "Q4_K_M"
    assert resolve_lmstudio_identity("qwen38-q6", [q4, q6]).quantization == "Q6_K"


def test_plan_readiness_distinguishes_registered_and_auto_registration() -> None:
    inventory = [model("meta/muse-glimmer")]

    assert model_readiness("meta/muse-glimmer", inventory, {"meta/muse-glimmer"})["status"] == "runnable"
    pending = model_readiness("meta/muse-glimmer", inventory, set())
    assert pending["status"] == "registration_required"
    assert pending["identity"]["runtime_model_id"] == "meta/muse-glimmer"
    assert model_readiness("qwen38_23GB", inventory, {"qwen38_23GB"})["status"] == "unavailable"


def test_plan_readiness_does_not_claim_runnable_when_provider_state_is_unknown() -> None:
    inventory = [model("meta/muse-glimmer")]

    assert model_readiness("meta/muse-glimmer", inventory, None, provider_connected=None)["status"] == "unknown"
    assert model_readiness("meta/muse-glimmer", inventory, {"meta/muse-glimmer"},
                           provider_connected=None)["status"] == "unknown"
    assert model_readiness("meta/muse-glimmer", inventory, {"meta/muse-glimmer"},
                           provider_connected=False)["status"] == "unavailable"


def test_identity_records_exact_variant_metadata() -> None:
    exact = model("qwen38-27b-q6k")
    exact = replace(exact, selected_variant="Q6_K", variants=("Q4_K_M", "Q6_K"))
    identity = resolve_lmstudio_identity("qwen38-27b-q6k", [exact]).to_dict()

    assert identity["lms_model_key"] == "qwen38-27b-q6k"
    assert identity["selected_variant"] == "Q6_K"
    assert identity["available_variants"] == ["Q4_K_M", "Q6_K"]


def test_project_registration_preserves_existing_config_and_aliases(tmp_path) -> None:
    path = tmp_path / "opencode.json"
    original = {
        "$schema": "https://opencode.ai/config.json",
        "model": "lmstudio/qwen38_23GB",
        "provider": {
            "lmstudio": {
                "options": {"baseURL": "http://127.0.0.1:1234/v1", "apiKey": "keep-me"},
                "models": {"qwen38_23GB": {"name": "legacy display alias"}},
            }
        },
        "other": {"unchanged": True},
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    write_project_model_registration(tmp_path, make_identity("meta/muse-glimmer", display="Muse Glimmer"))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["model"] == original["model"]
    assert saved["provider"]["lmstudio"]["options"] == original["provider"]["lmstudio"]["options"]
    assert saved["provider"]["lmstudio"]["models"]["qwen38_23GB"] == {"name": "legacy display alias"}
    assert saved["provider"]["lmstudio"]["models"]["meta/muse-glimmer"] == {"name": "Muse Glimmer"}
    assert saved["other"] == original["other"]


def test_failed_atomic_registration_leaves_existing_config_unchanged(tmp_path, monkeypatch) -> None:
    import agent_benchmark.identity as identity

    path = tmp_path / "opencode.json"
    original = '{"provider":{"lmstudio":{"models":{}}}}'
    path.write_text(original, encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(identity.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        write_project_model_registration(tmp_path, make_identity("new-id"))

    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_jsonc_project_config_is_never_overwritten(tmp_path) -> None:
    (tmp_path / "opencode.jsonc").write_text("{ /* retain comments */ }", encoding="utf-8")

    with pytest.raises(ModelIdentityError, match="JSONC"):
        write_project_model_registration(tmp_path, make_identity("new-id"))

    assert (tmp_path / "opencode.jsonc").read_text(encoding="utf-8") == "{ /* retain comments */ }"
    assert not (tmp_path / "opencode.json").exists()
