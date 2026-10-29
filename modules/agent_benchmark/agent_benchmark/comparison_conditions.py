"""Record comparable task/runtime conditions separately from model identity."""
import hashlib
import json
import platform
from pathlib import Path

from . import __version__
from .evidence import load_task
from .git_workspace import ISOLATION_POLICY
from .scratch import SCOPE_POLICY


def build_conditions(task_dirs, context_length, budget_profile, budget, runtime, *, provider="lmstudio", tool_profile=None):
    tasks, profiles = {}, {}
    for task_id, task_dir in sorted(task_dirs.items()):
        task = load_task(task_dir)
        digest, verifier = hashlib.sha256(), hashlib.sha256()
        for path in sorted(Path(task_dir).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                name = path.relative_to(task_dir).as_posix()
                digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
                if path.is_relative_to(task.verifier.parent):
                    verifier.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        tasks[task_id] = {"task_sha256": digest.hexdigest(), "verifier_sha256": verifier.hexdigest()}
        profiles[task_id] = (tool_profile or task.opencode_tool_profile) if provider == "lmstudio" else "cli-shell-v1"
    runtime = dict(runtime) if isinstance(runtime, dict) else runtime
    model_identity = runtime.pop("model_identity", None) if isinstance(runtime, dict) else None
    return {"schema": "comparison-conditions-v1", "tasks": tasks, "execution_profiles": profiles,
            "scope_policy": SCOPE_POLICY, "isolation_policy": ISOLATION_POLICY,
            "context_length": context_length,
            "budget": {"profile": budget_profile, **budget},
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "machine": platform.machine(), "harness_version": __version__,
                            "host_fingerprint": hashlib.sha256(platform.node().encode()).hexdigest(),
                            "model_identity": model_identity, "runtime": runtime}}


def runtime_conditions(evidence_dir):
    try:
        evidence = json.loads((evidence_dir / "runtime.json").read_text(encoding="utf-8"))
        if not isinstance(evidence, dict):
            return None
        role = evidence.get("agent_configuration", {})
        permissions = evidence.get("permissions")
        if (not isinstance(role, dict) or not isinstance(permissions, list) or not permissions
                or any(not isinstance(rule, dict) or not all(isinstance(rule.get(key), str) and rule[key]
                    for key in ("permission", "pattern", "action"))
                    or rule["action"] not in {"allow", "deny", "ask"} for rule in permissions)):
            return None
        # Rules are ordered. The benchmark role's exact default-deny rule resets
        # inherited/global grants; only the ordered suffix can affect this role.
        # Preserve suffix order so meaningful overrides remain part of identity.
        reset = {"permission": "*", "pattern": "*", "action": "deny"}
        reset_indexes = [index for index, rule in enumerate(permissions) if rule == reset]
        if not reset_indexes:
            return None
        effective_permissions = permissions[reset_indexes[-1] + 1:]
        allowed_tools = sorted({rule["permission"] for rule in effective_permissions
                                if rule["action"] == "allow" and rule["permission"] != "external_directory"})
        try:
            lifecycle = json.loads((evidence_dir / "lifecycle.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            lifecycle = {}
        return {"kind": "opencode", "version": evidence.get("opencode_version"),
                "bridge_version": evidence.get("bridge_version"), "agent": evidence.get("agent"),
                "prompt_sha256": role.get("prompt_sha256"), "allowed_tools": allowed_tools,
                "permissions_sha256": hashlib.sha256(json.dumps(effective_permissions, sort_keys=True).encode()).hexdigest(),
                "model_identity": lifecycle.get("model_identity"),
                "model_settings": evidence.get("effective_model_settings"),
                "requested_inference_profile": evidence.get("requested_inference_profile")}
    except (OSError, ValueError, TypeError):
        return None
