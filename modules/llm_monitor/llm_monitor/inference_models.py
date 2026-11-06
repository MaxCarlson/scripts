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
    loaded_instance_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ModelInventoryEntry:
        return cls(
            server_instance_id=str(payload.get("server_instance_id", "")),
            provider_model_id=str(payload.get("provider_model_id", "")),
            name=str(payload.get("name", "")),
            state=str(payload.get("state", "unknown")),
            loaded_instance_count=payload.get("loaded_instance_count"),
            context_length=payload.get("context_length"),
            loaded_context_lengths=tuple(payload.get("loaded_context_lengths", ())),
            max_context_length=payload.get("max_context_length"),
            quantization=payload.get("quantization"),
            model_instance_id=payload.get("model_instance_id"),
            identity_quality=str(payload.get("identity_quality", "provider_model_id_only")),
            context_source=str(payload.get("context_source", "unavailable")),
            loaded_instance_ids=tuple(payload.get("loaded_instance_ids", ())),
        )


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
class HardwareSample:
    sample_id: int
    timestamp: str
    timestamp_monotonic: float
    device_id: str
    device_name: str
    source: str
    gpu_utilization_percent: float | None = None
    memory_controller_utilization_percent: float | None = None
    vram_used_bytes: float | None = None
    vram_total_bytes: float | None = None
    temperature_celsius: float | None = None
    power_watts: float | None = None
    validity: str = "valid"
    error: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HardwareSample:
        return cls(
            sample_id=int(payload.get("sample_id", 0)),
            timestamp=str(payload.get("timestamp", "")),
            timestamp_monotonic=float(payload.get("timestamp_monotonic", 0.0)),
            device_id=str(payload.get("device_id", "unknown")),
            device_name=str(payload.get("device_name", "Unknown GPU")),
            source=str(payload.get("source", "unknown")),
            gpu_utilization_percent=_optional_float(payload.get("gpu_utilization_percent")),
            memory_controller_utilization_percent=_optional_float(payload.get("memory_controller_utilization_percent")),
            vram_used_bytes=_optional_float(payload.get("vram_used_bytes")),
            vram_total_bytes=_optional_float(payload.get("vram_total_bytes")),
            temperature_celsius=_optional_float(payload.get("temperature_celsius")),
            power_watts=_optional_float(payload.get("power_watts")),
            validity=str(payload.get("validity", "valid")),
            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "timestamp": self.timestamp,
            "timestamp_monotonic": self.timestamp_monotonic,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "source": self.source,
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "memory_controller_utilization_percent": self.memory_controller_utilization_percent,
            "vram_used_bytes": self.vram_used_bytes,
            "vram_total_bytes": self.vram_total_bytes,
            "temperature_celsius": self.temperature_celsius,
            "power_watts": self.power_watts,
            "validity": self.validity,
            "error": self.error,
        }


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
    client_model_id: str | None = None
    resolved_model_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    started_monotonic: float | None = None
    ended_monotonic: float | None = None
    input_tokens: int | None = None
    reasoning_tokens: int | None = None
    output_tokens: int | None = None
    generated_tokens: int | None = None
    usage_source: str | None = None
    finish_reason: str | None = None
    elapsed_seconds: float | None = None
    time_to_first_text_seconds: float | None = None
    time_to_first_text_source: str | None = None
    generation_tokens_per_second: float | None = None
    generation_speed_source: str | None = None
    gpu_average_percent: float | None = None
    gpu_peak_vram_bytes: float | None = None
    gpu_scope: str | None = None
    hardware_telemetry: dict[str, Any] | None = None
    coverage: dict[str, str] = field(default_factory=dict)
    benchmark_correlation: dict[str, Any] | None = None
    content: tuple[ContentSegment, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> InferenceRequest:
        content = payload.get("content")
        coverage = payload.get("coverage")
        hw_tel = payload.get("hardware_telemetry")
        return cls(
            request_id=str(payload["request_id"]),
            server_instance_id=str(payload["server_instance_id"]),
            source=str(payload.get("source", "unknown")),
            state=str(payload.get("state", "observed")),
            provider_model_id=payload.get("provider_model_id") if isinstance(payload.get("provider_model_id"), str) else None,
            model_name=payload.get("model_name") if isinstance(payload.get("model_name"), str) else None,
            model_instance_id=payload.get("model_instance_id") if isinstance(payload.get("model_instance_id"), str) else None,
            provider_request_id=payload.get("provider_request_id") if isinstance(payload.get("provider_request_id"), str) else None,
            client_model_id=payload.get("client_model_id") if isinstance(payload.get("client_model_id"), str) else None,
            resolved_model_id=payload.get("resolved_model_id") if isinstance(payload.get("resolved_model_id"), str) else None,
            started_at=payload.get("started_at") if isinstance(payload.get("started_at"), str) else None,
            ended_at=payload.get("ended_at") if isinstance(payload.get("ended_at"), str) else None,
            started_monotonic=_optional_float(payload.get("started_monotonic")),
            ended_monotonic=_optional_float(payload.get("ended_monotonic")),
            input_tokens=_optional_count(payload.get("input_tokens")),
            reasoning_tokens=_optional_count(payload.get("reasoning_tokens")),
            output_tokens=_optional_count(payload.get("output_tokens")),
            generated_tokens=_optional_count(payload.get("generated_tokens")),
            usage_source=payload.get("usage_source") if isinstance(payload.get("usage_source"), str) else None,
            finish_reason=payload.get("finish_reason") if isinstance(payload.get("finish_reason"), str) else None,
            elapsed_seconds=_optional_float(payload.get("elapsed_seconds")),
            time_to_first_text_seconds=_optional_float(payload.get("time_to_first_text_seconds")),
            time_to_first_text_source=payload.get("time_to_first_text_source") if isinstance(payload.get("time_to_first_text_source"), str) else None,
            generation_tokens_per_second=_optional_float(payload.get("generation_tokens_per_second")),
            generation_speed_source=payload.get("generation_speed_source") if isinstance(payload.get("generation_speed_source"), str) else None,
            gpu_average_percent=_optional_float(payload.get("gpu_average_percent")),
            gpu_peak_vram_bytes=_optional_float(payload.get("gpu_peak_vram_bytes")),
            gpu_scope=payload.get("gpu_scope") if isinstance(payload.get("gpu_scope"), str) else None,
            hardware_telemetry=dict(hw_tel) if isinstance(hw_tel, dict) else None,
            coverage={str(key): str(value) for key, value in coverage.items()} if isinstance(coverage, dict) else {},
            benchmark_correlation=dict(payload["benchmark_correlation"]) if isinstance(payload.get("benchmark_correlation"), dict) else None,
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
            "client_model_id": self.client_model_id,
            "resolved_model_id": self.resolved_model_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "started_monotonic": self.started_monotonic,
            "ended_monotonic": self.ended_monotonic,
            "input_tokens": self.input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "output_tokens": self.output_tokens,
            "generated_tokens": self.generated_tokens,
            "usage_source": self.usage_source,
            "finish_reason": self.finish_reason,
            "elapsed_seconds": self.elapsed_seconds,
            "time_to_first_text_seconds": self.time_to_first_text_seconds,
            "time_to_first_text_source": self.time_to_first_text_source,
            "generation_tokens_per_second": self.generation_tokens_per_second,
            "generation_speed_source": self.generation_speed_source,
            "gpu_average_percent": self.gpu_average_percent,
            "gpu_peak_vram_bytes": self.gpu_peak_vram_bytes,
            "gpu_scope": self.gpu_scope,
            "hardware_telemetry": self.hardware_telemetry,
            "coverage": dict(self.coverage),
            "benchmark_correlation": self.benchmark_correlation,
            "content": [segment.to_dict() for segment in self.content],
        }


def _optional_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
        return parsed if (not parsed != parsed) else None
    except (TypeError, ValueError):
        return None
