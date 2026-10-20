"""
Unit tests for LM Studio model discovery, loaded model detection, and safe transitions.
"""

from __future__ import annotations

import json
import subprocess
import pytest

from agent_benchmark import models_lifecycle
from agent_benchmark.models_lifecycle import (
    ModelDiscoveryError,
    ModelTransitionError,
    ModelTransitionNotAuthorizedError,
    get_loaded_model,
    get_loaded_models,
    list_downloaded_models,
    transition_model,
)

SAMPLE_LMS_LS_OUTPUT = json.dumps([
    {
        "type": "llm",
        "modelKey": "qwen38-27b-q4km",
        "displayName": "Qwen3.8 27B",
        "architecture": "qwen35",
        "sizeBytes": 16810714336,
        "format": "gguf",
        "path": "local/qwen38-27b-q4km/Qwen3.8-27B-Q4_K_M.gguf",
        "quantization": {"name": "Q4_K_M", "bits": 4},
        "maxContextLength": 262144,
        "trainedForToolUse": True,
    },
    {
        "type": "llm",
        "modelKey": "qwen38-27b-q6k",
        "displayName": "Qwen3.8 27B Q6",
        "architecture": "qwen35",
        "sizeBytes": 22430999776,
        "format": "gguf",
        "path": "local/qwen38-27b-q6k/Qwen3.8-27B-Q6_K.gguf",
        "quantization": {"name": "Q6_K", "bits": 6},
        "maxContextLength": 262144,
        "trainedForToolUse": True,
    },
])

SAMPLE_LMS_PS_LOADED = json.dumps([
    {
        "identifier": "qwen38_23GB",
        "modelKey": "qwen38-27b-q4km",
        "displayName": "Qwen3.8 27B",
        "status": "idle",
        "contextLength": 32768,
        "sizeBytes": 16810714336,
        "maxContextLength": 262144,
    }
])

SAMPLE_LMS_PS_EMPTY = "[]"


@pytest.mark.asyncio
async def test_default_command_runner_executes_windows_cli_in_worker_thread(monkeypatch) -> None:
    calls = []

    def fake_run(command, *, capture_output, text, check):
        calls.append((command, capture_output, text, check))
        return subprocess.CompletedProcess(command, 7, stdout="out", stderr="err")

    monkeypatch.setattr(models_lifecycle.subprocess, "run", fake_run)

    result = await models_lifecycle._default_cmd_runner(["lms", "ps", "--json"])

    assert result == (7, "out", "err")
    assert calls == [(["lms", "ps", "--json"], True, True, False)]


@pytest.mark.asyncio
async def test_list_downloaded_models_from_lms_cli() -> None:
    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        assert cmd == ["lms", "ls", "--json"]
        return 0, SAMPLE_LMS_LS_OUTPUT, ""

    models = await list_downloaded_models(runner=mock_runner)
    assert len(models) == 2

    m1 = models[0]
    assert m1.model_key == "qwen38-27b-q4km"
    assert m1.display_name == "Qwen3.8 27B"
    assert m1.quantization == "Q4_K_M"
    assert m1.architecture == "qwen35"
    assert m1.size_bytes == 16810714336
    assert m1.max_context_length == 262144
    assert m1.trained_for_tool_use is True

    m2 = models[1]
    assert m2.model_key == "qwen38-27b-q6k"
    assert m2.quantization == "Q6_K"


@pytest.mark.asyncio
async def test_get_loaded_models_and_loaded_model() -> None:
    # 1. When a model is loaded
    async def mock_runner_loaded(cmd: list[str]) -> tuple[int, str, str]:
        assert cmd == ["lms", "ps", "--json"]
        return 0, SAMPLE_LMS_PS_LOADED, ""

    loaded = await get_loaded_models(runner=mock_runner_loaded)
    assert len(loaded) == 1
    assert loaded[0].identifier == "qwen38_23GB"
    assert loaded[0].model_key == "qwen38-27b-q4km"
    assert loaded[0].status == "idle"

    single = await get_loaded_model(runner=mock_runner_loaded)
    assert single is not None
    assert single.identifier == "qwen38_23GB"

    # 2. When no model is loaded
    async def mock_runner_empty(cmd: list[str]) -> tuple[int, str, str]:
        return 0, SAMPLE_LMS_PS_EMPTY, ""

    empty_loaded = await get_loaded_models(runner=mock_runner_empty)
    assert empty_loaded == []
    empty_single = await get_loaded_model(runner=mock_runner_empty)
    assert empty_single is None


@pytest.mark.asyncio
async def test_get_loaded_models_error_handling() -> None:
    async def mock_runner_fail(cmd: list[str]) -> tuple[int, str, str]:
        return 1, "", "Service unavailable"

    with pytest.raises(ModelDiscoveryError, match="lms ps failed"):
        await get_loaded_models(runner=mock_runner_fail)


@pytest.mark.asyncio
async def test_transition_model_already_loaded_no_op() -> None:
    """If target model is already loaded, transition_model returns immediately without unload."""
    unloaded_called = False

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal unloaded_called
        if "unload" in cmd:
            unloaded_called = True
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        return 0, "", ""

    res = await transition_model("qwen38-27b-q4km", allow_transitions=False, runner=mock_runner)
    assert res.identifier == "qwen38_23GB"
    assert not unloaded_called


@pytest.mark.asyncio
async def test_transition_model_unauthorized_rejection() -> None:
    """If target model is not loaded and allow_transitions=False, raise ModelTransitionNotAuthorizedError."""
    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        return 0, "", ""

    with pytest.raises(ModelTransitionNotAuthorizedError, match="not authorized"):
        await transition_model("qwen38-27b-q6k", allow_transitions=False, runner=mock_runner)


@pytest.mark.asyncio
async def test_transition_model_authorized_success_flow() -> None:
    """Authorized transition: unloads current, waits for empty ps, loads target, waits for target ps."""
    ps_state = "initial"  # "initial" -> "unloaded" -> "loaded"
    commands_run: list[list[str]] = []

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal ps_state
        commands_run.append(cmd)
        if cmd == ["lms", "ps", "--json"]:
            if ps_state == "initial":
                return 0, SAMPLE_LMS_PS_LOADED, ""
            elif ps_state == "unloaded":
                return 0, SAMPLE_LMS_PS_EMPTY, ""
            elif ps_state == "loaded":
                return 0, json.dumps([{
                    "identifier": "qwen38_q6_id",
                    "modelKey": "qwen38-27b-q6k",
                    "displayName": "Qwen3.8 27B Q6",
                    "status": "idle",
                    "contextLength": 32768,
                    "sizeBytes": 22430999776,
                    "maxContextLength": 262144,
                }]), ""
        elif cmd == ["lms", "unload", "-a"]:
            ps_state = "unloaded"
            return 0, "Unloaded all models", ""
        elif cmd == ["lms", "load", "qwen38-27b-q6k", "-y"]:
            ps_state = "loaded"
            return 0, "Loaded qwen38-27b-q6k", ""
        return 0, "", ""

    res = await transition_model(
        "qwen38-27b-q6k",
        allow_transitions=True,
        runner=mock_runner,
        unload_timeout=5.0,
        load_timeout=5.0,
        poll_interval=0.01,
    )

    assert res.identifier == "qwen38_q6_id"
    assert res.model_key == "qwen38-27b-q6k"
    assert ["lms", "unload", "-a"] in commands_run
    assert ["lms", "load", "qwen38-27b-q6k", "-y"] in commands_run


@pytest.mark.asyncio
async def test_transition_model_load_failure_no_blind_retry() -> None:
    """When lms load fails, halt immediately and raise ModelTransitionError."""
    ps_state = "initial"

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal ps_state
        if cmd == ["lms", "ps", "--json"]:
            if ps_state == "initial":
                return 0, SAMPLE_LMS_PS_LOADED, ""
            return 0, SAMPLE_LMS_PS_EMPTY, ""
        elif cmd == ["lms", "unload", "-a"]:
            ps_state = "unloaded"
            return 0, "Unloaded", ""
        elif cmd == ["lms", "load", "faulty-model", "-y"]:
            return 1, "", "CUDA Out of Memory (OOM) error"
        return 0, "", ""

    with pytest.raises(ModelTransitionError, match="Failed to load model.*CUDA Out of Memory"):
        await transition_model(
            "faulty-model",
            allow_transitions=True,
            runner=mock_runner,
            unload_timeout=5.0,
            load_timeout=5.0,
            poll_interval=0.01,
        )


def test_resolve_model_provider_and_key() -> None:
    from agent_benchmark.models_lifecycle import resolve_model_provider_and_key

    # Gemini via agy aliases and prefixes
    assert resolve_model_provider_and_key("gemini-3.8-flash") == ("gemini", "gemini-3.8-flash-high")
    assert resolve_model_provider_and_key("gemini-4-Argon") == ("gemini", "gemini-4-argon-medium")
    assert resolve_model_provider_and_key("gemini/gemini-4-argon-high") == ("gemini", "gemini-4-argon-high")
    assert resolve_model_provider_and_key("gemini") == ("gemini", "gemini-4-argon-medium")

    # Codex aliases and prefixes
    assert resolve_model_provider_and_key("ChatGpt-6.1-sol") == ("codex", "gpt-6.1-sol")
    assert resolve_model_provider_and_key("6-sol") == ("codex", "gpt-6-sol")
    assert resolve_model_provider_and_key("6-luna") == ("codex", "gpt-6-luna")
    assert resolve_model_provider_and_key("6-Astra") == ("codex", "gpt-6-astra")
    assert resolve_model_provider_and_key("5.6-Luna") == ("codex", "gpt-5.6-luna")
    assert resolve_model_provider_and_key("5.6-Terra") == ("codex", "gpt-5.6-terra")
    assert resolve_model_provider_and_key("5.6-Sol") == ("codex", "gpt-5.6-sol")
    assert resolve_model_provider_and_key("codex/gpt-6-astra") == ("codex", "gpt-6-astra")
    assert resolve_model_provider_and_key("codex") == ("codex", "gpt-6.1-sol")

    # Local LM Studio models
    assert resolve_model_provider_and_key("qwen38-27b-q4km") == ("lmstudio", "qwen38-27b-q4km")
    assert resolve_model_provider_and_key("lmstudio/qwen38-27b-q6k") == ("lmstudio", "qwen38-27b-q6k")


@pytest.mark.asyncio
async def test_list_gemini_and_codex_models(tmp_path) -> None:
    from agent_benchmark.models_lifecycle import list_codex_models, list_gemini_models

    async def mock_agy_runner(cmd: list[str]) -> tuple[int, str, str]:
        out = (
            "Fetching available models...\n"
            "gemini-4-argon-medium\tGemini 4 Argon (Medium)\n"
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "claude-opus-5-5-low\tClaude Opus 5.5 (Low)\n"
        )
        return 0, out, ""

    gem_models = await list_gemini_models(runner=mock_agy_runner)
    assert len(gem_models) == 2
    assert gem_models[0].model_key == "gemini-4-argon-medium"
    assert gem_models[1].model_key == "gemini-3.8-flash-high"

    cache_file = tmp_path / "models_cache.json"
    cache_file.write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol", "description": "Workhorse"},
                    {"slug": "gpt-6-astra", "display_name": "GPT-6-Astra", "description": "Frontier"},
                    {"slug": "codex-auto-review", "display_name": "Codex Auto Review"},
                ]
            }
        ),
        encoding="utf-8",
    )
    cdx_models = await list_codex_models(cache_path=cache_file)
    assert len(cdx_models) == 2
    assert cdx_models[0].model_key == "gpt-6.1-sol"
    assert cdx_models[1].model_key == "gpt-6-astra"

