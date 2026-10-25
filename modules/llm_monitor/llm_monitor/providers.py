"""Read-only provider metadata adapters with conservative context semantics."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .opencode import ApiResult


def extract_opencode_model_limits(
    payload: Any, model_id: str, *, provider_id: str | None = None
) -> dict[str, Any] | None:
    root = payload.get("data", payload) if isinstance(payload, dict) else None
    providers = root.get("providers") if isinstance(root, dict) else None
    if not isinstance(providers, list):
        return None
    matches = []
    for provider in providers:
        if not isinstance(provider, dict) or not isinstance(provider.get("models"), dict):
            continue
        current_provider = provider.get("id")
        model = provider["models"].get(model_id)
        if not isinstance(model, dict):
            continue
        if provider_id and current_provider != provider_id:
            continue
        limit = model.get("limit") if isinstance(model.get("limit"), dict) else {}
        matches.append(
            {
                "provider_id": current_provider if isinstance(current_provider, str) else None,
                "model_id": model_id,
                "context": _positive(limit.get("context")),
                "output": _positive(limit.get("output")),
                "source": "opencode_config_providers",
            }
        )
    if provider_id:
        return matches[0] if matches else None
    return matches[0] if len(matches) == 1 else None


class LMStudioClient:
    """Read loaded model metadata; never calls inference or load/unload endpoints."""

    def __init__(self, base_url: str = "http://127.0.0.1:1234", *, timeout: float = 2.0,
                 api_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_token = api_token

    def get_json(self, path: str) -> ApiResult:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        try:
            with urlopen(Request(self.base_url + path, headers=headers, method="GET"), timeout=self.timeout) as response:
                return ApiResult(json.loads(response.read().decode("utf-8")), status_code=response.status)
        except HTTPError as exc:
            return ApiResult(error=f"HTTP {exc.code}", status_code=exc.code)
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ApiResult(error=f"{type(exc).__name__}: {exc}")

    def list_models(self) -> list[dict[str, Any]]:
        v1 = self.get_json("/api/v1/models")
        if v1.error is None:
            data = v1.data.get("models", v1.data.get("data")) if isinstance(v1.data, dict) else None
            if isinstance(data, list):
                return [_normalize_v1_model(item) for item in data if isinstance(item, dict)]
        v0 = self.get_json("/api/v0/models")
        data = v0.data.get("data") if isinstance(v0.data, dict) else None
        if v0.error is None and isinstance(data, list):
            return [_normalize_v0_model(item) for item in data if isinstance(item, dict)]
        if v1.error:
            raise RuntimeError(v1.error)
        raise RuntimeError(v0.error or "LM Studio returned an unsupported models response")


def _normalize_v1_model(model: dict[str, Any]) -> dict[str, Any]:
    loaded_instances = model.get("loaded_instances")
    if not isinstance(loaded_instances, list):
        loaded_instances = []
    contexts = []
    for instance in loaded_instances:
        if not isinstance(instance, dict):
            continue
        config = instance.get("config") if isinstance(instance.get("config"), dict) else {}
        context = _positive(config.get("context_length"))
        if context is not None:
            contexts.append(context)
    unique_contexts = sorted(set(contexts))
    identifier = model.get("key") or model.get("id") or model.get("model_key")
    return {
        "id": identifier if isinstance(identifier, str) else None,
        "state": "loaded" if loaded_instances else "not-loaded",
        "context_length": unique_contexts[0] if len(unique_contexts) == 1 else None,
        "loaded_context_lengths": unique_contexts,
        "loaded_instance_count": len(loaded_instances),
        "max_context_length": _positive(model.get("max_context_length")),
        "context_source": "loaded_instance_config" if len(unique_contexts) == 1 else "unavailable",
        "api_version": "v1",
    }


def _normalize_v0_model(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": model.get("id") if isinstance(model.get("id"), str) else None,
        "state": model.get("state") if isinstance(model.get("state"), str) else None,
        "context_length": None,
        "loaded_context_lengths": [],
        "loaded_instance_count": None,
        "max_context_length": _positive(model.get("max_context_length")),
        "context_source": "model_maximum_only" if model.get("max_context_length") else "unavailable",
        "api_version": "v0",
    }


def _positive(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return value
