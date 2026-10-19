"""
Hyperfine JSON benchmark importer.

Parses official Hyperfine JSON exports (--export-json):
- Extracts actual measured individual trial times (from the 'times' array)
- Rejects exports lacking individual 'times' (does not guess or reconstruct from aggregate statistics)
- Maps command variants to RunInfo and TrialResult records
- Preserves command parameters and exit code statuses
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Optional, Union

from ..models import (
    MetricQuality,
    MetricValue,
    RunInfo,
    TrialResult,
    TrialStatus,
    format_utc_timestamp,
)
from ..storage import append_results, save_run


def _slugify(text: str) -> str:
    """Create a safe identifier from a command string."""
    clean = re.sub(r"[^\w\-_.]", "_", text.strip())
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean[:48] if clean else "cmd"


def parse_hyperfine_data(
    data: dict[str, Any],
    suite_id: str = "hyperfine-benchmark",
    run_id: Optional[str] = None,
) -> tuple[RunInfo, list[TrialResult]]:
    """
    Parse a Hyperfine JSON data structure into RunInfo and TrialResult records.

    Args:
        data: Parsed dictionary of the Hyperfine JSON export.
        suite_id: Name for the benchmark suite.
        run_id: Optional identifier for the run.

    Returns:
        Tuple of (RunInfo, list[TrialResult]).
    """
    if not isinstance(data, dict) or "results" not in data:
        raise ValueError("Invalid Hyperfine export: missing root 'results' array.")

    results_list = data["results"]
    if not isinstance(results_list, list) or not results_list:
        raise ValueError("Invalid Hyperfine export: 'results' must be a non-empty list.")

    ts_now = format_utc_timestamp()
    clean_run_id = run_id or f"hyperfine-{ts_now.replace(':', '').replace('-', '')}"

    variants: dict[str, dict[str, Any]] = {}
    trials: list[TrialResult] = []
    task_ids: list[str] = []
    max_reps = 1

    for res_idx, res in enumerate(results_list, start=1):
        if not isinstance(res, dict):
            raise ValueError(f"Result entry #{res_idx} is not a valid JSON object.")

        command = res.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"Result entry #{res_idx} missing valid 'command' string.")

        # Require actual individual times array
        times = res.get("times")
        if not isinstance(times, list) or not times:
            raise ValueError(
                f"Result entry #{res_idx} ('{command}') lacks individual 'times' measurements. "
                "Reconstructing individual trials from aggregate statistics is unsupported."
            )

        exit_codes = res.get("exit_codes", [])
        parameters = res.get("parameters", {})

        # Variant ID
        variant_slug = _slugify(command)
        variant_id = f"var_{res_idx}_{variant_slug}"
        task_id = f"task_{res_idx}_{variant_slug}"
        task_ids.append(task_id)

        v_config: dict[str, Any] = {
            "command": command,
            "parameters": parameters if isinstance(parameters, dict) else {},
        }
        if "user" in res and res["user"] is not None:
            v_config["user_seconds"] = res["user"]
        if "system" in res and res["system"] is not None:
            v_config["system_seconds"] = res["system"]

        variants[variant_id] = v_config

        reps_count = len(times)
        if reps_count > max_reps:
            max_reps = reps_count

        for rep_idx, t_sec in enumerate(times, start=1):
            if not isinstance(t_sec, (int, float)) or isinstance(t_sec, bool):
                raise ValueError(
                    f"Invalid timing value in result #{res_idx} repetition #{rep_idx}: {t_sec!r}"
                )

            # Check exit code if available
            trial_status = TrialStatus.PASSED
            if isinstance(exit_codes, list) and len(exit_codes) >= rep_idx:
                code = exit_codes[rep_idx - 1]
                if code != 0:
                    trial_status = TrialStatus.FAILED

            wall_ms = round(float(t_sec) * 1000.0, 4)
            metrics = {
                "duration.wall_ms": MetricValue(
                    value=wall_ms,
                    unit="ms",
                    source="hyperfine",
                    quality=MetricQuality.MEASURED,
                )
            }

            trial_id = f"{clean_run_id}-{variant_id}-rep{rep_idx}"
            trial = TrialResult(
                run_id=clean_run_id,
                trial_id=trial_id,
                task_id=task_id,
                variant_id=variant_id,
                repetition=rep_idx,
                status=trial_status,
                metrics=metrics,
                details={
                    "command": command,
                    "parameters": parameters if isinstance(parameters, dict) else {},
                    "exit_code": exit_codes[rep_idx - 1] if len(exit_codes) >= rep_idx else 0,
                },
            )
            trials.append(trial)

    run_info = RunInfo(
        run_id=clean_run_id,
        created_at=ts_now,
        suite_id=suite_id,
        suite_version="1.0.0",
        task_ids=task_ids,
        variants=variants,
        repetitions=max_reps,
        scoring_basis="exit_code_zero",
        environment={"hyperfine_version": data.get("version", "unknown")},
        metadata={"importer": "hyperfine", "command_count": len(results_list)},
    )

    return run_info, trials


def import_hyperfine(
    input_file: Union[Path, str],
    suite_id: str = "hyperfine-benchmark",
    run_id: Optional[str] = None,
    output_dir: Optional[Union[Path, str]] = None,
    write: bool = False,
) -> tuple[RunInfo, list[TrialResult]]:
    """
    Import a Hyperfine JSON export file.

    Args:
        input_file: Path to Hyperfine JSON file.
        suite_id: Suite identifier.
        run_id: Optional run ID.
        output_dir: If write=True, destination directory for run.json and trials.jsonl.
        write: If True, writes authoritative files to output_dir.

    Returns:
        Tuple of (RunInfo, list[TrialResult]).
    """
    in_path = Path(input_file)
    if not in_path.is_file():
        raise FileNotFoundError(f"Hyperfine input file not found at {in_path}")

    content = in_path.read_text(encoding="utf-8")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in Hyperfine input {in_path}: {exc}") from exc

    run_info, trials = parse_hyperfine_data(data, suite_id=suite_id, run_id=run_id)

    if write:
        if output_dir is None:
            raise ValueError("output_dir must be specified when write=True")
        out_p = Path(output_dir)
        save_run(out_p, run_info, overwrite=True)
        target_trials = out_p / "trials.jsonl"
        if target_trials.exists():
            target_trials.unlink()
        append_results(out_p, trials, allow_duplicate=False)

    return run_info, trials
