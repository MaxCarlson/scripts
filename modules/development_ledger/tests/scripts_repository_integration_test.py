from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _require_scripts_repository() -> Path:
    manifest = REPO_ROOT / "validation-targets.json"
    if not manifest.is_file():
        pytest.skip("scripts-repository integration files are not available")
    return manifest


def test_validation_manifest_self_hosts_development_ledger():
    manifest_path = _require_scripts_repository()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = manifest["targets"]["development-ledger"]

    assert target["working_directory"] == "modules/development_ledger"
    assert target["context_files"][-1].endswith("00_implementation-plan.md")
    pytest_command = next(
        command for command in target["commands"] if command["name"] == "Development-ledger pytest and coverage suite"
    )
    assert "--junitxml={temp_root}/pytest.xml" in pytest_command["arguments"]

    record_command = target["commands"][-1]
    assert record_command["name"] == "Record development-ledger validation event"
    assert record_command["arguments"][:2] == ["-m", "development_ledger.dispatcher_record"]
    assert record_command["arguments"][-1] == "-w"
    assert "{temp_root}/pytest.xml" in record_command["arguments"]
    assert "{repo_root}/docs/test-results/development-ledger/LATEST.txt" in record_command["arguments"]
