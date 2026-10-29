import json
import os
import sys
from pathlib import Path


def main():
    root = Path(sys.argv[1])
    answer = json.loads((root / "answer.json").read_text(encoding="utf-8"))
    if answer != {"retryable_statuses": [429, 503], "delay_rule": "min(exponential_backoff, max_delay)"}:
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": 1}), encoding="utf-8")
    print("PASS: retry behavior report matches source")


if __name__ == "__main__":
    main()
