"""Explicit, versioned comparison conditions; unknown metadata is never equivalence."""
import hashlib
import json
import math


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
