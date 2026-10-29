import importlib.util
import json
import os
import sys
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    root = Path(sys.argv[1])
    config = load("candidate_retry_config", root / "retry_config.py")
    sys.modules["retry_config"] = config
    client = load("candidate_client", root / "client.py")
    if config.MAX_RETRIES != 5 or client.retry_count(429) != 5 or client.retry_count(503) != 5:
        raise SystemExit(1)
    if client.retry_count(400) != 0 or "return 5" in (root / "client.py").read_text(encoding="utf-8"):
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": 4}), encoding="utf-8")
    print("PASS: configured retries are shared across modules")


if __name__ == "__main__":
    main()
