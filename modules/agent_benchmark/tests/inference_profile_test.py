"""Inference profiles must remain explicit and project-local."""
import json
from pathlib import Path

import pytest

from agent_benchmark.evidence import load_task, prepare_workspace
from agent_benchmark.identity import ModelIdentity
from agent_benchmark.inference_profile import load_inference_profile, validate_context_match


def _write_profile(path: Path, *, mode="effort", effort="low", provenance="experiment_profile") -> None:
    path.write_text(json.dumps({
        "schema": "opencode-inference-profile-v1",
        "context_length": 98304,
        "output_limit": 8192,
        "reasoning": {"mode": mode, "effort": effort,
                      "provenance": "source_config" if mode == "unconfigured" else provenance},
    }), encoding="utf-8")


def test_inference_profile_validates_safe_scalar_settings_and_context(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    _write_profile(path)
    profile = load_inference_profile(path)
    assert profile.context_length == 98304
    assert profile.output_limit == 8192
    assert profile.reasoning_effort == "low"
    assert len(profile.sha256) == 64
    validate_context_match(profile, 98304)
    with pytest.raises(ValueError, match="does not match"):
        validate_context_match(profile, 16384)

    data = json.loads(path.read_text(encoding="utf-8"))
    data["api_key"] = "must-not-be-accepted"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="only schema"):
        load_inference_profile(path)


@pytest.mark.parametrize("mode,effort", [(["effort"], "none"), ("effort", {"value": "none"})])
def test_inference_profile_rejects_non_string_reasoning_values(tmp_path: Path, mode, effort) -> None:
    path = tmp_path / "profile.json"
    _write_profile(path, mode=mode, effort=effort)

    with pytest.raises(ValueError):
        load_inference_profile(path)


def test_experiment_cli_accepts_explicit_context_and_profile() -> None:
    from agent_benchmark.cli import parser

    args = parser().parse_args(["experiment", "run", "-x", "-m", "qwen38-27b-q4km", "-c", "98304",
                                "--inference-profile", "profile.json"])
    assert args.context_length == 98304
    assert args.inference_profile == Path("profile.json")


@pytest.mark.parametrize("mode,effort,expected", [
    ("unconfigured", None, {"reasoning": False, "effort": None}),
    ("effort", "none", {"reasoning": True, "effort": "none"}),
    ("effort", "xhigh", {"reasoning": True, "effort": "xhigh"}),
])
def test_profile_maps_to_exact_trial_model_and_agent_only(tmp_path: Path, mode, effort, expected) -> None:
    identity = ModelIdentity("qwen38-27b-q4km", "lmstudio", "qwen38-27b-q4km",
                             "qwen38-27b-q4km", "Qwen3.8-27B Q4_K_M", "Q4_K_M")
    path = tmp_path / "profile.json"
    _write_profile(path, mode=mode, effort=effort,
                   provenance="source_config" if mode == "unconfigured" else "experiment_profile")
    profile = load_inference_profile(path).to_dict()
    task_path = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks/qwen-file-creation"
    workspace = tmp_path / "workspace"
    prepare_workspace(load_task(task_path), workspace, model_identity=identity, inference_profile=profile)

    config = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
    model = config["provider"]["lmstudio"]["models"][identity.runtime_model_id]
    role = config["agent"]["benchmark-files"]
    assert model["limit"] == {"context": 98304, "output": 8192}
    assert (model.get("reasoning") is True) is expected["reasoning"]
    assert bool(model.get("variants")) is False
    assert model.get("options", {}).get("reasoningEffort") == expected["effort"]
    assert role.get("variant") is None
