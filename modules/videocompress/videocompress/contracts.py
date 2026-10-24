"""
Typed domain contracts and persistent schemas for videocompress.
Follows INTEGRATION_CONTRACTS.md and MEDIA_SAFETY_CONTRACT.md.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Canonical filesystem identity and fingerprint for a source media asset."""

    scope_id: str
    relative_path: str
    canonical_path: str
    stat_fingerprint: str
    fingerprint_method: str = "stat_mtime_size"
    strong_digest: str | None = None
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SourceIdentity:
        return cls(
            scope_id=str(data["scope_id"]),
            relative_path=str(data["relative_path"]),
            canonical_path=str(data["canonical_path"]),
            stat_fingerprint=str(data["stat_fingerprint"]),
            fingerprint_method=str(data.get("fingerprint_method", "stat_mtime_size")),
            strong_digest=data.get("strong_digest"),
            observed_at=data.get("observed_at"),
        )


@dataclass(frozen=True, slots=True)
class VideoStream:
    """Detailed metadata for a single stream within a media container."""

    stream_index: int
    stream_type: str  # video, audio, subtitle, attachment, data
    codec_name: str
    bit_rate_bps: int | None = None
    bitrate_provenance: str = "missing"  # ffprobe_stream, ffprobe_format, estimated, measured, missing
    profile: str | None = None
    level: int | None = None
    width: int | None = None
    height: int | None = None
    sample_aspect_ratio: str | None = None
    display_aspect_ratio: str | None = None
    rotation_degrees: int = 0
    fps_num: int | None = None
    fps_den: int | None = None
    duration_seconds: float | None = None
    pix_fmt: str | None = None
    bit_depth: int | None = None
    color_range: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    color_space: str | None = None
    is_hdr: bool = False
    is_attached_pic: bool = False
    channels: int | None = None
    channel_layout: str | None = None
    sample_rate: int | None = None
    language: str | None = None
    title: str | None = None
    disposition: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["disposition"] = dict(self.disposition)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VideoStream:
        return cls(
            stream_index=int(data["stream_index"]),
            stream_type=str(data["stream_type"]),
            codec_name=str(data["codec_name"]),
            bit_rate_bps=int(data["bit_rate_bps"]) if data.get("bit_rate_bps") is not None else None,
            bitrate_provenance=str(data.get("bitrate_provenance", "missing")),
            profile=data.get("profile"),
            level=int(data["level"]) if data.get("level") is not None else None,
            width=int(data["width"]) if data.get("width") is not None else None,
            height=int(data["height"]) if data.get("height") is not None else None,
            sample_aspect_ratio=data.get("sample_aspect_ratio"),
            display_aspect_ratio=data.get("display_aspect_ratio"),
            rotation_degrees=int(data.get("rotation_degrees", 0)),
            fps_num=int(data["fps_num"]) if data.get("fps_num") is not None else None,
            fps_den=int(data["fps_den"]) if data.get("fps_den") is not None else None,
            duration_seconds=float(data["duration_seconds"]) if data.get("duration_seconds") is not None else None,
            pix_fmt=data.get("pix_fmt"),
            bit_depth=int(data["bit_depth"]) if data.get("bit_depth") is not None else None,
            color_range=data.get("color_range"),
            color_primaries=data.get("color_primaries"),
            color_transfer=data.get("color_transfer"),
            color_space=data.get("color_space"),
            is_hdr=bool(data.get("is_hdr", False)),
            is_attached_pic=bool(data.get("is_attached_pic", False)),
            channels=int(data["channels"]) if data.get("channels") is not None else None,
            channel_layout=data.get("channel_layout"),
            sample_rate=int(data["sample_rate"]) if data.get("sample_rate") is not None else None,
            language=data.get("language"),
            title=data.get("title"),
            disposition=dict(data.get("disposition", {})),
        )


@dataclass(frozen=True, slots=True)
class VideoAsset:
    """Probed facts and stream layout for a complete container asset."""

    source_id: str
    relative_path: str
    file_bytes: int
    container_format: str
    duration_seconds: float
    streams: tuple[VideoStream, ...]
    schema_version: int = 1
    chapters_count: int = 0
    probe_status: str = "complete"  # complete, partial, failed
    probe_tool: str = "ffprobe"
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def primary_video_stream(self) -> VideoStream | None:
        """Return the primary non-cover-art video stream, if any."""
        for s in self.streams:
            if s.stream_type == "video" and not s.is_attached_pic:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "relative_path": self.relative_path,
            "file_bytes": self.file_bytes,
            "container_format": self.container_format,
            "duration_seconds": self.duration_seconds,
            "streams": [s.to_dict() for s in self.streams],
            "chapters_count": self.chapters_count,
            "probe_status": self.probe_status,
            "probe_tool": self.probe_tool,
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VideoAsset:
        streams = tuple(VideoStream.from_dict(s) for s in data.get("streams", []))
        errors = tuple(str(e) for e in data.get("errors", []))
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            source_id=str(data["source_id"]),
            relative_path=str(data["relative_path"]),
            file_bytes=int(data["file_bytes"]),
            container_format=str(data["container_format"]),
            duration_seconds=float(data["duration_seconds"]),
            streams=streams,
            chapters_count=int(data.get("chapters_count", 0)),
            probe_status=str(data.get("probe_status", "complete")),
            probe_tool=str(data.get("probe_tool", "ffprobe")),
            errors=errors,
        )


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """Evaluation result of source-asset eligibility filters."""

    stage: str  # discovery, metadata, feasibility, trial, apply
    status: str  # eligible, excluded, ineligible, unknown, unsupported
    reasons: tuple[str, ...] = field(default_factory=tuple)
    applied_thresholds: Mapping[str, Any] = field(default_factory=dict)
    unknowns: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "reasons": list(self.reasons),
            "applied_thresholds": dict(self.applied_thresholds),
            "unknowns": list(self.unknowns),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EligibilityDecision:
        return cls(
            stage=str(data["stage"]),
            status=str(data["status"]),
            reasons=tuple(str(r) for r in data.get("reasons", [])),
            applied_thresholds=dict(data.get("applied_thresholds", {})),
            unknowns=tuple(str(u) for u in data.get("unknowns", [])),
        )


@dataclass(frozen=True, slots=True)
class VideoRecipe:
    """Exact encoding parameters, stream policies, and runtime identifiers."""

    recipe_id: str
    codec: str  # av1, hevc, h264
    encoder: str  # av1_nvenc, hevc_nvenc, libsvtav1, libx265
    preset: str
    rate_control_mode: str  # cq, crf, cbr, vbr
    rate_control_value: float
    container: str = "matroska"
    pix_fmt: str = "yuv420p10le"
    bit_depth: int = 10
    audio_policy: str = "copy"  # copy, reencode, omit
    subtitle_policy: str = "copy"  # copy, omit
    attachment_policy: str = "copy"  # copy, omit
    metadata_policy: str = "copy"  # copy, clean
    quality_threshold: float | None = None
    runtime_identity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VideoRecipe:
        return cls(
            recipe_id=str(data["recipe_id"]),
            codec=str(data["codec"]),
            encoder=str(data["encoder"]),
            preset=str(data["preset"]),
            rate_control_mode=str(data["rate_control_mode"]),
            rate_control_value=float(data["rate_control_value"]),
            container=str(data.get("container", "matroska")),
            pix_fmt=str(data.get("pix_fmt", "yuv420p10le")),
            bit_depth=int(data.get("bit_depth", 10)),
            audio_policy=str(data.get("audio_policy", "copy")),
            subtitle_policy=str(data.get("subtitle_policy", "copy")),
            attachment_policy=str(data.get("attachment_policy", "copy")),
            metadata_policy=str(data.get("metadata_policy", "copy")),
            quality_threshold=float(data["quality_threshold"]) if data.get("quality_threshold") is not None else None,
            runtime_identity=data.get("runtime_identity"),
        )


@dataclass(frozen=True, slots=True)
class SamplingWindow:
    """A deterministic temporal interval within a video for trial encoding."""

    source_id: str
    window_index: int
    start_seconds: float
    duration_seconds: float
    start_pts: int | None = None
    end_pts: int | None = None
    frame_count: int | None = None
    weight: float = 1.0
    purpose: str = "uniform"  # uniform, stress, calibration
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SamplingWindow:
        return cls(
            source_id=str(data["source_id"]),
            window_index=int(data["window_index"]),
            start_seconds=float(data["start_seconds"]),
            duration_seconds=float(data["duration_seconds"]),
            start_pts=int(data["start_pts"]) if data.get("start_pts") is not None else None,
            end_pts=int(data["end_pts"]) if data.get("end_pts") is not None else None,
            frame_count=int(data["frame_count"]) if data.get("frame_count") is not None else None,
            weight=float(data.get("weight", 1.0)),
            purpose=str(data.get("purpose", "uniform")),
            seed=int(data["seed"]) if data.get("seed") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class VideoEstimationPlan:
    """Frozen plan defining source population, recipes, windows, and compute budget."""

    plan_id: str
    target_scope: str
    workspace_parent: str
    source_ids: tuple[str, ...]
    recipes: tuple[VideoRecipe, ...]
    sampling_windows: tuple[SamplingWindow, ...] = field(default_factory=tuple)
    schema_version: int = 1
    work_budget_seconds: float | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "target_scope": self.target_scope,
            "workspace_parent": self.workspace_parent,
            "source_ids": list(self.source_ids),
            "recipes": [r.to_dict() for r in self.recipes],
            "sampling_windows": [w.to_dict() for w in self.sampling_windows],
            "work_budget_seconds": self.work_budget_seconds,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VideoEstimationPlan:
        recipes = tuple(VideoRecipe.from_dict(r) for r in data.get("recipes", []))
        windows = tuple(SamplingWindow.from_dict(w) for w in data.get("sampling_windows", []))
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            plan_id=str(data["plan_id"]),
            target_scope=str(data["target_scope"]),
            workspace_parent=str(data["workspace_parent"]),
            source_ids=tuple(str(s) for s in data.get("source_ids", [])),
            recipes=recipes,
            sampling_windows=windows,
            work_budget_seconds=float(data["work_budget_seconds"]) if data.get("work_budget_seconds") is not None else None,
            created_at=data.get("created_at"),
        )


@dataclass(frozen=True, slots=True)
class TrialObservation:
    """Measured outcome of an actual bounded sample encode."""

    observation_id: str
    plan_id: str
    source_id: str
    recipe_id: str
    window_index: int
    clip_duration_seconds: float
    encoded_video_bytes: int
    encoded_video_bps: int
    elapsed_seconds: float
    schema_version: int = 1
    quality_metric_name: str | None = None
    quality_score: float | None = None
    cache_provenance: str = "fresh"  # fresh, cache_hit
    error_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TrialObservation:
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            observation_id=str(data["observation_id"]),
            plan_id=str(data["plan_id"]),
            source_id=str(data["source_id"]),
            recipe_id=str(data["recipe_id"]),
            window_index=int(data["window_index"]),
            clip_duration_seconds=float(data["clip_duration_seconds"]),
            encoded_video_bytes=int(data["encoded_video_bytes"]),
            encoded_video_bps=int(data["encoded_video_bps"]),
            elapsed_seconds=float(data["elapsed_seconds"]),
            quality_metric_name=data.get("quality_metric_name"),
            quality_score=float(data["quality_score"]) if data.get("quality_score") is not None else None,
            cache_provenance=str(data.get("cache_provenance", "fresh")),
            error_state=data.get("error_state"),
        )


@dataclass(frozen=True, slots=True)
class Prediction:
    """Predicted output bytes and feasibility decision for one asset and recipe."""

    source_id: str
    recipe_id: str
    tier: str  # metadata, features, sampled, calibrated
    source_container_bytes: int
    predicted_video_bytes: int
    predicted_nonvideo_bytes: int
    predicted_mux_overhead_bytes: int
    predicted_output_container_bytes: int
    predicted_gross_saved_bytes: int
    decision: str  # candidate, uncertain, unlikely, infeasible, needs_measurement, quality_risk
    schema_version: int = 1
    units: str = "bytes"
    prediction_interval: tuple[int, int] | None = None
    interval_status: str = "uncalibrated"  # calibrated, uncalibrated, abstained
    calibration_version: str | None = None
    observation_count: int = 0
    unknowns: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "recipe_id": self.recipe_id,
            "tier": self.tier,
            "units": self.units,
            "source_container_bytes": self.source_container_bytes,
            "predicted_video_bytes": self.predicted_video_bytes,
            "predicted_nonvideo_bytes": self.predicted_nonvideo_bytes,
            "predicted_mux_overhead_bytes": self.predicted_mux_overhead_bytes,
            "predicted_output_container_bytes": self.predicted_output_container_bytes,
            "predicted_gross_saved_bytes": self.predicted_gross_saved_bytes,
            "prediction_interval": list(self.prediction_interval) if self.prediction_interval else None,
            "interval_status": self.interval_status,
            "decision": self.decision,
            "calibration_version": self.calibration_version,
            "observation_count": self.observation_count,
            "unknowns": list(self.unknowns),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Prediction:
        interval = data.get("prediction_interval")
        parsed_interval = (int(interval[0]), int(interval[1])) if interval else None
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            source_id=str(data["source_id"]),
            recipe_id=str(data["recipe_id"]),
            tier=str(data["tier"]),
            units=str(data.get("units", "bytes")),
            source_container_bytes=int(data["source_container_bytes"]),
            predicted_video_bytes=int(data["predicted_video_bytes"]),
            predicted_nonvideo_bytes=int(data["predicted_nonvideo_bytes"]),
            predicted_mux_overhead_bytes=int(data["predicted_mux_overhead_bytes"]),
            predicted_output_container_bytes=int(data["predicted_output_container_bytes"]),
            predicted_gross_saved_bytes=int(data["predicted_gross_saved_bytes"]),
            prediction_interval=parsed_interval,
            interval_status=str(data.get("interval_status", "uncalibrated")),
            decision=str(data["decision"]),
            calibration_version=data.get("calibration_version"),
            observation_count=int(data.get("observation_count", 0)),
            unknowns=tuple(str(u) for u in data.get("unknowns", [])),
            errors=tuple(str(e) for e in data.get("errors", [])),
        )


@dataclass(frozen=True, slots=True)
class VideoApplyJob:
    """State of an authorized publication or conversion job under the media safety contract."""

    job_id: str
    source_id: str
    recipe_id: str
    plan_id: str
    status: str  # PLANNED, ELIGIBLE, ADMITTED, ENCODING, CANDIDATE_WRITTEN, VERIFYING, VERIFIED, SOURCE_RECHECKED, PUBLISHING, PUBLISHED, COMPLETED, SKIPPED, FAILED, INTERRUPTED, RECOVERY_REQUIRED
    source_canonical_path: str
    candidate_path: str
    output_path: str
    schema_version: int = 1
    backup_path: str | None = None
    staging_path: str | None = None
    authorization_token: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VideoApplyJob:
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            job_id=str(data["job_id"]),
            source_id=str(data["source_id"]),
            recipe_id=str(data["recipe_id"]),
            plan_id=str(data["plan_id"]),
            status=str(data["status"]),
            source_canonical_path=str(data["source_canonical_path"]),
            candidate_path=str(data["candidate_path"]),
            output_path=str(data["output_path"]),
            backup_path=data.get("backup_path"),
            staging_path=data.get("staging_path"),
            authorization_token=data.get("authorization_token"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass(frozen=True, slots=True)
class CompressionReport:
    """Structured report returned by video compression operations."""

    run_id: str
    operation: str
    total_sources: int
    eligible_sources: int
    processed_sources: int
    skipped_sources: int
    failed_sources: int
    total_input_bytes: int
    total_output_bytes: int
    predicted_savings_bytes: int
    realized_savings_bytes: int
    elapsed_seconds: float
    schema_version: int = 1
    per_source_records: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "operation": self.operation,
            "total_sources": self.total_sources,
            "eligible_sources": self.eligible_sources,
            "processed_sources": self.processed_sources,
            "skipped_sources": self.skipped_sources,
            "failed_sources": self.failed_sources,
            "total_input_bytes": self.total_input_bytes,
            "total_output_bytes": self.total_output_bytes,
            "predicted_savings_bytes": self.predicted_savings_bytes,
            "realized_savings_bytes": self.realized_savings_bytes,
            "elapsed_seconds": self.elapsed_seconds,
            "per_source_records": list(self.per_source_records),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CompressionReport:
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            run_id=str(data["run_id"]),
            operation=str(data["operation"]),
            total_sources=int(data["total_sources"]),
            eligible_sources=int(data["eligible_sources"]),
            processed_sources=int(data["processed_sources"]),
            skipped_sources=int(data["skipped_sources"]),
            failed_sources=int(data["failed_sources"]),
            total_input_bytes=int(data["total_input_bytes"]),
            total_output_bytes=int(data["total_output_bytes"]),
            predicted_savings_bytes=int(data["predicted_savings_bytes"]),
            realized_savings_bytes=int(data["realized_savings_bytes"]),
            elapsed_seconds=float(data["elapsed_seconds"]),
            per_source_records=tuple(dict(r) for r in data.get("per_source_records", [])),
            errors=tuple(str(e) for e in data.get("errors", [])),
        )
