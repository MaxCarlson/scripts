import importlib.util
import json
import os
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1]) / "src/greeting.py"
    spec = importlib.util.spec_from_file_location("candidate_greeting", path)
    if spec is None or spec.loader is None:
        raise SystemExit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = [("Ada", "Hello, Ada!"), ("  Grace Hopper  ", "Hello, Grace Hopper!"),
             ("", "Hello!"), (" \t ", "Hello!")]
    if any(module.greet(value) != expected for value, expected in cases):
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": len(cases)}), encoding="utf-8")
    print("PASS: greet formats and trims names")


if __name__ == "__main__":
    main()
