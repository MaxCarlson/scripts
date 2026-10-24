"""Unit tests for the llm_models registry helpers."""

from pathlib import Path
import sys
import importlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_models.registry import ModelAssignmentManager, ModelRegistry  # noqa: E402

registry_module = importlib.import_module("llm_models.registry")


def test_default_registry_contains_expected_models() -> None:
    registry = ModelRegistry.default()
    names = {spec.name for spec in registry.list_models()}
    assert "qwen2.5-coder-32b-instruct-q4_k_m" in names
    assert "deepseek-coder-v2-lite-instruct-q4_k_m" in names


def test_assignment_prefers_highest_scoring_model_within_budget() -> None:
    registry = ModelRegistry.default()
    manager = ModelAssignmentManager(registry=registry)

    selected = manager.select_model(task="coding", max_vram_gb=30)
    assert selected.name == "qwen2.5-coder-32b-instruct-q4_k_m"

    constrained = manager.select_model(task="coding", max_vram_gb=18)
    assert constrained.name == "codeqwen1.5-14b-chat-q4_k_m"


def test_available_vram_uses_shared_total_and_custom_binary(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("NVIDIA_SMI", "custom-nvidia-smi")
    monkeypatch.delenv("LLM_MAX_VRAM_GB", raising=False)
    monkeypatch.setattr(
        registry_module,
        "nvidia_gpus",
        lambda **kwargs: calls.append(kwargs) or [{"mem_total": 8 * 1024**3}],
    )
    manager = object.__new__(ModelAssignmentManager)

    assert manager._detect_available_vram() == 8192
    assert calls == [{"timeout": 5, "binary_name": "custom-nvidia-smi"}]
