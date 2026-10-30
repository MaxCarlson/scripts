"""Typed, privacy-aware data contracts for inference observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CapabilityState = Literal["available", "rendered_only", "streaming", "completion_only", "unavailable"]


@dataclass(frozen=True)
class Capability:
    state: CapabilityState
    source: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CaptureCapabilities:
    model_inventory: Capability
    aggregate_metrics: Capability
    request_lifecycle: Capability
    structured_input: Capability
    reasoning_text: Capability
    output_text: Capability
    token_usage: Capability
    request_timing: Capability
    gpu_samples: Capability
    historical_content: Capability

    @classmethod
    def passive_inventory(cls, *, available: bool = True) -> CaptureCapabilities:
        inventory = Capability(
            "available" if available else "unavailable",
            "lmstudio_model_inventory",
            None if available else "LM Studio model inventory is unavailable.",
        )
        unavailable = Capability("unavailable", "not_collected", "No supported source is connected in this phase.")
        return cls(
            model_inventory=inventory,
            aggregate_metrics=unavailable,
            request_lifecycle=unavailable,
            structured_input=unavailable,
            reasoning_text=unavailable,
            output_text=unavailable,
            token_usage=unavailable,
            request_timing=unavailable,
            gpu_samples=unavailable,
            historical_content=unavailable,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelInventoryEntry:
    server_instance_id: str
    provider_model_id: str
    name: str
    state: str
    loaded_instance_count: int | None = None
    context_length: int | None = None
    loaded_context_lengths: tuple[int, ...] = ()
    max_context_length: int | None = None
    quantization: str | None = None
    model_instance_id: str | None = None
    identity_quality: str = "provider_model_id_only"
    context_source: str = "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContentSegment:
    kind: str
    text: str | None = None
    role: str | None = None
    observed_at: str | None = None
    content_type: str = "text/plain"
    source: str = "unknown"
    sequence: int | None = None
    truncated: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ContentSegment:
        return cls(
            kind=str(payload.get("kind", "other")),
            text=payload.get("text") if isinstance(payload.get("text"), str) else None,
            role=payload.get("role") if isinstance(payload.get("role"), str) else None,
            observed_at=payload.get("observed_at") if isinstance(payload.get("observed_at"), str) else None,
            content_type=str(payload.get("content_type", "text/plain")),
            source=str(payload.get("source", "unknown")),
            sequence=payload.get("sequence") if isinstance(payload.get("sequence"), int) else None,
            truncated=payload.get("truncated") is True,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InferenceRequest:
    request_id: str
    server_instance_id: str
    source: str
    state: str
    provider_model_id: str | None = None
    model_name: str | None = None
    model_instance_id: str | None = None
    provider_request_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    input_tokens: int | None = None
    reasoning_tokens: int | None = None
    output_tokens: int | None = None
    generated_tokens: int | None = None
    usage_source: str | None = None
    finish_reason: str | None = None
    elapsed_seconds: float | None = None
    coverage: dict[str, str] = field(default_factory=dict)
    content: tuple[ContentSegment, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InferenceRequest:
        content = payload.get("content")
        coverage = payload.get("coverage")
        return cls(
            request_id=str(payload["request_id"]),
            server_instance_id=str(payload["server_instance_id"]),
            source=str(payload.get("source", "unknown")),
            state=str(payload.get("state", "observed")),
            provider_model_id=payload.get("provider_model_id") if isinstance(payload.get("provider_model_id"), str) else None,
            model_name=payload.get("model_name") if isinstance(payload.get("model_name"), str) else None,
            model_instance_id=payload.get("model_instance_id") if isinstance(payload.get("model_instance_id"), str) else None,
            provider_request_id=payload.get("provider_request_id") if isinstance(payload.get("provider_request_id"), str) else None,
            started_at=payload.get("started_at") if isinstance(payload.get("started_at"), str) else None,
            ended_at=payload.get("ended_at") if isinstance(payload.get("ended_at"), str) else None,
            input_tokens=_optional_count(payload.get("input_tokens")),
            reasoning_tokens=_optional_count(payload.get("reasoning_tokens")),
            output_tokens=_optional_count(payload.get("output_tokens")),
            generated_tokens=_optional_count(payload.get("generated_tokens")),
            usage_source=payload.get("usage_source") if isinstance(payload.get("usage_source"), str) else None,
            finish_reason=payload.get("finish_reason") if isinstance(payload.get("finish_reason"), str) else None,
            elapsed_seconds=payload.get("elapsed_seconds") if isinstance(payload.get("elapsed_seconds"), (int, float)) else None,
            coverage={str(key): str(value) for key, value in coverage.items()} if isinstance(coverage, dict) else {},
            content=tuple(ContentSegment.from_dict(item) for item in content if isinstance(item, dict))
            if isinstance(content, list) else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "server_instance_id": self.server_instance_id,
            "model_instance_id": self.model_instance_id,
            "provider_request_id": self.provider_request_id,
            "source": self.source,
            "state": self.state,
            "provider_model_id": self.provider_model_id,
            "model_name": self.model_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "input_tokens": self.input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "output_tokens": self.output_tokens,
            "generated_tokens": self.generated_tokens,
            "usage_source": self.usage_source,
            "finish_reason": self.finish_reason,
            "elapsed_seconds": self.elapsed_seconds,
            "coverage": dict(self.coverage),
            "content": [segment.to_dict() for segment in self.content],
        }


def _optional_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
