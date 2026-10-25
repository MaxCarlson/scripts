"""Benchmark startup and execution overhead of the unified launcher engine."""
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run_benchmark(iterations: int = 40):
    print(f"Running startup overhead benchmark ({iterations} iterations)...")

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        db_path = tmp_dir / "bench_invocations.sqlite3"
        manifest_path = tmp_dir / "manifest.json"
        target_py = tmp_dir / "noop_target.py"
        target_py.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

        manifest_data = {
            "schema_version": 1,
            "commands": {
                "bench_cmd": {
                    "program_id": "pyscript:noop_target.py",
                    "kind": "python_file",
                    "target": str(target_py),
                }
            },
        }
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

        env = os.environ.copy()
        env["SCRIPT_LOGGING_INVOCATION_DB"] = str(db_path)

        # 1. Direct Python baseline: python noop_target.py
        direct_times = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            subprocess.run([sys.executable, str(target_py)], env=env, check=True, capture_output=True)
            direct_times.append((time.perf_counter() - t0) * 1000)

        # 2. Cold launcher start (first invocation creates SQLite DB, runs migrations, writes start/finish)
        t_cold_start = time.perf_counter()
        cold_db_path = tmp_dir / "cold_invocations.sqlite3"
        env_cold = os.environ.copy()
        env_cold["SCRIPT_LOGGING_INVOCATION_DB"] = str(cold_db_path)
        subprocess.run(
            [sys.executable, "-m", "script_logging.launcher", "--manifest", str(manifest_path), "--command", "bench_cmd"],
            env=env_cold,
            check=True,
            capture_output=True,
        )
        cold_latency_ms = (time.perf_counter() - t_cold_start) * 1000

        # 3. Warm launcher executions
        warm_times = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            subprocess.run(
                [sys.executable, "-m", "script_logging.launcher", "--manifest", str(manifest_path), "--command", "bench_cmd"],
                env=env,
                check=True,
                capture_output=True,
            )
            warm_times.append((time.perf_counter() - t0) * 1000)

    # Compute statistics
    direct_p50 = statistics.median(direct_times)
    direct_p95 = sorted(direct_times)[int(len(direct_times) * 0.95)]
    warm_p50 = statistics.median(warm_times)
    warm_p95 = sorted(warm_times)[int(len(warm_times) * 0.95)]
    overhead_p50 = warm_p50 - direct_p50
    overhead_p95 = warm_p95 - direct_p95

    print("\n=== STARTUP OVERHEAD BENCHMARK RESULTS ===")
    print(f"Direct Baseline Execution: p50={direct_p50:.2f}ms, p95={direct_p95:.2f}ms")
    print(f"Cold Launcher First Run:   {cold_latency_ms:.2f}ms (includes DB creation & schema init)")
    print(f"Warm Launcher Execution:   p50={warm_p50:.2f}ms, p95={warm_p95:.2f}ms")
    print(f"Net Logging Overhead:      p50={overhead_p50:.2f}ms, p95={overhead_p95:.2f}ms")
    print("==========================================\n")

    return {
        "direct_p50_ms": direct_p50,
        "direct_p95_ms": direct_p95,
        "cold_ms": cold_latency_ms,
        "warm_p50_ms": warm_p50,
        "warm_p95_ms": warm_p95,
        "overhead_p50_ms": overhead_p50,
        "overhead_p95_ms": overhead_p95,
    }


if __name__ == "__main__":
    run_benchmark()
