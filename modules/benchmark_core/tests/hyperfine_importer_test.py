"""
Tests for Hyperfine JSON importer.
"""

import json
from pathlib import Path
import pytest

from benchmark_core.cli import main
from benchmark_core.importers.hyperfine import import_hyperfine, parse_hyperfine_data
from benchmark_core.models import TrialStatus
from benchmark_core.storage import load_run


@pytest.fixture
def sample_hyperfine_json(tmp_path: Path) -> Path:
    data = {
        "version": "1.18.0",
        "results": [
            {
                "command": "python -c 'print(1)'",
                "mean": 0.035,
                "stddev": 0.002,
                "median": 0.035,
                "user": 0.020,
                "system": 0.010,
                "min": 0.032,
                "max": 0.038,
                "times": [0.032, 0.035, 0.038],
                "exit_codes": [0, 0, 0],
                "parameters": {"opt": "level1"},
            },
            {
                "command": "python -c 'import sys; sys.exit(1)'",
                "mean": 0.040,
                "stddev": 0.003,
                "median": 0.040,
                "user": 0.025,
                "system": 0.012,
                "min": 0.038,
                "max": 0.045,
                "times": [0.038, 0.040, 0.045],
                "exit_codes": [1, 1, 1],
                "parameters": {"opt": "level2"},
            },
        ],
    }
    p = tmp_path / "hyperfine_export.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_import_hyperfine_valid(sample_hyperfine_json: Path) -> None:
    run_info, trials = import_hyperfine(
        input_file=sample_hyperfine_json,
        suite_id="cli-perf-eval",
        run_id="run-hf-01",
    )

    assert run_info.run_id == "run-hf-01"
    assert run_info.suite_id == "cli-perf-eval"
    assert len(run_info.variants) == 2
    assert run_info.repetitions == 3
    assert len(trials) == 6

    # Successful command trials
    cmd1_trials = [t for t in trials if "print(1)" in t.details["command"]]
    assert len(cmd1_trials) == 3
    for t in cmd1_trials:
        assert t.status == TrialStatus.PASSED
        assert t.metrics["duration.wall_ms"].unit == "ms"
        assert t.metrics["duration.wall_ms"].value is not None

    # Failed command trials (exit code 1)
    cmd2_trials = [t for t in trials if "sys.exit(1)" in t.details["command"]]
    assert len(cmd2_trials) == 3
    for t in cmd2_trials:
        assert t.status == TrialStatus.FAILED


def test_import_hyperfine_write_to_disk(tmp_path: Path, sample_hyperfine_json: Path) -> None:
    out_dir = tmp_path / "imported_hf_run"
    import_hyperfine(
        input_file=sample_hyperfine_json,
        output_dir=out_dir,
        write=True,
    )

    assert (out_dir / "run.json").is_file()
    assert (out_dir / "trials.jsonl").is_file()

    loaded_run, loaded_trials = load_run(out_dir)
    assert len(loaded_run.variants) == 2
    assert len(loaded_trials) == 6


def test_reject_hyperfine_lacking_individual_times() -> None:
    """Requirement: Do not reconstruct individual trials from aggregate statistics."""
    data = {
        "results": [
            {
                "command": "sleep 1",
                "mean": 1.0,
                # Missing 'times' array!
            }
        ]
    }
    with pytest.raises(ValueError, match="lacks individual 'times' measurements"):
        parse_hyperfine_data(data)


def test_cli_import_subcommand(tmp_path: Path, sample_hyperfine_json: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = tmp_path / "cli_hf_out"
    exit_code = main([
        "import",
        "--format", "hyperfine",
        "--input-file", str(sample_hyperfine_json),
        "--output-dir", str(out_dir),
        "--write",
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Successfully parsed Hyperfine benchmark" in captured.out
    assert (out_dir / "run.json").is_file()
    assert (out_dir / "trials.jsonl").is_file()
