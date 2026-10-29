import importlib.util
import json
import os
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1]) / "src/session_state.py"
    spec = importlib.util.spec_from_file_location("candidate_session_state", path)
    if spec is None or spec.loader is None:
        raise SystemExit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transition = module.transition
    cases = [
        ("idle", "submit", "queued"), ("queued", "start", "running"),
        ("queued", "cancel", "cancelled"), ("running", "succeed", "succeeded"),
        ("running", "fail", "failed"), ("running", "cancel", "cancelled"),
        ("succeeded", "reset", "idle"), ("failed", "reset", "idle"),
        ("cancelled", "reset", "idle"),
    ]
    for state, event, expected in cases:
        if transition(state, event) != expected:
            raise SystemExit(1)
    for state, event in (("idle", "start"), ("queued", "succeed"), ("running", "reset"),
                         ("succeeded", "submit"), ("unknown", "submit"), ("idle", "unknown")):
        try:
            transition(state, event)
        except ValueError:
            continue
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": 15}), encoding="utf-8")
    print("PASS: lifecycle transitions and invalid-transition rejection")


if __name__ == "__main__":
    main()
