from __future__ import annotations

import json
from pathlib import Path


def test_all_shipped_json_schemas_are_valid_json():
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    paths = sorted(schema_root.glob("*.schema.json"))

    assert paths
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload.get("type") == "object" or "oneOf" in payload
