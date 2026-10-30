import importlib.util
import json
import os
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1]) / "src/names.py"
    spec = importlib.util.spec_from_file_location("candidate_names", path)
    if spec is None or spec.loader is None:
        raise SystemExit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = module.display_name
    cases = [
        (("Ada", "Lovelace"), {}, "Ada Lovelace"),
        ((" Ada ", " Lovelace "), {"separator": ", "}, "Ada, Lovelace"),
        (("Ada", ""), {"separator": "-"}, "Ada"),
        (("", "Lovelace"), {"separator": "-"}, "Lovelace"),
        (("", ""), {"separator": "-"}, ""),
    ]
    if any(fn(*args, **kwargs) != expected for args, kwargs, expected in cases):
        raise SystemExit(1)
    receipt = os.environ.get("AGENT_BENCH_COMPLETION_PATH")
    if receipt:
        Path(receipt).write_text(json.dumps({"nonce": os.environ["AGENT_BENCH_VERIFICATION_NONCE"],
                                            "status": "passed", "checks_completed": len(cases)}), encoding="utf-8")
    print("PASS: display_name preserves defaults and supports separators")


if __name__ == "__main__":
    main()
