from __future__ import annotations

import json
from pathlib import Path

import pytest

from development_ledger.writer import ScriptCheck, write_script_results


def test_write_script_results_round_trips(tmp_path: Path):
    path = tmp_path / "nested" / "result.json"

    write_script_results(
        path,
        source="powershell",
        suite="smoke",
        checks=[ScriptCheck(id="check", name="Check", status="passed", item_ids=["AC-1"])],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["tests"][0]["item_ids"] == ["AC-1"]


def test_script_check_rejects_invalid_status():
    with pytest.raises(ValueError, match="Invalid script-check status"):
        ScriptCheck(id="bad", name="Bad", status="unknown").to_dict()
