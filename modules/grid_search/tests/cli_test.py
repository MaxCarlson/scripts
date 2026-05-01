"""CLI integration tests for gsearch."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from gsearch.cli import main, parse_args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_GRID = {
    "metric": {"name": "average_mbps", "direction": "maximize"},
    "parameters": {
        "concurrent_fragments": {"values": [1, 4, 8], "priority": 1},
        "buffer_size": {"values": ["1M", "4M"], "priority": 2},
    },
}


@pytest.fixture()
def grid_file(tmp_path: Path) -> Path:
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(MINIMAL_GRID), encoding="utf-8")
    return path


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_init_parses(self, tmp_path: Path) -> None:
        args = parse_args(["init", "-d", "x.db", "-g", "g.json", "-e", "exp1"])
        assert args.command == "init"
        assert args.database == "x.db"
        assert args.grid == "g.json"
        assert args.experiment == "exp1"

    def test_next_parses_defaults(self, tmp_path: Path) -> None:
        args = parse_args(["next", "-d", "x.db", "-e", "exp1"])
        assert args.command == "next"
        assert args.output == "-"
        assert args.group_key is None
        assert args.group_value is None
        assert args.group_mode == "hybrid"
        assert args.mode == "adaptive"
        assert args.seed is None

    def test_next_parses_group_args(self) -> None:
        args = parse_args([
            "next", "-d", "x.db", "-e", "exp1",
            "-k", "domain", "-v", "example.com", "-G", "per-group",
        ])
        assert args.group_key == "domain"
        assert args.group_value == "example.com"
        assert args.group_mode == "per-group"

    def test_record_parses(self) -> None:
        args = parse_args([
            "record", "-d", "x.db", "-t", "some-uuid", "-v", "42.1", "-s", "ok",
        ])
        assert args.command == "record"
        assert args.trial_id == "some-uuid"
        assert args.metric_value == pytest.approx(42.1)
        assert args.status == "ok"

    def test_record_invalid_status(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["record", "-d", "x.db", "-t", "uid", "-s", "bogus"])

    def test_export_parses(self) -> None:
        args = parse_args(["export", "-d", "x.db", "-e", "exp1", "-o", "out.jsonl"])
        assert args.command == "export"
        assert args.output == "out.jsonl"

    def test_summary_parses(self) -> None:
        args = parse_args(["summary", "-d", "x.db", "-e", "exp1"])
        assert args.command == "summary"
        assert args.output == "-"
        assert args.limit == 20

    def test_report_parses(self) -> None:
        args = parse_args(["report", "-d", "x.db", "-e", "exp1", "-o", "report/"])
        assert args.command == "report"
        assert args.output_dir == "report/"

    def test_no_command_exits(self) -> None:
        with pytest.raises(SystemExit):
            parse_args([])


# ---------------------------------------------------------------------------
# Full round-trip via main()
# ---------------------------------------------------------------------------


class TestMainRoundTrip:
    def test_init_creates_experiment(
        self, db_path: Path, grid_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rc = main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        assert rc == 0
        assert db_path.exists()

    def test_next_returns_trial_json_to_stdout(
        self, db_path: Path, grid_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main(["next", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "trial_id" in payload
        assert "config" in payload
        assert payload["status"] == "planned"

    def test_next_writes_trial_file(
        self, db_path: Path, grid_file: Path, tmp_path: Path
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        out_file = tmp_path / "trial.json"
        rc = main(["next", "-d", str(db_path), "-e", "exp1", "-o", str(out_file)])
        assert rc == 0
        assert out_file.exists()
        payload = json.loads(out_file.read_text())
        assert "trial_id" in payload

    def test_record_ok_updates_trial(
        self, db_path: Path, grid_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main(["next", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        out = capsys.readouterr().out
        trial_id = json.loads(out)["trial_id"]

        rc = main([
            "record", "-d", str(db_path),
            "-t", trial_id, "-v", "55.2", "-s", "ok",
        ])
        assert rc == 0

    def test_record_failed_no_metric(
        self, db_path: Path, grid_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main(["next", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        out = capsys.readouterr().out
        trial_id = json.loads(out)["trial_id"]

        rc = main([
            "record", "-d", str(db_path),
            "-t", trial_id, "-s", "failed",
        ])
        assert rc == 0

    def test_record_ok_without_metric_returns_error(
        self, db_path: Path, grid_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main(["next", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        out = capsys.readouterr().out
        trial_id = json.loads(out)["trial_id"]

        rc = main([
            "record", "-d", str(db_path),
            "-t", trial_id, "-s", "ok",  # no -v → should fail
        ])
        assert rc == 1

    def test_export_writes_jsonl(
        self, db_path: Path, grid_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        main(["next", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        capsys.readouterr()

        out_file = tmp_path / "out.jsonl"
        rc = main(["export", "-d", str(db_path), "-e", "exp1", "-o", str(out_file)])
        assert rc == 0
        assert out_file.exists()
        lines = [l for l in out_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert "trial_id" in json.loads(lines[0])

    def test_summary_stdout(
        self, db_path: Path, grid_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main(["summary", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["experiment_name"] == "exp1"
        assert "trial_count" in payload

    def test_summary_writes_file(
        self, db_path: Path, grid_file: Path, tmp_path: Path
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        out_file = tmp_path / "summary.json"
        rc = main(["summary", "-d", str(db_path), "-e", "exp1", "-o", str(out_file)])
        assert rc == 0
        assert out_file.exists()

    def test_full_round_trip(
        self, db_path: Path, grid_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        # init → next → record ok → summary shows 1 successful trial
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        main(["next", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        out = capsys.readouterr().out
        trial_id = json.loads(out)["trial_id"]

        main([
            "record", "-d", str(db_path),
            "-t", trial_id, "-v", "88.0", "-s", "ok",
        ])
        capsys.readouterr()

        main(["summary", "-d", str(db_path), "-e", "exp1", "-o", "-"])
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["successful_trial_count"] == 1
        assert len(payload["top"]) == 1
        assert payload["top"][0]["mean"] == pytest.approx(88.0)

    def test_error_missing_experiment_returns_1(
        self, db_path: Path, grid_file: Path
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main(["next", "-d", str(db_path), "-e", "nonexistent"])
        assert rc == 1

    def test_record_missing_trial_returns_1(self, db_path: Path, grid_file: Path) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main([
            "record", "-d", str(db_path),
            "-t", "00000000-0000-0000-0000-000000000000",
            "-v", "1.0", "-s", "ok",
        ])
        assert rc == 1

    def test_group_next_uses_domain(
        self, db_path: Path, grid_file: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["init", "-d", str(db_path), "-g", str(grid_file), "-e", "exp1"])
        rc = main([
            "next", "-d", str(db_path), "-e", "exp1",
            "-k", "domain", "-v", "example.com", "-G", "hybrid",
            "-o", "-",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["group_key"] == "domain"
        assert payload["group_value"] == "example.com"
