"""Explicit, versioned comparison conditions; unknown metadata is never equivalence."""
import hashlib
import json
import math


TOOL_INTERVENTION_PROFILES = {
    "B0": ("file-tools-v1", ["StructuredOutput", "edit", "glob", "grep", "list", "read"]),
    "B2": ("retrieval-files-v1", ["StructuredOutput", "code_context", "code_locate", "edit", "glob", "grep", "list", "read"]),
    "B3": ("retrieval-structural-v1", [
        "StructuredOutput", "code_context", "code_locate", "code_map", "code_symbols",
        "edit", "glob", "grep", "list", "read",
    ]),
}
_INTERVENTION_PATHS = [
    "execution_profiles",
    "environment.runtime.allowed_tools",
    "environment.runtime.permissions_sha256",
]


def contract_error(value: object) -> str | None:
    if not isinstance(value, dict) or value.get("schema") != "comparison-conditions-v1":
        return "Missing or unsupported comparison contract"
    required = {"tasks", "execution_profiles", "scope_policy", "isolation_policy", "context_length", "budget", "environment"}
    if not required.issubset(value):
        return "Comparison contract is missing required conditions"
    def known(item):
        if item is None or isinstance(item, str) and (not item.strip() or item.lower() in {"unknown", "unavailable", "unverified", "n/a"}):
            return False
        if isinstance(item, dict):
            return bool(item) and all(isinstance(k, str) and known(v) for k, v in item.items())
        if isinstance(item, list):
            return bool(item) and all(known(v) for v in item)
        return isinstance(item, (str, bool, int, float)) and (not isinstance(item, float) or math.isfinite(item))
    if not known(value):
        return "Comparison contract has unknown, empty or malformed conditions"
    if not isinstance(value["context_length"], int) or isinstance(value["context_length"], bool) or value["context_length"] <= 0:
        return "Comparison context is not established"
    def text(item):
        return isinstance(item, str) and bool(item.strip()) and item.lower() not in {"unknown", "unavailable", "unverified", "n/a"}
    if not all(text(value[name]) for name in ("scope_policy", "isolation_policy")):
        return "Scope/isolation policies must be established strings"
    environment = value["environment"]
    if not isinstance(environment, dict) or not all(text(environment.get(k)) for k in ("python", "platform", "machine", "harness_version")):
        return "Environment identity is incomplete"
    runtime = environment.get("runtime")
    if not isinstance(runtime, dict) or not text(runtime.get("kind")) or not text(runtime.get("version")):
        return "Runtime identity/version is incomplete"
    tasks = value["tasks"]
    if not isinstance(tasks, dict) or not isinstance(value["execution_profiles"], dict) or set(tasks) != set(value["execution_profiles"]):
        return "Task identity/profile conditions are inconsistent"
    if not all(text(key) and text(profile) for key, profile in value["execution_profiles"].items()):
        return "Execution profile identities must be established strings"
    for task in tasks.values():
        if not isinstance(task, dict) or not all(isinstance(task.get(k), str) and len(task[k]) == 64
            and all(c in "0123456789abcdef" for c in task[k]) for k in ("task_sha256", "verifier_sha256")):
            return "Task/verifier identity is not a SHA-256 digest"
    if not isinstance(value["budget"], dict) or not {"profile", "task_seconds", "grace_seconds", "verifier_seconds"}.issubset(value["budget"]):
        return "Budget conditions are incomplete"
    budget = value["budget"]
    if not text(budget["profile"]):
        return "Budget profile identity is incomplete"
    for name in ("task_seconds", "verifier_seconds", "grace_seconds"):
        number = budget[name]
        if (not isinstance(number, (float, int)) or isinstance(number, bool) or not math.isfinite(number)
                or number < 0 or name != "grace_seconds" and number == 0):
            return "Budget values must be finite positive numbers (grace may be zero)"
    return None


def contract_key(value: object) -> str | None:
    if contract_error(value):
        return None
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def declared_tool_intervention_error(
    baseline_contract: object,
    candidate_contract: object,
    baseline_metadata: object,
    candidate_metadata: object,
) -> tuple[str | None, dict[str, str] | None]:
    """Validate the one explicit tool-surface experiment supported by this benchmark.

    Ordinary comparisons still require exact contract equality. This opt-in path only
    admits B0/B2/B3 when task/model/runtime/budget/prompt controls are equal and the
    changed profiles and effective tool permissions match the declared levels.
    """
    for contract in (baseline_contract, candidate_contract):
        if isinstance(contract, dict) and isinstance(contract.get("environment"), dict):
            runtime = contract["environment"].get("runtime")
            if isinstance(runtime, dict) and runtime.get("model_settings") is None:
                return "Effective inference settings are missing from run provenance", None
            if contract["environment"].get("model_identity") is None:
                return "Exact model identity and quantization are missing from run provenance", None
        error = contract_error(contract)
        if error:
            return error, None
    if not isinstance(baseline_contract, dict) or not isinstance(candidate_contract, dict):
        return "Missing comparison contract", None
    if not isinstance(baseline_metadata, dict) or not isinstance(candidate_metadata, dict):
        return "Missing run metadata", None
    base_intervention = baseline_metadata.get("intervention_contract")
    candidate_intervention = candidate_metadata.get("intervention_contract")
    if not isinstance(base_intervention, dict) or not isinstance(candidate_intervention, dict):
        return "Missing declared intervention provenance", None

    expected_keys = {"schema", "design_id", "factor", "allowed_differences", "conditions", "assignment"}
    if set(base_intervention) != expected_keys or set(candidate_intervention) != expected_keys:
        return "Intervention contract fields are missing or unexpected", None
    if any(base_intervention[key] != candidate_intervention[key]
           for key in ("schema", "design_id", "factor", "allowed_differences", "conditions")):
        return "Intervention design definitions differ", None
    if (base_intervention["schema"] != "declared-tool-intervention-v1"
            or base_intervention["design_id"] != "local-agent-efficiency-b0-b2-b3-v1"
            or base_intervention["factor"] != "tool_profile"
            or base_intervention["allowed_differences"] != _INTERVENTION_PATHS):
        return "Unsupported or overbroad intervention design", None
    conditions = base_intervention["conditions"]
    expected_conditions = {
        condition: {"profile": profile, "allowed_tools": tools}
        for condition, (profile, tools) in TOOL_INTERVENTION_PROFILES.items()
    }
    if conditions != expected_conditions:
        return "Declared B0/B2/B3 tool surfaces do not match the approved profile matrix", None

    base_id, candidate_id = base_intervention["assignment"], candidate_intervention["assignment"]
    if base_id not in TOOL_INTERVENTION_PROFILES or candidate_id not in TOOL_INTERVENTION_PROFILES:
        return "Unknown intervention condition assignment", None
    if base_id == candidate_id:
        return "Intervention comparison requires two distinct conditions", None

    def clone(value: dict) -> dict:
        return json.loads(json.dumps(value))

    base_normalized, candidate_normalized = clone(baseline_contract), clone(candidate_contract)
    for contract in (base_normalized, candidate_normalized):
        contract.pop("execution_profiles", None)
        runtime = contract.get("environment", {}).get("runtime", {})
        runtime.pop("allowed_tools", None)
        runtime.pop("permissions_sha256", None)
    if base_normalized != candidate_normalized:
        differing = sorted(key for key in set(base_normalized) | set(candidate_normalized)
                           if base_normalized.get(key) != candidate_normalized.get(key))
        return "Undeclared comparison conditions differ: " + ", ".join(differing), None

    for condition_id, contract in ((base_id, baseline_contract), (candidate_id, candidate_contract)):
        expected_profile, expected_tools = TOOL_INTERVENTION_PROFILES[condition_id]
        profiles = contract.get("execution_profiles")
        if not isinstance(profiles, dict) or not profiles or set(profiles.values()) != {expected_profile}:
            return f"{condition_id} execution profile does not match its declared assignment", None
        runtime = contract.get("environment", {}).get("runtime", {})
        tools = runtime.get("allowed_tools") if isinstance(runtime, dict) else None
        permissions_hash = runtime.get("permissions_sha256") if isinstance(runtime, dict) else None
        if tools != expected_tools:
            return f"{condition_id} effective tool surface does not match its declaration", None
        if not isinstance(permissions_hash, str) or len(permissions_hash) != 64 or any(
            char not in "0123456789abcdef" for char in permissions_hash
        ):
            return f"{condition_id} effective permission provenance is missing", None

    base_runtime = baseline_contract["environment"]["runtime"]
    candidate_runtime = candidate_contract["environment"]["runtime"]
    for runtime in (base_runtime, candidate_runtime):
        if (runtime.get("agent") != "benchmark-files"
                or not isinstance(runtime.get("prompt_sha256"), str)
                or len(runtime["prompt_sha256"]) != 64
                or not isinstance(runtime.get("model_settings"), dict)):
            return "Worker identity, prompt, or effective model settings are not established", None

    model = baseline_contract["environment"].get("model_identity")
    if not isinstance(model, dict) or model != candidate_contract["environment"].get("model_identity"):
        return "Matched exact model identity and quantization are not established", None
    if (model.get("provider") != "lmstudio" or not isinstance(model.get("runtime_model_id"), str)
            or not model["runtime_model_id"] or not isinstance(model.get("quantization"), str)
            or not model["quantization"] or model["quantization"].lower() in {"unknown", "unverified"}):
        return "Exact model ID or quantization is missing", None
    settings = base_runtime["model_settings"]
    if settings != candidate_runtime["model_settings"]:
        return "Effective inference settings differ between conditions", None
    required_settings = {"context", "output", "temperature", "top_p", "reasoning_effort", "options_sha256"}
    if not required_settings.issubset(settings):
        return "Effective inference settings are incomplete", None
    if not all(isinstance(settings.get(key), int) and not isinstance(settings.get(key), bool) and settings[key] > 0
               for key in ("context", "output")):
        return "Effective context/output limits are missing", None
    if not all(isinstance(settings.get(key), (int, float)) and not isinstance(settings.get(key), bool)
               and math.isfinite(settings[key]) for key in ("temperature", "top_p")):
        return "Effective temperature/top_p settings are missing", None
    if not isinstance(settings.get("reasoning_effort"), str) or not settings["reasoning_effort"]:
        return "Effective reasoning setting is missing", None
    if not isinstance(settings.get("options_sha256"), str) or len(settings["options_sha256"]) != 64:
        return "Effective provider options fingerprint is missing", None
    if settings["context"] != baseline_contract["context_length"]:
        return "Effective context does not match the comparison context", None
    fingerprints = [metadata.get("suite_fingerprint")
                    for metadata in (baseline_metadata, candidate_metadata)]
    if any(not isinstance(value, str) or len(value) != 64
           or any(char not in "0123456789abcdef" for char in value) for value in fingerprints):
        return "Suite provenance fingerprint is missing or invalid", None
    if fingerprints[0] != fingerprints[1]:
        return "Suite provenance fingerprints differ", None

    return None, {"baseline_condition": base_id, "candidate_condition": candidate_id,
                  "design_id": base_intervention["design_id"]}
