import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    workspace = Path(sys.argv[1]).resolve()
    verifier_dir = Path(__file__).resolve().parent
    result = subprocess.run(
        ["node", str(verifier_dir / "acceptance.cjs"), str(workspace / "src/telemetry_polling.js")],
        check=False,
        capture_output=True,
        text=True,
        timeout=8,
    )
    if result.returncode:
        print(result.stderr[-2000:], file=sys.stderr)
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({
            "nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
            "status": "passed",
            "checks_completed": 27,
        }), encoding="utf-8")
    print("PASS: lifecycle, visibility, cancellation, and bounded telemetry polling")


if __name__ == "__main__":
    main()
