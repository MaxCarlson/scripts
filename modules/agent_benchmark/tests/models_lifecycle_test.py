"""
Unit tests for LM Studio model discovery, loaded model detection, and safe transitions.
"""

from __future__ import annotations

import json
import pytest

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
