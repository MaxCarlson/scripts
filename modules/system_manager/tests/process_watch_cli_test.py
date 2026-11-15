"""CLI, legacy compatibility, and packaging tests for proc-stats and sm proc watch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from system_manager import cli as sm_cli
from system_manager import process_watch_cli
from system_manager.process_watch.cli import main as watch_main
from system_manager.process_watch.cli import translate_legacy_args


def test_legacy_arg_translation_preserves_ms_and_bare_glob():
    ns = translate_legacy_args(["-n", "5", "-g", "python", "-s", "memory", "-a", "500", "-u", "250"])
    assert ns.rows == 5
    assert ns.glob == ["*python*"]
    assert ns.sort == "rss"
    assert ns.interval == pytest.approx(0.5)

    ns_wild = translate_legacy_args(["-g", "node*", "-s", "disk", "-a", "200", "-u", "1500"])
    assert ns_wild.glob == ["node*"]
    assert ns_wild.sort == "io_total"
    assert ns_wild.interval == pytest.approx(1.5)


def test_proc_stats_help_and_sm_proc_watch_help(capsys):
    with pytest.raises(SystemExit) as exc1:
        process_watch_cli.main(["--help"])
    assert exc1.value.code == 0
    out1 = capsys.readouterr().out
    assert "--exclude-glob" in out1
    assert "--match-command-line" in out1

    with pytest.raises(SystemExit) as exc2:
        sm_cli.main(["proc", "watch", "--help"])
    assert exc2.value.code == 0
    out2 = capsys.readouterr().out
    assert "--recursive" in out2


def test_one_shot_json_csv_and_output_overwrite_guard(tmp_path, capsys):
    rc = watch_main(["-1", "-i", "0.05", "-n", "3", "-f", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "timestamp_utc" in payload
    assert "processes" in payload
    assert len(payload["processes"]) <= 3

    out_csv = tmp_path / "snap.csv"
    rc_csv = watch_main(["-1", "-i", "0.05", "-n", "2", "-f", "csv", "-o", str(out_csv)])
    assert rc_csv == 0
    assert out_csv.is_file()
    assert "identity_key" in out_csv.read_text(encoding="utf-8")

    # Overwrite without --force fails cleanly
    rc_dup = watch_main(["-1", "-i", "0.05", "-n", "2", "-f", "csv", "-o", str(out_csv)])
    assert rc_dup == 2

    # With --force succeeds
    rc_force = watch_main(["-1", "-i", "0.05", "-n", "2", "-f", "csv", "-o", str(out_csv), "-F"])
    assert rc_force == 0


def test_legacy_pyscript_help():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "pyscripts" / "proc_stats.py"
    res = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)
    assert res.returncode == 0
    assert "--analysis-time" in res.stdout
    assert "--update-frequency" in res.stdout
