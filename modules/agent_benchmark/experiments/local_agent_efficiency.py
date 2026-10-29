"""Dry-run-first, counterbalanced dispatcher for the B0/B2/B3 experiment.

No command is run unless --execute is explicitly passed after separate Gate B approval.
Each command submits exactly one existing agent-benchmark trial.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
CONFIG_PATH = HERE / "local_agent_efficiency_b0_b2_b3.json"


def load_plan() -> tuple[dict, list[dict]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("schema") != "local-agent-efficiency-experiment-v1":
        raise ValueError("Unsupported experiment config schema")
    tasks = config["tasks"]
    if len(tasks) != 4 or len(set(tasks)) != 4:
        raise ValueError("Experiment must contain four distinct task fixtures")
    for task in tasks:
        if not (REPO_ROOT / "modules/agent_benchmark/agent_benchmark/tasks" / task / "task.json").is_file():
            raise ValueError(f"Missing task fixture: {task}")
    assignments = list(itertools.permutations(config["conditions"])) * 2
    rng = random.Random(config["seed"])
    rng.shuffle(assignments)
    blocks = [(task, repetition) for task in tasks
              for repetition in range(1, config["repetitions_per_condition_task"] + 1)]
    rng.shuffle(blocks)
    schedule = []
    for block_index, ((task, repetition), order) in enumerate(zip(blocks, assignments, strict=True)):
        for ordinal, condition in enumerate(order, start=1):
            schedule.append({"index": len(schedule) + 1, "block": block_index + 1,
                             "task": task, "repetition": repetition, "condition": condition,
                             "order_in_block": ordinal})
    if len(schedule) != config["expected_dispatches"]:
        raise ValueError("Generated schedule does not match the declared dispatch count")
    return config, schedule


def build_command(config: dict, item: dict, model_key: str, output_root: Path, state_dir: Path) -> list[str]:
    task_path = REPO_ROOT / "modules/agent_benchmark/agent_benchmark/tasks" / item["task"]
    run_dir = output_root / item["condition"] / item["task"] / f"rep-{item['repetition']:02d}"
    return [sys.executable, "-m", "agent_benchmark.cli", "experiment", "run", "-x",
            "-m", model_key, "-t", str(task_path), "-r", "1",
            "-b", config["budget_profile"], "-c", str(config["context_length"]),
            "--max-ram-percent", str(config["max_ram_percent"]), "--random-seed", str(config["seed"]),
            "--no-allow-model-transitions", "--tool-profile", config["conditions"][item["condition"]]["profile"],
            "-o", str(run_dir), "-s", str(state_dir), "-u", "http://127.0.0.1:4096", "-Q"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-key", required=True, help="Exact verified LM Studio modelKey")
    parser.add_argument("--output-root", type=Path, default=Path("reports/local-agent-efficiency"))
    parser.add_argument("--state-dir", type=Path, default=Path("reports/local-agent-efficiency/state"))
    parser.add_argument("--execute", action="store_true", help="Run all 36 model-backed trials; requires separate Gate B authorization")
    args = parser.parse_args(argv)

    config, schedule = load_plan()
    output_root = args.output_root.resolve()
    state_dir = args.state_dir.resolve()
    commands = [build_command(config, item, args.model_key, output_root, state_dir) for item in schedule]
    print(json.dumps({"config": str(CONFIG_PATH), "seed": config["seed"], "dispatches": len(commands),
                      "duration_cap_seconds": config["max_duration_seconds"], "execute": args.execute,
                      "schedule": [{**item, "argv": command} for item, command in zip(schedule, commands, strict=True)]},
                     indent=2))
    if not args.execute:
        return 0

    start = time.monotonic()
    for item, command in zip(schedule, commands, strict=True):
        remaining = config["max_duration_seconds"] - (time.monotonic() - start)
        if remaining <= 0:
            print("STOP: total 2-hour experiment limit reached", file=sys.stderr)
            return 124
        try:
            result = subprocess.run(command, cwd=REPO_ROOT, timeout=remaining, check=False)
        except subprocess.TimeoutExpired:
            print(f"STOP: dispatch {item['index']} exceeded remaining wall-clock limit; preserve state for reconciliation",
                  file=sys.stderr)
            return 124
        if result.returncode:
            print(f"STOP: dispatch {item['index']} returned {result.returncode}; no retry or later dispatch",
                  file=sys.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
