"""Empirical trial measurement backend, SQLite trial cache, and sample estimation."""

from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from videocompress.adapters.ffmpeg import FFmpegAdapter, SampleEncodeResult
from videocompress.contracts import VideoAsset, VideoRecipe
from videocompress.predictor import compute_nonvideo_payload, determine_quality_floor
from videocompress.sampling import SampleWindow, generate_sample_windows
from videocompress.workspace import VideoWorkspace


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """Persistent record of an empirical sample encoding trial."""

    trial_id: str
    source_id: str
    stat_fingerprint: str
    recipe_id: str
    window_index: int
    window_start: float
    window_duration: float
    actual_duration: float
    sample_file_bytes: int
    sample_video_bytes: int
    sample_video_bps: int
    encode_seconds: float
    fps_throughput: float
    encoder: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "source_id": self.source_id,
            "stat_fingerprint": self.stat_fingerprint,
            "recipe_id": self.recipe_id,
            "window_index": self.window_index,
            "window_start": round(self.window_start, 3),
            "window_duration": round(self.window_duration, 3),
            "actual_duration": round(self.actual_duration, 3),
            "sample_file_bytes": self.sample_file_bytes,
            "sample_video_bytes": self.sample_video_bytes,
            "sample_video_bps": self.sample_video_bps,
            "encode_seconds": round(self.encode_seconds, 3),
            "fps_throughput": round(self.fps_throughput, 2),
            "encoder": self.encoder,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TrialRecord:
        return cls(
            trial_id=str(row["trial_id"]),
            source_id=str(row["source_id"]),
            stat_fingerprint=str(row["stat_fingerprint"]),
            recipe_id=str(row["recipe_id"]),
            window_index=int(row["window_index"]),
            window_start=float(row["window_start"]),
            window_duration=float(row["window_duration"]),
            actual_duration=float(row["actual_duration"]),
            sample_file_bytes=int(row["sample_file_bytes"]),
            sample_video_bytes=int(row["sample_video_bytes"]),
            sample_video_bps=int(row["sample_video_bps"]),
            encode_seconds=float(row["encode_seconds"]),
            fps_throughput=float(row["fps_throughput"]),
            encoder=str(row["encoder"]),
            created_at=str(row["created_at"]),
        )


class TrialStore:
    """SQLite persistence store for empirical sample trial measurements."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trials_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sample_trials (
                    trial_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    stat_fingerprint TEXT NOT NULL,
                    recipe_id TEXT NOT NULL,
                    window_index INTEGER NOT NULL,
                    window_start REAL NOT NULL,
                    window_duration REAL NOT NULL,
                    actual_duration REAL NOT NULL,
                    sample_file_bytes INTEGER NOT NULL,
                    sample_video_bytes INTEGER NOT NULL,
                    sample_video_bps INTEGER NOT NULL,
                    encode_seconds REAL NOT NULL,
                    fps_throughput REAL NOT NULL,
                    encoder TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (source_id, stat_fingerprint, recipe_id, window_index)
                );
                CREATE INDEX IF NOT EXISTS idx_sample_trials_lookup
                    ON sample_trials(source_id, stat_fingerprint, recipe_id);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO trials_metadata (key, value) VALUES ('schema_version', '1');"
            )

    def get_trial(
        self,
        source_id: str,
        stat_fingerprint: str,
        recipe_id: str,
        window_index: int,
    ) -> TrialRecord | None:
        """Retrieve a cached trial record matching exact asset state and window."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM sample_trials
                WHERE source_id = ? AND stat_fingerprint = ? AND recipe_id = ? AND window_index = ?
                """,
                (source_id, stat_fingerprint, recipe_id, window_index),
            )
            row = cursor.fetchone()
            return TrialRecord.from_row(row) if row else None

    def get_trials_for_asset(
        self,
        source_id: str,
        stat_fingerprint: str,
        recipe_id: str,
    ) -> list[TrialRecord]:
        """Retrieve all completed trials for an asset under a target recipe."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM sample_trials
                WHERE source_id = ? AND stat_fingerprint = ? AND recipe_id = ?
                ORDER BY window_index ASC
                """,
                (source_id, stat_fingerprint, recipe_id),
            )
            return [TrialRecord.from_row(r) for r in cursor.fetchall()]

    def save_trial(self, record: TrialRecord) -> None:
        """Insert or replace a trial record."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sample_trials (
                    trial_id, source_id, stat_fingerprint, recipe_id,
                    window_index, window_start, window_duration, actual_duration,
                    sample_file_bytes, sample_video_bytes, sample_video_bps,
                    encode_seconds, fps_throughput, encoder, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.trial_id,
                    record.source_id,
                    record.stat_fingerprint,
                    record.recipe_id,
                    record.window_index,
                    record.window_start,
                    record.window_duration,
                    record.actual_duration,
                    record.sample_file_bytes,
                    record.sample_video_bytes,
                    record.sample_video_bps,
                    record.encode_seconds,
                    record.fps_throughput,
                    record.encoder,
                    record.created_at,
                ),
            )


@dataclass(frozen=True, slots=True)
class SamplePrediction:
    """Aggregate prediction based on measured empirical sample trials."""

    source_id: str
    recipe_id: str
    tier: str
    source_container_bytes: int
    duration_seconds: float
    measured_mean_video_bps: int
    predicted_video_bytes: int
    predicted_nonvideo_bytes: int
    predicted_mux_overhead_bytes: int
    predicted_output_container_bytes: int
    predicted_gross_saved_bytes: int
    predicted_savings_pct: float
    prediction_interval: tuple[int, int]
    decision: str  # measured_promising, measured_unfavorable, quality_risk, insufficient_samples
    confidence: str  # high, medium, low
    interval_status: str
    trials_count: int
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "recipe_id": self.recipe_id,
            "tier": self.tier,
            "source_container_bytes": self.source_container_bytes,
            "duration_seconds": self.duration_seconds,
            "measured_mean_video_bps": self.measured_mean_video_bps,
            "predicted_video_bytes": self.predicted_video_bytes,
            "predicted_nonvideo_bytes": self.predicted_nonvideo_bytes,
            "predicted_mux_overhead_bytes": self.predicted_mux_overhead_bytes,
            "predicted_output_container_bytes": self.predicted_output_container_bytes,
            "predicted_gross_saved_bytes": self.predicted_gross_saved_bytes,
            "predicted_savings_pct": round(self.predicted_savings_pct, 2),
            "prediction_interval": list(self.prediction_interval),
            "decision": self.decision,
            "confidence": self.confidence,
            "interval_status": self.interval_status,
            "trials_count": self.trials_count,
            "rejection_reasons": list(self.rejection_reasons),
            "warnings": list(self.warnings),
        }


def aggregate_sample_estimate(
    asset: VideoAsset,
    recipe: VideoRecipe,
    trials: Sequence[TrialRecord],
    min_savings_pct: float | None = None,
    min_savings_bytes: int | None = None,
    savings_policy: str = "both",
) -> SamplePrediction:
    """Aggregate empirical trial measurements into a calibrated sample prediction."""
    source_bytes = asset.file_bytes
    duration = asset.duration_seconds

    # Decompose non-video streams using Stage 3 stream breakdown
    breakdown = compute_nonvideo_payload(asset, recipe)

    if not trials:
        return SamplePrediction(
            source_id=asset.source_id,
            recipe_id=recipe.recipe_id,
            tier="sampled",
            source_container_bytes=source_bytes,
            duration_seconds=duration,
            measured_mean_video_bps=0,
            predicted_video_bytes=0,
            predicted_nonvideo_bytes=breakdown.total_nonvideo_bytes,
            predicted_mux_overhead_bytes=breakdown.mux_overhead_bytes,
            predicted_output_container_bytes=source_bytes,
            predicted_gross_saved_bytes=0,
            predicted_savings_pct=0.0,
            prediction_interval=(source_bytes, source_bytes),
            decision="insufficient_samples",
            confidence="low",
            interval_status="no_trials_completed",
            trials_count=0,
            rejection_reasons=("No sample trial measurements completed.",),
        )

    # Compute duration-weighted average video bitrate
    total_sample_sec = sum(t.actual_duration for t in trials)
    if total_sample_sec > 0:
        mean_video_bps = int(sum(t.sample_video_bps * t.actual_duration for t in trials) / total_sample_sec)
    else:
        mean_video_bps = int(sum(t.sample_video_bps for t in trials) / len(trials))

    # Min and max bitrates across windows
    min_bps = min(t.sample_video_bps for t in trials)
    max_bps = max(t.sample_video_bps for t in trials)

    # Output video bytes
    pred_video_bytes = int(mean_video_bps * duration / 8.0) if duration > 0 else 0
    p_opt_vbytes = int(min_bps * duration / 8.0) if duration > 0 else 0
    p_cons_vbytes = int(max_bps * duration / 8.0) if duration > 0 else 0

    nonvideo_payload = breakdown.audio_bytes + breakdown.subtitle_bytes + breakdown.attachment_bytes
    mux_overhead = breakdown.mux_overhead_bytes
    total_nonvideo = breakdown.total_nonvideo_bytes

    pred_out_bytes = pred_video_bytes + total_nonvideo
    p_opt_out = p_opt_vbytes + total_nonvideo
    p_cons_out = p_cons_vbytes + total_nonvideo

    pred_saved_bytes = source_bytes - pred_out_bytes
    pred_saved_pct = (pred_saved_bytes / source_bytes * 100.0) if source_bytes > 0 else 0.0

    # Decision evaluation
    pv = asset.primary_video_stream
    quality_floor = determine_quality_floor(pv, recipe.codec) if pv else 1_000_000

    reasons: list[str] = []
    warnings: list[str] = []

    meets_pct = (min_savings_pct is None) or (pred_saved_pct >= min_savings_pct)
    meets_bytes = (min_savings_bytes is None) or (pred_saved_bytes >= min_savings_bytes)
    meets_savings = (meets_pct and meets_bytes) if savings_policy == "both" else (meets_pct or meets_bytes)

    if mean_video_bps < quality_floor:
        decision = "quality_risk"
        reasons.append(
            f"Measured sample video bitrate ({mean_video_bps // 1000} kbps) is below "
            f"recommended visual quality floor ({quality_floor // 1000} kbps)."
        )
    elif meets_savings:
        decision = "measured_promising"
    else:
        decision = "measured_unfavorable"
        reasons.append("Measured trial savings do not meet required minimum savings threshold.")

    confidence = "high" if len(trials) >= 3 else "medium"

    return SamplePrediction(
        source_id=asset.source_id,
        recipe_id=recipe.recipe_id,
        tier="sampled",
        source_container_bytes=source_bytes,
        duration_seconds=duration,
        measured_mean_video_bps=mean_video_bps,
        predicted_video_bytes=pred_video_bytes,
        predicted_nonvideo_bytes=nonvideo_payload,
        predicted_mux_overhead_bytes=mux_overhead,
        predicted_output_container_bytes=pred_out_bytes,
        predicted_gross_saved_bytes=pred_saved_bytes,
        predicted_savings_pct=pred_saved_pct,
        prediction_interval=(p_opt_out, p_cons_out),
        decision=decision,
        confidence=confidence,
        interval_status="empirical_sample_measurement",
        trials_count=len(trials),
        rejection_reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def run_sample_trials(
    assets: Sequence[VideoAsset],
    canonical_paths: Mapping[str, str],
    recipe: VideoRecipe,
    workspace: VideoWorkspace,
    schedule: str = "s3",
    window_duration_seconds: float = 10.0,
    max_trials: int | None = None,
    max_time_seconds: float | None = None,
    force_refresh: bool = False,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> tuple[list[TrialRecord], str]:
    """Execute bounded empirical sample trials with SQLite caching and quota budgeting.

    Returns:
        tuple of (all_completed_trial_records, stopped_reason)
        stopped_reason is 'complete', 'max_trials_budget_reached', or 'max_time_budget_reached'.
    """
    store = TrialStore(workspace.trials_db)
    adapter = FFmpegAdapter()

    all_records: list[TrialRecord] = []
    trials_executed_count = 0
    total_encode_time_sec = 0.0
    stopped_reason = "complete"

    for asset_idx, asset in enumerate(assets):
        source_path_str = canonical_paths.get(asset.source_id)
        if not source_path_str:
            continue
        source_path = Path(source_path_str)
        if not source_path.exists():
            continue

        st = source_path.stat()
        stat_fp = f"{st.st_mtime_ns}:{st.st_size}"

        windows = generate_sample_windows(
            duration_seconds=asset.duration_seconds,
            schedule=schedule,
            window_duration_seconds=window_duration_seconds,
        )

        for window in windows:
            # Check SQLite cache first
            cached = store.get_trial(
                source_id=asset.source_id,
                stat_fingerprint=stat_fp,
                recipe_id=recipe.recipe_id,
                window_index=window.window_index,
            )
            if cached and not force_refresh:
                all_records.append(cached)
                continue

            # Check quota before executing new encode
            if max_trials is not None and trials_executed_count >= max_trials:
                stopped_reason = "max_trials_budget_reached"
                return all_records, stopped_reason

            if max_time_seconds is not None and total_encode_time_sec >= max_time_seconds:
                stopped_reason = "max_time_budget_reached"
                return all_records, stopped_reason

            # Generate unique trial ID and isolated scratch space
            trial_key = f"{asset.source_id}_{recipe.recipe_id}_w{window.window_index}_{window.start_seconds:.1f}"
            trial_id = hashlib.sha256(trial_key.encode("utf-8")).hexdigest()[:16]
            scratch_trial_dir = workspace.root / "scratch" / f"trial_{trial_id}"

            if progress_cb:
                progress_cb(f"Encoding sample {asset.relative_path} w{window.window_index}", trials_executed_count, max_trials or 0)

            # Execute sample encode
            result = adapter.encode_sample_clip(
                source_path=source_path,
                recipe=recipe,
                window=window,
                scratch_dir=scratch_trial_dir,
            )

            record = TrialRecord(
                trial_id=trial_id,
                source_id=asset.source_id,
                stat_fingerprint=stat_fp,
                recipe_id=recipe.recipe_id,
                window_index=window.window_index,
                window_start=window.start_seconds,
                window_duration=window.duration_seconds,
                actual_duration=result.actual_duration,
                sample_file_bytes=result.sample_file_bytes,
                sample_video_bytes=result.sample_video_bytes,
                sample_video_bps=result.sample_video_bps,
                encode_seconds=result.encode_seconds,
                fps_throughput=result.fps_throughput,
                encoder=result.encoder,
                created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

            store.save_trial(record)
            all_records.append(record)

            trials_executed_count += 1
            total_encode_time_sec += result.encode_seconds

            # Clean up intermediate scratch clip to conserve disk space
            try:
                if result.sample_path.exists():
                    result.sample_path.unlink()
                if scratch_trial_dir.exists():
                    scratch_trial_dir.rmdir()
            except OSError:
                pass

    return all_records, stopped_reason
