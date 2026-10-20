"""Comparison identity must come from complete recorded runtime observations."""
import json

from agent_benchmark.comparison_conditions import runtime_conditions


def test_missing_permissions_do_not_hash_into_established_runtime(tmp_path):
    evidence = {"opencode_version": "1.19.3", "bridge_version": "3.0.0", "agent": "benchmark-files",
                "agent_configuration": {"prompt_sha256": "a" * 64}}
    (tmp_path / "runtime.json").write_text(json.dumps(evidence), encoding="utf-8")
    assert runtime_conditions(tmp_path) is None
    evidence["permissions"] = [{"permission": "*", "pattern": "*", "action": "deny"}]
    (tmp_path / "runtime.json").write_text(json.dumps(evidence), encoding="utf-8")
    assert len(runtime_conditions(tmp_path)["permissions_sha256"]) == 64
