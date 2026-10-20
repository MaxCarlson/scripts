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
async def test_transition_model_blocks_preloaded_model_at_high_ram(monkeypatch) -> None:
    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(ram_pct=95.0))

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_LOADED, ""
        pytest.fail(f"High RAM must prevent dispatch or transition: {cmd}")

    with pytest.raises(ModelTransitionError, match="preloaded model.*95.0%"):
        await transition_model("qwen38-27b-q4km", allow_transitions=False, context_length=32768, runner=mock_runner)


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
            return 0, "Estimated GPU Memory: 18.0 GiB\nEstimated Total Memory: 22.0 GiB", ""
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


@pytest.mark.asyncio
async def test_transition_model_blocks_estimate_that_exceeds_gpu_headroom(monkeypatch) -> None:
    calls = []

    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        calls.append(cmd)
        if cmd == ["lms", "ps", "--json"]:
            return 0, SAMPLE_LMS_PS_EMPTY, ""
        if "--estimate-only" in cmd:
            return 0, "Estimated GPU Memory: 31 GiB\nEstimated Total Memory: 35 GiB", ""
        pytest.fail(f"Unsafe estimate must block actual load: {cmd}")

    monkeypatch.setattr(models_lifecycle, "collect_resource_snapshot", lambda: ResourceSnapshot(
        ram_pct=35, ram_available_bytes=40 * 1024**3,
        gpu_memory_used_bytes=0, gpu_memory_total_bytes=32 * 1024**3,
    ))
    with pytest.raises(ModelTransitionError, match="estimates 31.0 GiB GPU memory"):
        await transition_model("large-model", allow_transitions=True, context_length=16384, runner=mock_runner)
    assert not any("-y" in command for command in calls)


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
async def test_transition_model_stops_before_load_at_ram_safety_limit(monkeypatch) -> None:
    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, "[]", ""
        pytest.fail(f"No load should be attempted at high RAM usage: {cmd}")

    monkeypatch.setattr(
        "agent_benchmark.models_lifecycle.collect_resource_snapshot",
        lambda: ResourceSnapshot(ram_pct=91.0),
    )

    with pytest.raises(ModelTransitionError, match="RAM utilization is 91.0%.*safety limit 90%"):
        await transition_model("new-model", allow_transitions=True, runner=mock_runner)


@pytest.mark.asyncio
async def test_transition_model_requires_estimated_model_headroom(monkeypatch) -> None:
    async def mock_runner(cmd: list[str]) -> tuple[int, str, str]:
        if cmd == ["lms", "ps", "--json"]:
            return 0, "[]", ""
        pytest.fail(f"Insufficient headroom must block load: {cmd}")

    monkeypatch.setattr(
        "agent_benchmark.models_lifecycle.collect_resource_snapshot",
        lambda: ResourceSnapshot(ram_pct=75.0, ram_available_bytes=10 * 1024**3),
    )

    with pytest.raises(ModelTransitionError, match="at least 13421772800 bytes is required"):
        await transition_model(
            "large-model",
            allow_transitions=True,
            expected_model_size_bytes=10 * 1024**3,
            runner=mock_runner,
        )


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

