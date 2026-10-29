import importlib.util
import json
import os
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1]) / "score.py"
    spec = importlib.util.spec_from_file_location("candidate_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = module.clamp_score
    cases = [(-20, 0), (0, 0), (42, 42), (100, 100), (130, 100)]
    if any(fn(value) != expected for value, expected in cases):
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": len(cases)}), encoding="utf-8")
    print("PASS: clamp_score bounds and preserves values")


if __name__ == "__main__":
    main()
