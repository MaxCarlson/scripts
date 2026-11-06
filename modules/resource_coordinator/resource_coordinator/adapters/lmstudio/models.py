"""Supported LM Studio native v1 REST operations used for safe model offload/restore."""

from __future__ import annotations

from typing import Any, Dict, List

import httpx


class NativeModelController:
    _LOAD_OPTIONS = {
        "context_length", "eval_batch_size", "flash_attention", "num_experts", "offload_kv_cache_to_gpu"
    }

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def snapshot_loaded(self) -> List[Dict[str, Any]]:
        response = await self.client.get("/api/v1/models")
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise RuntimeError("LM Studio model list response is malformed")
        snapshot: List[Dict[str, Any]] = []
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("key"), str):
                raise RuntimeError("LM Studio model entry is malformed")
            instances = model.get("loaded_instances", [])
            if not isinstance(instances, list):
                raise RuntimeError("LM Studio loaded instance list is malformed")
            for instance in instances:
                if not isinstance(instance, dict) or not isinstance(instance.get("id"), str):
                    raise RuntimeError("LM Studio loaded instance identity is missing")
                config = instance.get("config", {})
                if not isinstance(config, dict):
                    raise RuntimeError("LM Studio loaded instance config is malformed")
                snapshot.append({"model": model["key"], "instance_id": instance["id"],
                                 "type": model.get("type", "llm"), "config": dict(config)})
        return snapshot

    async def unload(self, snapshot: List[Dict[str, Any]]) -> None:
        for instance in snapshot:
            response = await self.client.post("/api/v1/models/unload", json={"instance_id": instance["instance_id"]})
            response.raise_for_status()
        remaining = await self.snapshot_loaded()
        removed = {item["instance_id"] for item in snapshot}
        if any(item["instance_id"] in removed for item in remaining):
            raise RuntimeError("LM Studio still reports a gaming-target model instance loaded")

    async def unload_all(self) -> List[Dict[str, Any]]:
        snapshot = await self.snapshot_loaded()
        await self.unload(snapshot)
        return [{"model": item["model"], "type": item["type"], "config": item["config"]} for item in snapshot]

    async def restore(self, snapshot: List[Dict[str, Any]]) -> None:
        currently_loaded = await self.snapshot_loaded()
        loaded_models = {item["model"] for item in currently_loaded}
        for item in snapshot:
            model, config = item.get("model"), item.get("config", {})
            if not isinstance(model, str) or not model or not isinstance(config, dict):
                raise RuntimeError("Persisted gaming model snapshot is malformed")
            if model in loaded_models:
                continue
            body: Dict[str, Any] = {"model": model, **{key: value for key, value in config.items()
                                                        if key in self._LOAD_OPTIONS}}
            response = await self.client.post("/api/v1/models/load", json=body)
            response.raise_for_status()
            loaded_models.add(model)
        final = await self.snapshot_loaded()
        final_models = {item["model"] for item in final}
        missing = {str(item.get("model")) for item in snapshot} - final_models
        if missing:
            raise RuntimeError(f"LM Studio failed to restore model(s): {', '.join(sorted(missing))}")
