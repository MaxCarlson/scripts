"""Exact model identity resolution and isolated OpenCode registration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import httpx

from .models_lifecycle import DownloadedModelInfo, list_downloaded_models


class ModelIdentityError(ValueError):
    """A requested model cannot be mapped to one exact installed LM Studio key."""


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    requested_id: str
    provider: str
    runtime_model_id: str
    lms_model_key: str
    display_name: str
    quantization: str
    selected_variant: str | None = None
    available_variants: tuple[str, ...] = ()
    max_context_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_id": self.requested_id,
            "provider": self.provider,
            "runtime_model_id": self.runtime_model_id,
            "lms_model_key": self.lms_model_key,
            "display_name": self.display_name,
            "quantization": self.quantization,
            "selected_variant": self.selected_variant,
            "available_variants": list(self.available_variants),
            "max_context_length": self.max_context_length,
            "resolution": "exact_model_key",
        }


def resolve_lmstudio_identity(requested_id: str, inventory: list[DownloadedModelInfo]) -> ModelIdentity:
    """Resolve only an exact LM Studio modelKey; display names are never aliases."""
    matches = [item for item in inventory if item.model_type.lower() == "llm" and item.model_key == requested_id]
    if not matches:
        available = sorted({item.model_key for item in inventory if item.model_type.lower() == "llm" and item.model_key})
        hint = " Use a downloaded LM Studio model key; OpenCode model names are display labels, not ID mappings."
        if requested_id in {"qwen38_17GB", "qwen38_23GB"}:
            hint += " This OpenCode alias is not an LM Studio model key on this machine."
        raise ModelIdentityError(
            f"Model '{requested_id}' is unavailable: no exact LM Studio model key matched. "
            f"Available keys: {', '.join(available) or '(none)'}.{hint}"
        )
    if len(matches) != 1:
        variants = ", ".join(sorted({item.quantization for item in matches}))
        raise ModelIdentityError(
            f"Model key '{requested_id}' is ambiguous in LM Studio inventory ({variants or 'multiple records'}); "
            "select an explicit model key for the intended quantization."
        )
    item = matches[0]
    return ModelIdentity(
        requested_id=requested_id,
        provider="lmstudio",
        runtime_model_id=item.model_key,
        lms_model_key=item.model_key,
        display_name=item.display_name,
        quantization=item.quantization,
        selected_variant=item.selected_variant,
        available_variants=item.variants,
        max_context_length=item.max_context_length,
    )


def model_readiness(
    requested_id: str,
    inventory: list[DownloadedModelInfo],
    configured_model_ids: set[str] | None,
    *,
    provider_connected: bool | None = True,
) -> dict[str, Any]:
    """Describe whether a plan can run directly, needs isolated registration, or cannot resolve."""
    try:
        identity = resolve_lmstudio_identity(requested_id, inventory)
    except ModelIdentityError as error:
        status = "ambiguous" if "ambiguous" in str(error).lower() else "unavailable"
        return {"requested_id": requested_id, "status": status, "reason": str(error), "identity": None}
    if provider_connected is False:
        return {"requested_id": requested_id, "status": "unavailable",
                "reason": "OpenCode LM Studio provider is not connected; inspect local service readiness.",
                "identity": identity.to_dict()}
    if configured_model_ids is None or provider_connected is None:
        return {"requested_id": requested_id, "status": "unknown",
                "reason": "OpenCode provider readiness could not be verified; plan is expanded but run readiness is unknown.",
                "identity": identity.to_dict()}
    registered = configured_model_ids is not None and identity.runtime_model_id in configured_model_ids
    return {
        "requested_id": requested_id,
        "status": "runnable" if registered else "registration_required",
        "reason": (
            "Exact model ID is already visible to OpenCode."
            if registered and provider_connected is True
            else "The exact downloaded ID will be registered in the isolated trial project config."
            if provider_connected is not False
            else "OpenCode LM Studio provider is not connected; inspect local service readiness."
        ),
        "registration_scope": "existing effective config" if registered else "isolated trial project",
        "identity": identity.to_dict(),
    }


async def discover_lmstudio_identity(requested_id: str, *, lms_path: str = "lms", runner=None) -> ModelIdentity:
    """Resolve against the live, read-only LM Studio downloaded-model inventory."""
    inventory = await list_downloaded_models(lms_path=lms_path, runner=runner)
    return resolve_lmstudio_identity(requested_id, inventory)


async def get_effective_lmstudio_model_ids(
    base_url: str, *, directory: Path, request_seconds: float = 5
) -> tuple[set[str], bool] | None:
    """Read the effective OpenCode provider catalog for a directory; never writes config."""
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    auth = (os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"), password) if password else None
    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=request_seconds, auth=auth, trust_env=False
        ) as client:
            response = await client.get("/provider", headers={"x-opencode-directory": str(directory.resolve())})
            response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("all"), list):
        return None
    entry = next((item for item in payload["all"] if isinstance(item, dict) and item.get("id") == "lmstudio"), None)
    if entry is None:
        return set(), False
    models = entry.get("models", {})
    if not isinstance(models, dict) or any(not isinstance(key, str) for key in models):
        return None
    connected = payload.get("connected", [])
    return set(models), isinstance(connected, list) and "lmstudio" in connected


def write_project_model_registration(directory: Path, identity: ModelIdentity) -> Path:
    """Add one exact runtime ID to a trial project's config without changing other config."""
    if identity.provider != "lmstudio" or identity.runtime_model_id != identity.lms_model_key:
        raise ModelIdentityError("Isolated registration requires an exact LM Studio key as the OpenCode model ID")
    if "/" in identity.runtime_model_id and identity.runtime_model_id.strip("/") != identity.runtime_model_id:
        raise ModelIdentityError("Model ID contains an invalid path-like separator")

    target = directory / "opencode.json"
    jsonc = directory / "opencode.jsonc"
    if jsonc.exists():
        raise ModelIdentityError("Cannot safely add a model to an existing opencode.jsonc project config; JSONC is preserved")
    if target.exists():
        try:
            original = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ModelIdentityError(f"Cannot safely merge existing OpenCode project config: {error}") from error
        if not isinstance(original, dict):
            raise ModelIdentityError("Cannot safely merge existing OpenCode project config: root must be an object")
        config: dict[str, Any] = original
    else:
        config = {"$schema": "https://opencode.ai/config.json"}

    provider = config.setdefault("provider", {})
    if not isinstance(provider, dict):
        raise ModelIdentityError("Cannot safely merge project config: provider must be an object")
    lmstudio = provider.setdefault("lmstudio", {})
    if not isinstance(lmstudio, dict):
        raise ModelIdentityError("Cannot safely merge project config: provider.lmstudio must be an object")
    models = lmstudio.setdefault("models", {})
    if not isinstance(models, dict):
        raise ModelIdentityError("Cannot safely merge project config: provider.lmstudio.models must be an object")
    if identity.runtime_model_id in models:
        existing = models[identity.runtime_model_id]
        if isinstance(existing, dict) and existing.get("id") not in (None, identity.runtime_model_id):
            raise ModelIdentityError(
                f"Existing OpenCode model '{identity.runtime_model_id}' declares a different backend ID; refusing ambiguity"
            )
        return target
    models[identity.runtime_model_id] = {"name": identity.display_name or identity.runtime_model_id}

    payload = (json.dumps(config, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=".opencode-model-", suffix=".tmp", dir=directory)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)
    return target
