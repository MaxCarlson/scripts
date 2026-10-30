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


def test_configured_inference_observations_do_not_become_effective_comparison_settings(tmp_path):
    evidence = {
        "opencode_version": "1.19.3",
        "bridge_version": "3.0.0",
        "agent": "benchmark-files",
        "permissions": [{"permission": "*", "pattern": "*", "action": "deny"}],
        "agent_configuration": {"prompt_sha256": "a" * 64},
        "configured_inference_evidence": {
            "schema": "opencode-configured-inference-v1",
            "context_limit": {"value": 32768, "source": "/provider", "status": "configured"},
            "output_limit": {"value": 8192, "source": "/provider", "status": "configured"},
        },
    }
    (tmp_path / "runtime.json").write_text(json.dumps(evidence), encoding="utf-8")
    assert runtime_conditions(tmp_path)["model_settings"] is None


def test_requested_inference_profile_is_retained_as_comparison_provenance(tmp_path):
    profile = {"schema": "opencode-inference-profile-v1", "context_length": 98304,
               "output_limit": 8192,
               "reasoning": {"mode": "effort", "effort": "low", "provenance": "experiment_profile"},
               "sha256": "b" * 64}
    evidence = {"opencode_version": "1.19.3", "bridge_version": "3.0.0", "agent": "benchmark-files",
                "permissions": [{"permission": "*", "pattern": "*", "action": "deny"}],
                "agent_configuration": {"prompt_sha256": "a" * 64},
                "requested_inference_profile": profile}
    (tmp_path / "runtime.json").write_text(json.dumps(evidence), encoding="utf-8")
    assert runtime_conditions(tmp_path)["requested_inference_profile"] == profile


def test_effective_permission_fingerprint_ignores_only_overridden_prefix(tmp_path):
    base = [{"permission": "read", "pattern": "*", "action": "allow"},
            {"permission": "external_directory", "pattern": "C:/skill/a/*", "action": "allow"}]
    reset = {"permission": "*", "pattern": "*", "action": "deny"}
    effective = [{"permission": "read", "pattern": "*", "action": "allow"},
                 {"permission": "edit", "pattern": "*", "action": "allow"},
                 {"permission": "external_directory", "pattern": "*", "action": "deny"},
                 {"permission": "external_directory", "pattern": "C:/opencode/tool-output/*", "action": "allow"}]
    hashes = []
    for name, prefix in (("one", base), ("two", list(reversed(base)) + [
        {"permission": "external_directory", "pattern": "C:/skill/b/*", "action": "allow"}])):
        evidence = {"opencode_version": "1.19.3", "bridge_version": "3.0.0", "agent": "benchmark-files",
                    "permissions": prefix + [reset] + effective,
                    "agent_configuration": {"prompt_sha256": "a" * 64}}
        folder = tmp_path / name
        folder.mkdir()
        (folder / "runtime.json").write_text(json.dumps(evidence), encoding="utf-8")
        hashes.append(runtime_conditions(folder)["permissions_sha256"])
    assert hashes[0] == hashes[1]


def test_permission_fingerprint_requires_reset_and_preserves_effective_order(tmp_path):
    base = {"opencode_version": "1.19.3", "bridge_version": "3.0.0", "agent": "benchmark-files",
            "agent_configuration": {"prompt_sha256": "a" * 64}}
    reset = {"permission": "*", "pattern": "*", "action": "deny"}
    allow = {"permission": "read", "pattern": "*", "action": "allow"}
    deny = {"permission": "read", "pattern": "secret/*", "action": "deny"}
    hashes = []
    for index, permissions in enumerate(([reset, allow, deny], [reset, deny, allow])):
        folder = tmp_path / str(index)
        folder.mkdir()
        (folder / "runtime.json").write_text(json.dumps({**base, "permissions": permissions}), encoding="utf-8")
        hashes.append(runtime_conditions(folder)["permissions_sha256"])
    assert hashes[0] != hashes[1]

    missing_reset = tmp_path / "missing-reset"
    missing_reset.mkdir()
    (missing_reset / "runtime.json").write_text(json.dumps({**base, "permissions": [allow]}), encoding="utf-8")
    assert runtime_conditions(missing_reset) is None


def test_same_fixture_hashes_support_declared_profile_override():
    from agent_benchmark.comparison_conditions import build_conditions
    from pathlib import Path

    task = Path(__file__).resolve().parents[1] / "agent_benchmark/tasks/py-grep-smoke"
    common = dict(task_dirs={"py-grep-smoke": task}, context_length=32768,
                  budget_profile="canonical-120s",
                  budget={"task_seconds": 120, "grace_seconds": 15, "verifier_seconds": 10},
                  runtime={"kind": "test", "version": "1"})
    conditions = [build_conditions(**common, tool_profile=profile)
                  for profile in ("file-tools-v1", "retrieval-files-v1", "retrieval-structural-v1")]
    assert conditions[0]["tasks"] == conditions[1]["tasks"] == conditions[2]["tasks"]
    assert [condition["execution_profiles"]["py-grep-smoke"] for condition in conditions] == [
        "file-tools-v1", "retrieval-files-v1", "retrieval-structural-v1"]
