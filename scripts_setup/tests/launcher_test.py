"""Behavioral tests for the scripts-owned manifest and shared-launcher adapter."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts_setup import launcher


def test_missing_command_refreshes_scripts_manifest_and_preserves_arguments(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "scripts_manifest.json"
    calls: list[tuple[Path, Path]] = []
    delegated: list[list[str]] = []

    def refresh(repo_root: Path, target_path: Path) -> Path:
        calls.append((repo_root, target_path))
        target_path.write_text(json.dumps({"commands": {"sample": {}}}), encoding="utf-8")
        return target_path

    monkeypatch.setattr(launcher, "generate_manifest", refresh)
    monkeypatch.setattr(launcher, "shared_launcher_main", lambda argv: delegated.append(list(argv)) or 19)
    arguments = [
        "--manifest", str(manifest), "--command", "sample", "--wrapper", "sample.cmd",
        "--target-python", "python.exe", "--", "--name", "雪 value",
    ]

    assert launcher.main(arguments) == 19
    assert calls == [(tmp_path, manifest)]
    assert delegated == [arguments]


def test_existing_command_does_not_rewrite_manifest(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "scripts_manifest.json"
    manifest.write_text(json.dumps({"commands": {"sample": {}}}), encoding="utf-8")
    monkeypatch.setattr(launcher, "generate_manifest", lambda *_args: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(launcher, "shared_launcher_main", lambda _argv: 0)

    assert launcher.main(["--manifest", str(manifest), "--command", "sample", "--"]) == 0


def test_isolated_script_launcher_preserves_io_arguments_cwd_exit_and_history(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    captured = tmp_path / "captured.json"
    history = tmp_path / "invocations.sqlite3"
    manifest = tmp_path / "scripts_manifest.json"
    wrapper = tmp_path / "sample-wrapper.cmd"
    target.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CAPTURED_ARGS']).write_text(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}), encoding='utf-8')\n"
        "print('target stdout')\n"
        "print('target stderr', file=sys.stderr)\n"
        "raise SystemExit(23)\n",
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps({
            "commands": {
                "sample": {"program_id": "module:sample", "kind": "python_file", "target": str(target)}
            }
        }),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["CAPTURED_ARGS"] = str(captured)
    environment["SCRIPT_LOGGING_INVOCATION_DB"] = str(history)

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(__file__).resolve().parents[1] / "launcher.py"),
            "--manifest", str(manifest),
            "--command", "sample",
            "--wrapper", str(wrapper),
            "--target-python", sys.executable,
            "--", "--name", "雪 value",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 23
    assert result.stdout == "target stdout\n"
    assert result.stderr == "target stderr\n"
    assert json.loads(captured.read_text(encoding="utf-8")) == {
        "args": ["--name", "雪 value"],
        "cwd": str(tmp_path),
    }
    assert history.is_file() and history.stat().st_size > 0
    with sqlite3.connect(history) as connection:
        row = connection.execute(
            "SELECT exit_code, status FROM invocations ORDER BY started_epoch_ms DESC LIMIT 1"
        ).fetchone()
    assert row == (23, "exited")
