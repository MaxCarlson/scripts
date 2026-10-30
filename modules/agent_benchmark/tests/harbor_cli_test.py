"""End-to-end CLI tests for agent-bench external command group."""

from __future__ import annotations

import json
from pathlib import Path

from agent_benchmark.cli import main
from harbor_fixtures import create_mock_harbor_job


def test_cli_external_list(capsys):
    rc = main(["external", "list", "--format", "json"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "datasets" in data
    assert any(d["id"] == "aider/aider-polyglot" for d in data["datasets"])
    assert any(d["id"] == "terminal-bench/terminal-bench@4.0.0" for d in data["datasets"])
    assert any(d["id"] == "terminal-bench/terminal-bench-2" and d["total_tasks"] == 89 for d in data["datasets"])
    assert "readiness" in data


def test_cli_external_plan_json(capsys):
    rc = main([
        "external", "plan",
        "-d", "aider/aider-polyglot",
        "--language", "python",
        "-n", "3",
        "-s", "42",
        "--format", "json",
    ])
    assert rc in (0, 1)  # 0 when Docker is online, 1 when offline
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["selected_tasks_count"] == 3
    assert data["seed"] == 42
    assert data["scoring_protocol"] == "single-attempt-v1"
    assert "readiness" in data


def test_cli_external_import_and_report(tmp_path: Path, capsys):
    job_dir = create_mock_harbor_job(tmp_path)
    out_dir = tmp_path / "reports_dir"

    # 1. Run import
    rc_import = main([
        "external", "import",
        "-j", str(job_dir),
        "-o", str(out_dir),
        "--format", "json",
    ])
    assert rc_import == 1  # The mock job has 1 infrastructure error, so exit code reflects errors
    captured_import = capsys.readouterr()
    import_summary = json.loads(captured_import.out)
    assert import_summary["scheduled"] == 4
    assert import_summary["passed"] == 1
    assert import_summary["scored"] == 3
    assert import_summary["infrastructure_error"] == 1

    # Check files created on disk
    assert (out_dir / "run.json").is_file()
    assert (out_dir / "trials.jsonl").is_file()
    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "harbor_summary.json").is_file()

    # 2. Run report
    rc_report = main([
        "external", "report",
        "-o", str(out_dir),
        "--format", "json",
    ])
    assert rc_report == 0
    captured_report = capsys.readouterr()
    report_data = json.loads(captured_report.out)
    assert len(report_data) == 1
    assert report_data[0]["passed"] == 1
    assert report_data[0]["scored"] == 3

    # 3. Run report markdown
    rc_md = main([
        "external", "report",
        "-o", str(out_dir),
        "--format", "markdown",
    ])
    assert rc_md == 0
    captured_md = capsys.readouterr()
    assert "### Benchmark: aider/aider-polyglot" in captured_md.out
    assert "`oracle`" in captured_md.out


def test_cli_external_run_unauthorized(capsys):
    rc = main([
        "external", "run",
        "-d", "aider/aider-polyglot",
        "-a", "oracle",
    ])
    assert rc != 0
    captured = capsys.readouterr()
    assert "refused without -x/--execute" in captured.err
