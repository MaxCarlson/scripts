"""
Model inventory discovery, loaded model detection, and safe model transitions for LM Studio.

Provides safe inspection and authorized sequential model switching without blind retries.
All operations support dependency-injected command runners for hermetic offline testing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
import logging
import shutil
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

CommandRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


class ModelDiscoveryError(RuntimeError):
    """Raised when model inventory discovery fails."""


class ModelTransitionError(RuntimeError):
    """Raised when an authorized model transition fails or times out."""


class ModelTransitionNotAuthorizedError(RuntimeError):
    """Raised when a model transition is required but not explicitly authorized."""


@dataclass(frozen=True, slots=True)
class DownloadedModelInfo:
    """Metadata describing a model available on local disk."""

    model_key: str
    display_name: str
    architecture: str
    size_bytes: int
    quantization: str
    max_context_length: int
    format: str
    path: str
    trained_for_tool_use: bool = False
    model_type: str = "llm"

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "display_name": self.display_name,
            "architecture": self.architecture,
            "size_bytes": self.size_bytes,
            "quantization": self.quantization,
            "max_context_length": self.max_context_length,
            "format": self.format,
            "path": self.path,
            "trained_for_tool_use": self.trained_for_tool_use,
            "model_type": self.model_type,
        }

    @classmethod
    def from_lms_dict(cls, data: dict[str, Any]) -> DownloadedModelInfo:
        quant_info = data.get("quantization")
        quant_str = quant_info.get("name", "unknown") if isinstance(quant_info, dict) else str(quant_info or "unknown")
        return cls(
            model_key=data.get("modelKey", data.get("id", "")),
            display_name=data.get("displayName", data.get("modelKey", "")),
            architecture=str(data.get("architecture", "")),
            size_bytes=int(data.get("sizeBytes", 0) or 0),
            quantization=quant_str,
            max_context_length=int(data.get("maxContextLength", 0) or 0),
            format=str(data.get("format", "gguf")),
            path=str(data.get("path", "")),
            trained_for_tool_use=bool(data.get("trainedForToolUse", False)),
            model_type=str(data.get("type", "llm")),
        )


@dataclass(frozen=True, slots=True)
class LoadedModelInfo:
    """Metadata describing a model currently loaded into GPU/system memory."""

    identifier: str
    model_key: str
    display_name: str
    status: str
    context_length: int
    size_bytes: int
    max_context_length: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "model_key": self.model_key,
            "display_name": self.display_name,
            "status": self.status,
            "context_length": self.context_length,
            "size_bytes": self.size_bytes,
            "max_context_length": self.max_context_length,
        }

    @classmethod
    def from_lms_dict(cls, data: dict[str, Any]) -> LoadedModelInfo:
        return cls(
            identifier=data.get("identifier", data.get("modelKey", "")),
            model_key=data.get("modelKey", data.get("identifier", "")),
            display_name=data.get("displayName", data.get("identifier", "")),
            status=data.get("status", "unknown"),
            context_length=int(data.get("contextLength", 0) or 0),
            size_bytes=int(data.get("sizeBytes", 0) or 0),
            max_context_length=int(data.get("maxContextLength", 0) or 0),
        )


async def _default_cmd_runner(cmd: list[str]) -> tuple[int, str, str]:
    """Execute an external command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    return proc.returncode or 0, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")


async def list_downloaded_models(
    *,
    lms_path: str = "lms",
    runner: Optional[CommandRunner] = None,
    http_base_url: str = "http://127.0.0.1:1234",
) -> list[DownloadedModelInfo]:
    """
    Discover all downloaded local models.

    Prefers `lms ls --json` for rich metadata (quantization, context length, architecture).
    Gracefully falls back to LM Studio's `/v1/models` HTTP endpoint if `lms` is not installed.
    """
    cmd_exec = runner or _default_cmd_runner

    # Try lms CLI first if available or custom runner provided
    if runner is not None or shutil.which(lms_path) is not None:
        try:
            code, stdout, stderr = await cmd_exec([lms_path, "ls", "--json"])
            if code == 0 and stdout.strip():
                data = json.loads(stdout)
                if isinstance(data, list):
                    return [DownloadedModelInfo.from_lms_dict(item) for item in data if isinstance(item, dict)]
        except Exception as exc:
            logger.debug(f"lms ls command failed, falling back to HTTP: {exc}")

    # Fallback to HTTP endpoint
    try:
        async with httpx.AsyncClient(base_url=http_base_url, timeout=5.0) as client:
            resp = await client.get("/v1/models")
            if resp.status_code == 200:
                payload = resp.json()
                items = payload.get("data", [])
                models: list[DownloadedModelInfo] = []
                for it in items:
                    mid = it.get("id", "")
                    if mid:
                        models.append(
                            DownloadedModelInfo(
                                model_key=mid,
                                display_name=mid,
                                architecture="unknown",
                                size_bytes=0,
                                quantization="unknown",
                                max_context_length=0,
                                format="unknown",
                                path="",
                            )
                        )
                return models
    except Exception as exc:
        raise ModelDiscoveryError(
            f"Failed to discover downloaded models via lms CLI or HTTP endpoint: {exc}"
        ) from exc

    return []


async def get_loaded_models(
    *,
    lms_path: str = "lms",
    runner: Optional[CommandRunner] = None,
) -> list[LoadedModelInfo]:
    """
    Query currently loaded models in memory via `lms ps --json`.
    """
    cmd_exec = runner or _default_cmd_runner

    if runner is None and shutil.which(lms_path) is None:
        raise ModelDiscoveryError(f"CLI executable '{lms_path}' not found in PATH.")

    try:
        code, stdout, stderr = await cmd_exec([lms_path, "ps", "--json"])
        if code != 0:
            raise ModelDiscoveryError(f"lms ps failed (exit {code}): {stderr or stdout}")
        data = json.loads(stdout)
        if not isinstance(data, list):
            return []
        return [LoadedModelInfo.from_lms_dict(item) for item in data if isinstance(item, dict)]
    except json.JSONDecodeError as exc:
        raise ModelDiscoveryError(f"Malformed JSON from lms ps: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, ModelDiscoveryError):
            raise
        raise ModelDiscoveryError(f"Error querying loaded models: {exc}") from exc


async def get_loaded_model(
    *,
    lms_path: str = "lms",
    runner: Optional[CommandRunner] = None,
) -> Optional[LoadedModelInfo]:
    """
    Return the primary loaded model in memory, or None if no model is loaded.
    """
    loaded = await get_loaded_models(lms_path=lms_path, runner=runner)
    return loaded[0] if loaded else None


async def transition_model(
    target_model_key: str,
    *,
    allow_transitions: bool = False,
    lms_path: str = "lms",
    unload_timeout: float = 30.0,
    load_timeout: float = 120.0,
    poll_interval: float = 0.25,
    runner: Optional[CommandRunner] = None,
) -> LoadedModelInfo:
    """
    Safely transition the active GPU model in LM Studio.

    Safety Guarantees:
    1. If target is already loaded, returns immediately (no unload).
    2. If target is not loaded and allow_transitions=False, raises ModelTransitionNotAuthorizedError.
    3. If allow_transitions=True:
       - Unloads existing models via `lms unload -a`.
       - Polls until memory is released within unload_timeout.
       - Loads target model via `lms load <key> -y`.
       - Verifies target model is active and idle within load_timeout.
       - Halts immediately on any command or service failure without blind retries.
    """
    cmd_exec = runner or _default_cmd_runner

    if not target_model_key or not target_model_key.strip():
        raise ValueError("target_model_key must be a non-empty string")

    loaded_list = await get_loaded_models(lms_path=lms_path, runner=runner)
    for m in loaded_list:
        if m.model_key == target_model_key or m.identifier == target_model_key:
            return m

    # Model is not loaded. Check authorization.
    if not allow_transitions:
        current_id = loaded_list[0].identifier if loaded_list else "none"
        raise ModelTransitionNotAuthorizedError(
            f"Target model '{target_model_key}' is not loaded (current loaded: '{current_id}'). "
            "Model transitions are not authorized. Set allow_transitions=True or pass --allow-model-transitions."
        )

    # Authorized transition: unload current if any
    if loaded_list:
        code, stdout, stderr = await cmd_exec([lms_path, "unload", "-a"])
        if code != 0:
            raise ModelTransitionError(
                f"Failed to unload active model(s) (exit code {code}): {stderr or stdout}"
            )

        # Wait for VRAM/process stabilization
        start_unload = asyncio.get_running_loop().time()
        while True:
            remaining = await get_loaded_models(lms_path=lms_path, runner=runner)
            if not remaining:
                break
            if asyncio.get_running_loop().time() - start_unload > unload_timeout:
                raise ModelTransitionError(
                    f"Timed out waiting for VRAM/memory release after unload ({unload_timeout}s)."
                )
            await asyncio.sleep(poll_interval)

    # Load target model
    code, stdout, stderr = await cmd_exec([lms_path, "load", target_model_key, "-y"])
    if code != 0:
        raise ModelTransitionError(
            f"Failed to load model '{target_model_key}' (exit code {code}): {stderr or stdout}"
        )

    # Wait for target model to be ready
    start_load = asyncio.get_running_loop().time()
    while True:
        current_loaded = await get_loaded_models(lms_path=lms_path, runner=runner)
        for m in current_loaded:
            if m.model_key == target_model_key or m.identifier == target_model_key:
                return m
        if asyncio.get_running_loop().time() - start_load > load_timeout:
            raise ModelTransitionError(
                f"Timed out waiting for model '{target_model_key}' to become ready ({load_timeout}s)."
            )
        await asyncio.sleep(poll_interval)
