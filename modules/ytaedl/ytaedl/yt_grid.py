"""yt-dlp grid-search helpers for ytaedl.

This module intentionally keeps gsearch imports lazy so normal ytaedl usage
does not require the optional grid_search module to be installed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_GRID_EXPERIMENT = "yt-dlp-mp4-speed"

DEFAULT_YTDLP_GRID_SPEC: dict[str, Any] = {
    "metric": {"name": "average_mbps", "direction": "maximize"},
    "policy": {
        "warmup_trials": 40,
        "epsilon_start": 0.35,
        "epsilon_floor": 0.08,
        "epsilon_decay_trials": 180,
        "ucb_weight": 0.75,
        "candidate_pool_size": 256,
        "neighbor_probability_after_warmup": 0.55,
        "ucb_probability_after_warmup": 0.30,
        "coverage_probability_after_warmup": 0.15,
        "min_group_trials": 16,
        "planned_trial_ttl_seconds": 21600,
    },
    "baseline": {
        "downloader": "native",
        "concurrent_fragments": 4,
        "http_chunk_size": "disabled",
        "buffer_size": "1M",
        "resize_buffer": True,
        "socket_timeout": 20,
        "retries": 10,
        "fragment_retries": 10,
        "force_ip": "auto",
        "format": "bv*+ba/b",
    },
    "parameters": {
        "downloader": {"values": ["native", "aria2c"], "priority": 1},
        "concurrent_fragments": {
            "values": [1, 2, 4, 8, 16, 32],
            "active_when": {"downloader": "native"},
            "priority": 1,
        },
        "http_chunk_size": {
            "values": ["disabled", "1M", "5M", "10M", "20M", "50M", "64M"],
            "active_when": {"downloader": "native"},
            "priority": 1,
        },
        "buffer_size": {
            "values": ["64K", "256K", "1M", "4M", "16M"],
            "active_when": {"downloader": "native"},
            "priority": 2,
        },
        "resize_buffer": {
            "values": [True, False],
            "active_when": {"downloader": "native"},
            "priority": 2,
        },
        "socket_timeout": {"values": [5, 10, 20, 30, 60], "priority": 3},
        "retries": {"values": [3, 5, 10, 20, 30], "priority": 3},
        "fragment_retries": {"values": [3, 5, 10, 20, 30], "priority": 3},
        "force_ip": {"values": ["auto", "ipv4", "ipv6"], "priority": 4},
        "format": {
            "values": ["best", "bv*+ba/b", "b", "bestvideo+bestaudio/best"],
            "priority": 2,
        },
        "aria2c_max_connection_per_server": {
            "values": [1, 2, 4, 8, 16],
            "active_when": {"downloader": "aria2c"},
            "priority": 1,
        },
        "aria2c_split": {
            "values": [1, 2, 4, 8, 16, 32],
            "active_when": {"downloader": "aria2c"},
            "priority": 1,
        },
        "aria2c_min_split_size": {
            "values": ["1M", "2M", "5M", "10M", "20M", "50M", "100M"],
            "active_when": {"downloader": "aria2c"},
            "priority": 1,
        },
        "aria2c_piece_length": {
            "values": ["256K", "512K", "1M", "2M", "4M", "8M", "16M"],
            "active_when": {"downloader": "aria2c"},
            "priority": 2,
        },
        "aria2c_file_allocation": {
            "values": ["none", "prealloc", "falloc"],
            "active_when": {"downloader": "aria2c"},
            "priority": 2,
        },
        "aria2c_disk_cache": {
            "values": ["0", "16M", "64M", "128M"],
            "active_when": {"downloader": "aria2c"},
            "priority": 2,
        },
    },
    "constraints": [
        {
            "type": "greater_equal",
            "left": "aria2c_split",
            "right": "aria2c_max_connection_per_server",
            "active_when": {"downloader": "aria2c"},
        }
    ],
}


def import_gsearch_manager() -> Any:
    try:
        from gsearch import manager as gsearch_manager
    except Exception as exc:  # pragma: no cover - exercised through caller error paths.
        raise RuntimeError(
            "yt-dlp grid search requires the gsearch module. Install modules/grid_search "
            "or run from an environment where gsearch is importable."
        ) from exc
    return gsearch_manager


def ensure_grid_experiment(database: str | Path, experiment: str) -> None:
    gsearch_manager = import_gsearch_manager()
    store = gsearch_manager.AdaptiveGridStore(database)
    try:
        store.read_experiment_grid(experiment)
    except RuntimeError:
        store.upsert_experiment(experiment, DEFAULT_YTDLP_GRID_SPEC)


def create_trial(
    *,
    database: str | Path,
    experiment: str,
    url: str,
    base_domain: str,
    worker_slot: int,
    source_urlfile: str,
) -> dict[str, Any]:
    gsearch_manager = import_gsearch_manager()
    return gsearch_manager.create_next_trial(
        database=database,
        experiment=experiment,
        output=None,
        group_key="domain",
        group_value=base_domain,
        group_mode="hybrid",
        selection_mode="adaptive",
        metadata={
            "url": url,
            "base_domain": base_domain,
            "worker_slot": worker_slot,
            "source_urlfile": source_urlfile,
        },
        seed=None,
    )


def record_trial(
    *,
    database: str | Path,
    trial_id: str,
    status: str,
    metric_value: float | None,
    metadata: dict[str, Any],
) -> None:
    gsearch_manager = import_gsearch_manager()
    gsearch_manager.record_trial_result(
        database=database,
        trial_id=trial_id,
        status=status,
        metric_value=metric_value,
        metadata=metadata,
    )


def write_trial_config(path: str | Path, trial_payload: dict[str, Any]) -> Path:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(trial_payload, indent=2, sort_keys=True), encoding="utf-8")
    return resolved


def load_trial_config(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("config"), dict):
        return dict(payload["config"])
    if isinstance(payload, dict):
        return dict(payload)
    raise RuntimeError(f"Invalid yt-dlp grid config file: {path}")


def append_raw_result(database: str | Path, payload: dict[str, Any]) -> Path:
    db_path = Path(database).expanduser().resolve()
    output = db_path.with_name(f"{db_path.stem}-raw-results.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
    return output


def base_domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return "-"
    host = host.lower().strip(".")
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host or "-"


def hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "-").lower().strip(".") or "-"
    except Exception:
        return "-"


def average_mbps(downloaded_bytes: Any, elapsed_seconds: Any) -> float | None:
    if not isinstance(downloaded_bytes, (int, float)) or downloaded_bytes <= 0:
        return None
    if not isinstance(elapsed_seconds, (int, float)) or elapsed_seconds <= 0:
        return None
    return (float(downloaded_bytes) * 8.0) / float(elapsed_seconds) / 1_000_000.0


def build_ytdlp_grid_args(config: dict[str, Any], *, allow_format: bool = True) -> list[str]:
    args: list[str] = []
    downloader = str(config.get("downloader") or "native")
    if downloader:
        args.extend(["--downloader", downloader])

    if "socket_timeout" in config:
        args.extend(["--socket-timeout", str(config["socket_timeout"])])
    if "retries" in config:
        args.extend(["--retries", str(config["retries"])])
    if "fragment_retries" in config:
        args.extend(["--fragment-retries", str(config["fragment_retries"])])

    force_ip = config.get("force_ip")
    if force_ip == "ipv4":
        args.append("--force-ipv4")
    elif force_ip == "ipv6":
        args.append("--force-ipv6")

    if allow_format and config.get("format"):
        args.extend(["--format", str(config["format"])])

    if downloader == "native":
        if "concurrent_fragments" in config:
            args.extend(["--concurrent-fragments", str(config["concurrent_fragments"])])
        if config.get("http_chunk_size") not in {None, "disabled"}:
            args.extend(["--http-chunk-size", str(config["http_chunk_size"])])
        if "buffer_size" in config:
            args.extend(["--buffer-size", str(config["buffer_size"])])
        if config.get("resize_buffer") is True:
            args.append("--resize-buffer")
        elif config.get("resize_buffer") is False:
            args.append("--no-resize-buffer")

    if downloader == "aria2c":
        aria2c_args: list[str] = []
        if "aria2c_max_connection_per_server" in config:
            aria2c_args.extend(["-x", str(config["aria2c_max_connection_per_server"])])
        if "aria2c_split" in config:
            aria2c_args.extend(["-s", str(config["aria2c_split"])])
        if "aria2c_min_split_size" in config:
            aria2c_args.extend(["-k", str(config["aria2c_min_split_size"])])
        if "aria2c_piece_length" in config:
            aria2c_args.append(f"--piece-length={config['aria2c_piece_length']}")
        if "aria2c_file_allocation" in config:
            aria2c_args.append(f"--file-allocation={config['aria2c_file_allocation']}")
        if "aria2c_disk_cache" in config:
            aria2c_args.append(f"--disk-cache={config['aria2c_disk_cache']}")
        if aria2c_args:
            args.extend(["--downloader-args", "aria2c:" + " ".join(aria2c_args)])

    return args


@dataclass
class GridRuntimeStats:
    base_domain: str
    started_at: float = field(default_factory=time.time)
    last_update_at: float = field(default_factory=time.time)
    same_domain_other_area: float = 0.0
    same_domain_including_self_area: float = 0.0
    total_speed_bps_area: float = 0.0
    worker_speed_bps_area: float = 0.0

    def update(
        self,
        *,
        now: float,
        same_domain_other_count: int,
        same_domain_including_self_count: int,
        total_speed_bps: float,
        worker_speed_bps: float,
    ) -> None:
        elapsed = max(0.0, now - self.last_update_at)
        self.same_domain_other_area += max(0, same_domain_other_count) * elapsed
        self.same_domain_including_self_area += max(0, same_domain_including_self_count) * elapsed
        self.total_speed_bps_area += max(0.0, float(total_speed_bps or 0.0)) * elapsed
        self.worker_speed_bps_area += max(0.0, float(worker_speed_bps or 0.0)) * elapsed
        self.last_update_at = now

    def snapshot(self, *, now: float) -> dict[str, float]:
        duration = max(0.0, now - self.started_at)
        denominator = max(duration, 1e-9)
        return {
            "manager_observed_elapsed_seconds": duration,
            "same_base_domain_other_active_average": self.same_domain_other_area / denominator,
            "same_base_domain_including_self_active_average": self.same_domain_including_self_area / denominator,
            "total_workers_average_mbps": (self.total_speed_bps_area / denominator) * 8.0 / 1_000_000.0,
            "worker_sampled_average_mbps": (self.worker_speed_bps_area / denominator) * 8.0 / 1_000_000.0,
        }
