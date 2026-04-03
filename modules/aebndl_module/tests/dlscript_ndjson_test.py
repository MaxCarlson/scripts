#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from pathlib import Path


def _run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout.strip().splitlines(), p.stderr


def test_dlscript_dry_run_emits_valid_json(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    urlfile = tmp_path / "urls.txt"
    urlfile.write_text("https://example.com/video\n", encoding="utf-8")
    cmd = [sys.executable, str(repo_root / "test" / "dlscript.py"), "-f", str(urlfile), "-n", "-q"]
    rc, out_lines, _ = _run(cmd)
    assert rc == 0
    assert out_lines, "no output"
    # Should contain at least start and finish events
    events = [json.loads(ln) for ln in out_lines if ln.strip()]
    kinds = [e.get("event") for e in events]
    assert "start" in kinds
    assert "finish" in kinds

