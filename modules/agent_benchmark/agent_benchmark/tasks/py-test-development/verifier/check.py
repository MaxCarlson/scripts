import os
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    test_file = root / "tests/test_normalize.py"
    source = test_file.read_text(encoding="utf-8")
    if "unittest.TestCase" not in source or source.count("def test_") < 4:
        raise SystemExit(1)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-B", str(test_file)], cwd=root, env=env,
                            capture_output=True, text=True, timeout=8)
    if result.returncode or "Ran 4 tests" not in result.stderr + result.stdout:
        print(result.stdout, result.stderr, file=sys.stderr)
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        import json
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": 4}), encoding="utf-8")
    print("PASS: four normalize tests execute successfully")


if __name__ == "__main__":
    main()
