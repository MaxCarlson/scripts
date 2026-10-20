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
from pathlib import Path
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
    selected_variant: str | None = None
    variants: tuple[str, ...] = ()

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
            "selected_variant": self.selected_variant,
            "variants": list(self.variants),
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
            selected_variant=data.get("selectedVariant") if isinstance(data.get("selectedVariant"), str) else None,
            variants=tuple(value for value in data.get("variants", []) if isinstance(value, str))
            if isinstance(data.get("variants", []), list)
            else (),
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


@dataclass(frozen=True, slots=True)
class AvailableModelInfo:
    """Unified model metadata across local LM Studio, Gemini (via agy), and Codex CLIs."""

    provider: str
    model_key: str
    canonical_id: str
    display_name: str
    status: str
    description: str = ""
    architecture: str = ""
    quantization: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_key": self.model_key,
            "canonical_id": self.canonical_id,
            "display_name": self.display_name,
            "status": self.status,
            "description": self.description,
            "architecture": self.architecture,
            "quantization": self.quantization,
        }


DEFAULT_GEMINI_MODELS: tuple[tuple[str, str], ...] = (
    ("gemini-4-argon-medium", "Gemini 4 Argon (Medium)"),
    ("gemini-4-argon-high", "Gemini 4 Argon (High)"),
    ("gemini-4-argon-low", "Gemini 4 Argon (Low)"),
    ("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
    ("gemini-3.8-flash-medium", "Gemini 3.8 Flash (Medium)"),
    ("gemini-3.8-flash-low", "Gemini 3.8 Flash (Low)"),
)

DEFAULT_CODEX_MODELS: tuple[tuple[str, str, str], ...] = (
    ("gpt-6.1-sol", "GPT-6.1-Sol", "Latest workhorse model for coding and everyday work."),
    ("gpt-6-astra", "GPT-6-Astra", "Frontier intelligence for the most demanding work."),
    ("gpt-6-sol", "GPT-6-Sol", "Previous generation workhorse model."),
    ("gpt-6-luna", "GPT-6-Luna", "Fast and affordable model for easier tasks."),
    ("gpt-5.6-sol", "GPT-5.6-Sol", "Older generation workhorse model."),
    ("gpt-5.6-terra", "GPT-5.6-Terra", "Older balanced model for straightforward work."),
    ("gpt-5.6-luna", "GPT-5.6-Luna", "Older fast and efficient model."),
)

_GEMINI_ALIASES: dict[str, str] = {
    "gemini": "gemini-4-argon-medium",
    "gemini-4-argon": "gemini-4-argon-medium",
    "gemini-4-argon-medium": "gemini-4-argon-medium",
    "gemini-4-argon-high": "gemini-4-argon-high",
    "gemini-4-argon-low": "gemini-4-argon-low",
    "gemini-3.8-flash": "gemini-3.8-flash-high",
    "gemini-3.8-flash-high": "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium": "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low": "gemini-3.8-flash-low",
    "gemini-flash": "gemini-3.8-flash-high",
}

_CODEX_ALIASES: dict[str, str] = {
    "codex": "gpt-6.1-sol",
    "6.1-sol": "gpt-6.1-sol",
    "chatgpt-6.1-sol": "gpt-6.1-sol",
    "gpt-6.1-sol": "gpt-6.1-sol",
    "6-sol": "gpt-6-sol",
    "chatgpt-6-sol": "gpt-6-sol",
    "gpt-6-sol": "gpt-6-sol",
    "6-luna": "gpt-6-luna",
    "chatgpt-6-luna": "gpt-6-luna",
    "gpt-6-luna": "gpt-6-luna",
    "6-astra": "gpt-6-astra",
    "chatgpt-6-astra": "gpt-6-astra",
    "gpt-6-astra": "gpt-6-astra",
    "5.6-sol": "gpt-5.6-sol",
    "chatgpt-5.6-sol": "gpt-5.6-sol",
    "gpt-5.6-sol": "gpt-5.6-sol",
    "5.6-terra": "gpt-5.6-terra",
    "chatgpt-5.6-terra": "gpt-5.6-terra",
    "gpt-5.6-terra": "gpt-5.6-terra",
    "5.6-luna": "gpt-5.6-luna",
    "chatgpt-5.6-luna": "gpt-5.6-luna",
    "gpt-5.6-luna": "gpt-5.6-luna",
}


def resolve_model_provider_and_key(
    raw_model: str,
    default_provider: str = "lmstudio",
) -> tuple[str, str]:
    """
    Resolve a user-supplied model string into (provider, canonical_model_key).

    Supports explicit prefixes (`gemini/...`, `codex/...`, `lmstudio/...`) and
    friendly shorthand names (`gemini-3.8-flash`, `gemini-4-Argon`, `ChatGpt-6.1-sol`,
    `6-Astra`, `5.6-Terra`, etc.).
    """
    cleaned = raw_model.strip()
    if not cleaned:
        raise ValueError("Model identifier must not be empty")

    explicit_provider: Optional[str] = None
    if "/" in cleaned:
        prefix, rest = cleaned.split("/", 1)
        p_low = prefix.lower()
        if p_low in ("gemini", "agy"):
            explicit_provider = "gemini"
            cleaned = rest.strip()
        elif p_low in ("codex", "chatgpt", "openai"):
            explicit_provider = "codex"
            cleaned = rest.strip()
        elif p_low in ("lmstudio", "lms", "local"):
            explicit_provider = "lmstudio"
            cleaned = rest.strip()

    low = cleaned.lower()

    if explicit_provider == "gemini" or (explicit_provider is None and default_provider == "gemini"):
        return "gemini", _GEMINI_ALIASES.get(low, low)

    if explicit_provider == "codex" or (explicit_provider is None and default_provider == "codex"):
        if low in _CODEX_ALIASES:
            return "codex", _CODEX_ALIASES[low]
        norm = low.removeprefix("chatgpt-")
        if not norm.startswith("gpt-") and any(tok in norm for tok in ("sol", "luna", "terra", "astra")):
            norm = f"gpt-{norm}"
        return "codex", norm

    if explicit_provider == "lmstudio":
        return "lmstudio", cleaned

    # Auto-detect from model name when no provider prefix was given
    if low in _GEMINI_ALIASES or low.startswith("gemini") or "argon" in low:
        return "gemini", _GEMINI_ALIASES.get(low, low)

    if low in _CODEX_ALIASES or low.startswith(("gpt-", "chatgpt-")) or any(
        low.endswith(sfx) for sfx in ("-sol", "-luna", "-terra", "-astra")
    ):
        if low in _CODEX_ALIASES:
            return "codex", _CODEX_ALIASES[low]
        norm = low.removeprefix("chatgpt-")
        if not norm.startswith("gpt-"):
            norm = f"gpt-{norm}"
        return "codex", norm

    return default_provider, cleaned


async def list_gemini_models(
    *,
    agy_path: str = "agy",
    runner: Optional[CommandRunner] = None,
) -> list[AvailableModelInfo]:
    """
    Programmatically discover Gemini models available through the local `agy` CLI.
    Falls back to the canonical Gemini catalog if `agy` is unavailable.
    """
    cmd_exec = runner or _default_cmd_runner
    exe = agy_path if runner is not None else (shutil.which(agy_path) or agy_path)

    if runner is not None or shutil.which(agy_path) is not None:
        try:
            code, stdout, _ = await cmd_exec([exe, "models"])
            if code == 0 and stdout.strip():
                discovered: list[AvailableModelInfo] = []
                for line in stdout.splitlines():
                    line_s = line.strip()
                    if not line_s or line_s.lower().startswith("fetching"):
                        continue
                    parts = line_s.split("\t", 1)
                    m_key = parts[0].strip()
                    d_name = parts[1].strip() if len(parts) > 1 else m_key
                    if m_key.lower().startswith("gemini") or "argon" in m_key.lower():
                        discovered.append(
                            AvailableModelInfo(
                                provider="gemini",
                                model_key=m_key,
                                canonical_id=f"gemini/{m_key}",
                                display_name=d_name,
                                status="AVAILABLE (agy)",
                                architecture="gemini",
                            )
                        )
                if discovered:
                    return discovered
        except Exception as exc:
            logger.debug(f"agy models command failed, using fallback catalog: {exc}")

    return [
        AvailableModelInfo(
            provider="gemini",
            model_key=m_key,
            canonical_id=f"gemini/{m_key}",
            display_name=d_name,
            status="CATALOG (agy)",
            architecture="gemini",
        )
        for m_key, d_name in DEFAULT_GEMINI_MODELS
    ]


async def list_codex_models(
    *,
    cache_path: Optional[Path] = None,
) -> list[AvailableModelInfo]:
    """
    Programmatically discover Codex models from `~/.codex/models_cache.json`.
    Falls back to the canonical Codex model catalog if the cache file is absent.
    """
    target_cache = cache_path or (Path.home() / ".codex" / "models_cache.json")
    has_cli = shutil.which("codex") is not None
    status_label = "AVAILABLE (codex)" if has_cli else "CATALOG (codex)"

    if target_cache.is_file():
        try:
            raw = json.loads(target_cache.read_text(encoding="utf-8"))
            models_list = raw.get("models", [])
            discovered: list[AvailableModelInfo] = []
            for item in models_list:
                if not isinstance(item, dict):
                    continue
                slug = str(item.get("slug") or "").strip()
                if not slug or slug == "codex-auto-review":
                    continue
                d_name = str(item.get("display_name") or slug).strip()
                desc = str(item.get("description") or "").strip()
                discovered.append(
                    AvailableModelInfo(
                        provider="codex",
                        model_key=slug,
                        canonical_id=f"codex/{slug}",
                        display_name=d_name,
                        status=status_label,
                        description=desc,
                        architecture="gpt",
                    )
                )
            if discovered:
                return discovered
        except Exception as exc:
            logger.debug(f"Failed reading codex models_cache.json, using fallback catalog: {exc}")

    return [
        AvailableModelInfo(
            provider="codex",
            model_key=slug,
            canonical_id=f"codex/{slug}",
            display_name=d_name,
            status=status_label,
            description=desc,
            architecture="gpt",
        )
        for slug, d_name, desc in DEFAULT_CODEX_MODELS
    ]


async def list_all_available_models(
    *,
    provider: str = "all",
    lms_path: str = "lms",
    agy_path: str = "agy",
    codex_cache_path: Optional[Path] = None,
    runner: Optional[CommandRunner] = None,
    http_base_url: str = "http://127.0.0.1:1234",
) -> list[AvailableModelInfo]:
    """Return available models across requested provider(s) ('all', 'lmstudio', 'gemini', 'codex')."""
    results: list[AvailableModelInfo] = []
    prov = provider.lower().strip()

    if prov in ("all", "gemini", "agy"):
        results.extend(await list_gemini_models(agy_path=agy_path, runner=runner))

    if prov in ("all", "codex", "openai", "chatgpt"):
        results.extend(await list_codex_models(cache_path=codex_cache_path))

    if prov in ("all", "lmstudio", "lms", "local"):
        try:
            downloaded = await list_downloaded_models(
                lms_path=lms_path, runner=runner, http_base_url=http_base_url
            )
            try:
                loaded = await get_loaded_models(lms_path=lms_path, runner=runner)
                loaded_keys = {m.model_key for m in loaded} | {m.identifier for m in loaded}
            except Exception:
                loaded_keys = set()
            for m in downloaded:
                st = "LOADED (active)" if m.model_key in loaded_keys else "DOWNLOADED"
                results.append(
                    AvailableModelInfo(
                        provider="lmstudio",
                        model_key=m.model_key,
                        canonical_id=f"lmstudio/{m.model_key}",
                        display_name=m.display_name,
                        status=st,
                        architecture=m.architecture,
                        quantization=m.quantization,
                    )
                )
        except Exception as exc:
            if prov != "all":
                raise
            logger.debug(f"LM Studio model discovery skipped in 'all' mode: {exc}")

    return results

