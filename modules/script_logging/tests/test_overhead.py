"""Regression test verifying startup overhead stays within acceptable bounds."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def test_launcher_startup_latency_bounds(tmp_path: Path):
    """Verify that launcher startup overhead remains bounded."""
    db_path = tmp_path / "bench.sqlite3"
    manifest_path = tmp_path / "manifest.json"
    target_py = tmp_path / "fast_target.py"
    target_py.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

    manifest_data = {
        "schema_version": 1,
        "commands": {
            "fast_cmd": {
                "program_id": "pyscript:fast_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    env = os.environ.copy()
    env["SCRIPT_LOGGING_INVOCATION_DB"] = str(db_path)

    # Warmup run to initialize DB schema
    subprocess.run(
        [sys.executable, "-m", "script_logging.launcher", "--manifest", str(manifest_path), "--command", "fast_cmd"],
        env=env,
        check=True,
        capture_output=True,
    )

    # Measure 5 warm runs
    warm_latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        res = subprocess.run(
            [sys.executable, "-m", "script_logging.launcher", "--manifest", str(manifest_path), "--command", "fast_cmd"],
            env=env,
            capture_output=True,
        )
        assert res.returncode == 0
        warm_latencies.append((time.perf_counter() - t0) * 1000)

    avg_warm = sum(warm_latencies) / len(warm_latencies)
    # On Windows native, warm launcher execution should comfortably stay well under 750ms
    assert avg_warm < 750, f"Warm launcher startup took {avg_warm:.1f}ms, exceeding 750ms bound!"
