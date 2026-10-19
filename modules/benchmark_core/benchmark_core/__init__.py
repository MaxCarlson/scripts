"""
benchmark_core — Lightweight, reusable benchmarking results and reporting utility.
"""

__version__ = "0.1.0"

from .models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
    format_utc_timestamp,
    is_safe_relative_path,
    metric_value_from_dict,
    metric_value_from_json,
    metric_value_to_dict,
    metric_value_to_json,
    parse_utc_timestamp,
    run_info_from_dict,
    run_info_from_json,
    run_info_to_dict,
    run_info_to_json,
    trial_result_from_dict,
    trial_result_from_json,
    trial_result_to_dict,
    trial_result_to_json,
    validate_relative_path,
)
from .stats import (
    BenchmarkSummary,
    DurationStats,
    MetricStats,
    TaskSummary,
    VariantSummary,
    compute_metric_stats,
    summarize,
)
from .storage import (
    BenchmarkStorageError,
    CorruptedDataError,
    DuplicateTrialError,
    append_result,
    append_results,
    get_existing_trial_ids,
    load_run,
    load_run_info,
    load_trials,
    save_run,
)

__all__ = [
    # Models
    "MetricQuality",
    "MetricValue",
    "RunInfo",
    "TrialResult",
    "TrialStatus",
    "format_utc_timestamp",
    "is_safe_relative_path",
    "metric_value_from_dict",
    "metric_value_from_json",
    "metric_value_to_dict",
    "metric_value_to_json",
    "parse_utc_timestamp",
    "run_info_from_dict",
    "run_info_from_json",
    "run_info_to_dict",
    "run_info_to_json",
    "trial_result_from_dict",
    "trial_result_from_json",
    "trial_result_to_dict",
    "trial_result_to_json",
    "validate_relative_path",
    # Storage
    "BenchmarkStorageError",
    "CorruptedDataError",
    "DuplicateTrialError",
    "append_result",
    "append_results",
    "get_existing_trial_ids",
    "load_run",
    "load_run_info",
    "load_trials",
    "save_run",
    # Stats
    "BenchmarkSummary",
    "DurationStats",
    "MetricStats",
    "TaskSummary",
    "VariantSummary",
    "compute_metric_stats",
    "summarize",
]
