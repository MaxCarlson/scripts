from __future__ import annotations

import json
import subprocess
from pathlib import Path

from development_ledger.cli import main


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "tracked.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)


def test_validate_plan_cli(plan_path, capsys):
    result = main(["validate-plan", "-p", str(plan_path)])

    assert result == 0
    assert "VALID: demo-plan" in capsys.readouterr().out


def test_record_cli_writes_ledger_and_projections(plan_path, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        """<testsuite name="pytest"><testcase name="test_preview" file="tests/engine_test.py" />
<testcase name="test_error_code" file="tests/cli_test.py" /></testsuite>""",
        encoding="utf-8",
    )
    output = tmp_path / "ledger"

    result = main(
        [
            "record",
            "-p",
            str(plan_path),
            "-o",
            str(output),
            "-r",
            str(repo),
            "-j",
            str(junit),
            "-i",
            "run-cli",
            "-w",
        ]
    )

    assert result == 0
    assert (output / "RUNS.jsonl").exists()
    assert json.loads((output / "LATEST.json").read_text(encoding="utf-8"))["event_id"] == "run-cli"
    assert (output / "PROGRESS.md").exists()


def test_init_plan_defaults_to_preview(tmp_path: Path, capsys):
    path = tmp_path / "new-plan.md"

    result = main(["init-plan", "-p", str(path), "-i", "p1", "-t", "One", "-r", "modules/one"])

    assert result == 0
    assert not path.exists()
    assert "development-ledger:state:start" in capsys.readouterr().out


def test_init_plan_write_creates_file(tmp_path: Path):
    path = tmp_path / "new-plan.md"

    result = main(
        ["init-plan", "-p", str(path), "-i", "p1", "-t", "One", "-r", "modules/one", "-w"]
    )

    assert result == 0
    assert path.exists()


def test_main_returns_two_for_invalid_plan(tmp_path: Path, capsys):
    path = tmp_path / "invalid.md"
    path.write_text("# Missing state", encoding="utf-8")

    result = main(["validate-plan", "-p", str(path)])

    assert result == 2
    assert "ERROR:" in capsys.readouterr().err


def test_manual_and_summarize_cli(plan_path, tmp_path: Path, capsys):
    repo = tmp_path / "repo-manual"
    repo.mkdir()
    _init_git_repo(repo)
    output = tmp_path / "ledger-manual"

    result = main(
        [
            "manual",
            "-p",
            str(plan_path),
            "-o",
            str(output),
            "-r",
            str(repo),
            "-i",
            "MC-001",
            "-s",
            "passed",
            "-n",
            "Verified",
            "-e",
            "manual-1",
            "-w",
        ]
    )
    assert result == 0
    assert "RECORDED" in capsys.readouterr().out

    result = main(["summarize", "-p", str(plan_path), "-o", str(output)])
    assert result == 0
    assert "Development Progress" in capsys.readouterr().out

    result = main(["summarize", "-p", str(plan_path), "-o", str(output), "-w"])
    assert result == 0
    assert "UPDATED" in capsys.readouterr().out
