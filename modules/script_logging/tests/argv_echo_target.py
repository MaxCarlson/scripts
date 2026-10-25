"""Diagnostic target that echoes sys.argv[1:] as a JSON array."""
import json
import sys

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    json.dump(sys.argv[1:], sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)
