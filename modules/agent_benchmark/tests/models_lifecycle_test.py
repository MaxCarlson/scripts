"""
Unit tests for LM Studio model discovery, loaded model detection, and safe transitions.
"""

from __future__ import annotations

import json
import subprocess
import pytest

from agent_benchmark import models_lifecycle
from agent_benchmark.telemetry import ResourceSnapshot
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

    def fake_run(command, *, capture_output, text, check, encoding, errors, timeout):
        calls.append((command, capture_output, text, check, encoding, errors, timeout))
        return subprocess.CompletedProcess(command, 7, stdout="out", stderr="err")

    monkeypatch.setattr(models_lifecycle.subprocess, "run", fake_run)

    result = await models_lifecycle._default_cmd_runner(["lms", "ps", "--json"])

    assert result == (7, "out", "err")
    assert calls == [(["lms", "ps", "--json"], True, True, False, "utf-8", "replace", 15.0)]


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
async def test_transition_model_already_loaded_no_op(monkeypatch) -> None:
    """If target model is already loaded, transition_model returns immediately without unload."""
    unloaded_called = False
    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=40, ram_available_bytes=32 * 1024**3,
        gpu_memory_used_bytes=4 * 1024**3, gpu_memory_total_bytes=32 * 1024**3,
    ))

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal unloaded_called
        if "unload" in cmd:
            unloaded_called = True
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        return 0, "", ""

    res = await transition_model("qwen38-27b-q4km", allow_transitions=False, context_length=32768, runner=mock_runner)
    assert res.identifier == "qwen38_23GB"
    assert not unloaded_called


@pytest.mark.asyncio
async def test_transition_model_rejects_preloaded_context_mismatch_without_authorization() -> None:
    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        pytest.fail(f"Context mismatch must not load or unload without authorization: {cmd}")

    with pytest.raises(ModelTransitionNotAuthorizedError, match="context.*32768.*16384"):
        await transition_model(
            "qwen38-27b-q4km", allow_transitions=False, context_length=16384, runner=mock_runner
        )


@pytest.mark.asyncio
async def test_transition_model_allows_preloaded_model_at_high_ram_by_default(monkeypatch) -> None:
    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(ram_pct=95.0))

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        pytest.fail(f"A matching preloaded model should not need a transition: {cmd}")

    loaded = await transition_model("qwen38-27b-q4km", allow_transitions=False,
                                    context_length=32768, runner=mock_runner)
    assert loaded.model_key == "qwen38-27b-q4km"


@pytest.mark.asyncio
async def test_transition_model_honors_explicit_ram_percent_for_preloaded_model(monkeypatch) -> None:
    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(ram_pct=95.0))

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        pytest.fail(f"Explicit RAM limit must prevent dispatch: {cmd}")

    with pytest.raises(ModelTransitionError, match="95.0%.*explicit RAM limit 90.0%"):
        await transition_model("qwen38-27b-q4km", allow_transitions=False, context_length=32768,
                               max_ram_pct=90.0, runner=mock_runner)


@pytest.mark.asyncio
async def test_transition_model_fails_closed_when_explicit_ram_limit_cannot_be_measured(monkeypatch) -> None:
    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot())

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        pytest.fail(f"An unenforceable explicit limit must stop before dispatch: {cmd}")

    with pytest.raises(ModelTransitionError, match="Cannot enforce explicit host RAM limit"):
        await transition_model("qwen38-27b-q4km", allow_transitions=False, context_length=32768,
                               max_ram_pct=90.0, runner=mock_runner)


@pytest.mark.asyncio
async def test_transition_model_estimates_and_loads_at_requested_context(monkeypatch) -> None:
    ps_state = "initial"
    commands_run: list[list[str]] = []

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal ps_state
        commands_run.append(cmd)
        if cmd == ["lms", "ps", "--json"]:
            if ps_state == "initial":
                return 0, SAMPLE_LMS_PS_LOADED, ""
            if ps_state == "unloaded":
                return 0, SAMPLE_LMS_PS_EMPTY, ""
            item = json.loads(SAMPLE_LMS_PS_LOADED)[0]
            item["modelKey"] = "qwen38-27b-q6k"
            item["contextLength"] = 16384
            return 0, json.dumps([item]), ""
        if cmd == ["lms", "unload", "-a"]:
            ps_state = "unloaded"
            return 0, "Unloaded all models", ""
        if cmd == ["lms", "load", "qwen38-27b-q6k", "--estimate-only", "--context-length", "16384"]:
            # The installed LMS CLI writes successful human-readable estimates to stderr.
            return 0, "", "Estimated GPU Memory: 18.0 GiB\nEstimated Total Memory: 22.0 GiB"
        if cmd == ["lms", "load", "qwen38-27b-q6k", "--context-length", "16384", "-y"]:
            ps_state = "loaded"
            return 0, "Loaded", ""
        pytest.fail(f"Unexpected command: {cmd}")

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=40, ram_available_bytes=32 * 1024**3,
        gpu_memory_used_bytes=4 * 1024**3, gpu_memory_total_bytes=32 * 1024**3,
    ))
    result = await transition_model(
        "qwen38-27b-q6k", allow_transitions=True, expected_model_size_bytes=16 * 1024**3,
        context_length=16384, runner=mock_runner, unload_timeout=5, load_timeout=5, poll_interval=0.01,
    )
    assert result.context_length == 16384
    assert ["lms", "load", "qwen38-27b-q6k", "--estimate-only", "--context-length", "16384"] in commands_run
    assert ["lms", "load", "qwen38-27b-q6k", "--context-length", "16384", "-y"] in commands_run


def test_parse_lms_memory_estimate():
    from agent_benchmark.models_lifecycle import parse_lms_memory_estimate

    assert parse_lms_memory_estimate(
        "Estimated GPU Memory: 21.48 GiB\nEstimated Total Memory: 25.00 GB"
    ) == pytest.approx((21.48 * 1024**3, 25.00 * 10**9))


def test_parse_lms_memory_estimate_rejects_incomplete_output():
    from agent_benchmark.models_lifecycle import parse_lms_memory_estimate

    with pytest.raises(ModelTransitionError, match="Could not parse"):
        parse_lms_memory_estimate("Model can be loaded")


def test_lms_estimate_blocks_when_combined_measured_capacity_is_insufficient():
    snapshot = ResourceSnapshot(ram_available_bytes=8 * 1024**3,
                                gpu_memory_used_bytes=0, gpu_memory_total_bytes=32 * 1024**3)
    with pytest.raises(ModelTransitionError, match="measured combined headroom is 40.0 GiB"):
        models_lifecycle._verify_memory_estimate(31 * 1024**3, 41 * 1024**3, snapshot)


@pytest.mark.asyncio
async def test_transition_model_blocks_estimate_that_exceeds_measured_gpu_capacity(monkeypatch) -> None:
    calls = []

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        calls.append(cmd)
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_EMPTY, ""
        if "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 33 GiB\nEstimated Total Memory: 35 GiB", ""
        pytest.fail(f"Unsafe estimate must block actual load: {cmd}")

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=35, ram_available_bytes=40 * 1024**3,
        gpu_memory_used_bytes=0, gpu_memory_total_bytes=32 * 1024**3,
    ))
    with pytest.raises(ModelTransitionError, match="GPU estimate 33.0 GiB exceeds measured GPU availability"):
        await transition_model("large-model", allow_transitions=True, context_length=16384, runner=mock_runner)
    assert not any("-y" in command for command in calls)


@pytest.mark.asyncio
async def test_transition_model_allows_estimate_that_fits_measured_capacity_without_reserve(monkeypatch) -> None:
    commands = []
    state = "empty"
    loaded_json = "[]"

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal state, loaded_json
        commands.append(cmd)
        if cmd == ["lms", "ps", "--json"]:
            if state == "empty":
                return 0, SAMPLE_LMS_PS_EMPTY, ""
            return 0, loaded_json, ""
        if "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 30 GiB\nEstimated Total Memory: 45 GiB", ""
        if "-y" in cmd:
            item = dict(json.loads(SAMPLE_LMS_PS_LOADED)[0], modelKey="new-model", identifier="new-model",
                        contextLength=16384)
            state = "loaded"
            loaded_json = json.dumps([item])
            return 0, "Loaded", ""
        if cmd == ["lms", "ps", "--json"] and any("-y" in command for command in commands):
            return 0, commands[-1][1], ""
        pytest.fail(f"Unexpected command: {cmd}")

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=96.0, ram_available_bytes=15 * 1024**3,
        gpu_memory_used_bytes=0, gpu_memory_total_bytes=30 * 1024**3,
    ))
    loaded = await transition_model("new-model", allow_transitions=True, context_length=16384,
                                    runner=mock_runner, load_timeout=0.01)
    assert loaded.model_key == "new-model"
    assert any("-y" in command for command in commands)


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
async def test_transition_model_rejects_target_loaded_alongside_other_model_without_transition() -> None:
    first = json.loads(SAMPLE_LMS_PS_LOADED)[0]
    other = dict(first, identifier="other", modelKey="other", displayName="Other")
    two_loaded = json.dumps([first, other])

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        assert cmd == ["lms", "ps", "--json"]
        return 0, two_loaded, ""

    with pytest.raises(ModelTransitionNotAuthorizedError, match="sole loaded model"):
        await transition_model("qwen38-27b-q4km", allow_transitions=False, runner=mock_runner)


@pytest.mark.asyncio
async def test_transition_model_does_not_unload_busy_lmstudio_model() -> None:
    busy = json.loads(SAMPLE_LMS_PS_LOADED)[0]
    busy["status"] = "processing"

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, json.dumps([busy]), ""
        pytest.fail(f"Busy model must not be unloaded: {cmd}")

    with pytest.raises(ModelTransitionError, match="active or unknown status"):
        await transition_model("qwen38-27b-q6k", allow_transitions=True, runner=mock_runner)


@pytest.mark.asyncio
async def test_transition_model_authorized_success_flow(monkeypatch) -> None:
    """Authorized transition: unloads current, waits for empty ps, loads target, waits for target ps."""
    ps_state = "initial"  # "initial" -> "unloaded" -> "loaded"
    commands_run: list[list[str]] = []
    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=40, ram_available_bytes=32 * 1024**3,
        gpu_memory_used_bytes=4 * 1024**3, gpu_memory_total_bytes=32 * 1024**3,
    ))

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
                    "contextLength": 16384,
                    "sizeBytes": 22430999776,
                    "maxContextLength": 262144,
                }]), ""
        elif cmd == ["lms", "unload", "-a"]:
            ps_state = "unloaded"
            return 0, "Unloaded all models", ""
        elif "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 18 GiB\nEstimated Total Memory: 22 GiB", ""
        elif cmd == ["lms", "load", "qwen38-27b-q6k", "--context-length", "16384", "-y"]:
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
        expected_model_size_bytes=16 * 1024**3,
        context_length=16384,
    )

    assert res.identifier == "qwen38_q6_id"
    assert res.model_key == "qwen38-27b-q6k"
    assert ["lms", "unload", "-a"] in commands_run
    assert ["lms", "load", "qwen38-27b-q6k", "--context-length", "16384", "-y"] in commands_run


@pytest.mark.asyncio
async def test_transition_model_load_failure_no_blind_retry(monkeypatch) -> None:
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
        elif "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 18 GiB\nEstimated Total Memory: 22 GiB", ""
        elif cmd == ["lms", "load", "faulty-model", "--context-length", "16384", "-y"]:
            return 1, "", "CUDA Out of Memory (OOM) error"
        return 0, "", ""

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=40, ram_available_bytes=32 * 1024**3,
        gpu_memory_used_bytes=4 * 1024**3, gpu_memory_total_bytes=32 * 1024**3,
    ))

    with pytest.raises(ModelTransitionError, match="Failed to load model.*CUDA Out of Memory"):
        await transition_model(
            "faulty-model",
            allow_transitions=True,
            runner=mock_runner,
            unload_timeout=5.0,
            load_timeout=5.0,
            poll_interval=0.01,
            expected_model_size_bytes=16 * 1024**3,
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
    assert resolve_model_provider_and_key("openai/gpt-oss-20b") == ("lmstudio", "openai/gpt-oss-20b")
    assert resolve_model_provider_and_key("lms/meta/muse-glimmer") == ("lmstudio", "meta/muse-glimmer")
    assert resolve_model_provider_and_key("lmstudio/mistralai/devstral-small-2-2512") == (
        "lmstudio", "mistralai/devstral-small-2-2512"
    )
    assert resolve_model_provider_and_key("lmstudio/qwen38-27b-q6k") == ("lmstudio", "qwen38-27b-q6k")


@pytest.mark.asyncio
async def test_transition_model_allows_load_above_90_percent_without_explicit_limit(monkeypatch) -> None:
    state = "empty"
    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal state
        if cmd == ["lms", "ps", "--json"]:
            if state == "empty":
                return 0, "[]", ""
            item = dict(json.loads(SAMPLE_LMS_PS_LOADED)[0], modelKey="new-model", identifier="new-model",
                        contextLength=16384)
            return 0, json.dumps([item]), ""
        if "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 10 GiB\nEstimated Total Memory: 15 GiB", ""
        if "-y" in cmd:
            state = "loaded"
            return 0, "Loaded", ""
        pytest.fail(f"Unexpected command: {cmd}")

    monkeypatch.setattr(
        "agent_benchmark.models_lifecycle.collect_resource_snapshot",
        lambda: ResourceSnapshot(ram_pct=91.0, ram_available_bytes=20 * 1024**3,
                                 gpu_memory_used_bytes=0, gpu_memory_total_bytes=32 * 1024**3),
    )

    loaded = await transition_model("new-model", allow_transitions=True, runner=mock_runner)
    assert loaded.model_key == "new-model"


@pytest.mark.asyncio
async def test_transition_model_does_not_apply_file_size_multiplier(monkeypatch) -> None:
    state = "empty"
    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        nonlocal state
        if cmd == ["lms", "ps", "--json"]:
            if state == "empty":
                return 0, "[]", ""
            item = dict(json.loads(SAMPLE_LMS_PS_LOADED)[0], modelKey="large-model", identifier="large-model",
                        contextLength=16384)
            return 0, json.dumps([item]), ""
        if "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 1 GiB\nEstimated Total Memory: 2 GiB", ""
        if "-y" in cmd:
            state = "loaded"
            return 0, "Loaded", ""
        pytest.fail(f"Unexpected command: {cmd}")

    monkeypatch.setattr(
        "agent_benchmark.models_lifecycle.collect_resource_snapshot",
        lambda: ResourceSnapshot(ram_pct=75.0, ram_available_bytes=10 * 1024**3,
                                 gpu_memory_used_bytes=0, gpu_memory_total_bytes=8 * 1024**3),
    )

    await transition_model("large-model", allow_transitions=True,
                           expected_model_size_bytes=10 * 1024**3, runner=mock_runner)


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



@pytest.mark.asyncio
async def test_unload_waits_for_empty_inventory_without_percentage_or_reserve_threshold(monkeypatch):
    state = "loaded"
    samples = 0
    commands = []

    def snapshot():
        nonlocal samples
        samples += 1
        return ResourceSnapshot(ram_pct=76 if samples == 1 else 40,
                                ram_available_bytes=(15 if samples == 1 else 40) * 1024**3,
                                gpu_memory_used_bytes=4 * 1024**3, gpu_memory_total_bytes=32 * 1024**3)

    async def runner(cmd):
        nonlocal state
        commands.append(cmd)
        if "ps" in cmd:
            if state == "loaded":
                return 0, SAMPLE_LMS_PS_LOADED, ""
            if state == "empty":
                return 0, "[]", ""
            return 0, json.dumps([{"identifier": "new", "modelKey": "new", "status": "idle", "contextLength": 16384}]), ""
        if "unload" in cmd:
            state = "empty"
            return 0, "", ""
        if "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 18 GiB\nEstimated Total Memory: 22 GiB", ""
        state = "new"
        return 0, "", ""

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", snapshot)
    await transition_model("new", allow_transitions=True, runner=runner,
                           expected_model_size_bytes=22 * 1024**3, poll_interval=0.001)
    assert sum("ps" in cmd for cmd in commands) >= 3


@pytest.mark.asyncio
async def test_unload_proceeds_when_inventory_is_empty_even_if_memory_percent_is_high(monkeypatch):
    state = "loaded"
    commands = []

    async def runner(cmd):
        nonlocal state
        commands.append(cmd)
        if "unload" in cmd:
            state = "empty"
        if "ps" in cmd:
            if state == "loaded":
                return 0, SAMPLE_LMS_PS_LOADED, ""
            if state == "new":
                item = dict(json.loads(SAMPLE_LMS_PS_LOADED)[0], modelKey="new", identifier="new",
                            contextLength=16384)
                return 0, json.dumps([item]), ""
            return 0, "[]", ""
        if "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 10 GiB\nEstimated Total Memory: 15 GiB", ""
        if "-y" in cmd:
            state = "new"
            return 0, "Loaded", ""
        return 0, "", ""

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=95, ram_available_bytes=20 * 1024**3, gpu_memory_used_bytes=0,
        gpu_memory_total_bytes=32 * 1024**3))
    await transition_model("new", allow_transitions=True, runner=runner,
                           unload_timeout=0.005, poll_interval=0.001)
    assert any("-y" in cmd for cmd in commands)
