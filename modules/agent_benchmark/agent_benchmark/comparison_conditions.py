"""Record comparable task/runtime conditions separately from model identity."""
import hashlib
import json
import platform
from pathlib import Path

from . import __version__
from .evidence import load_task
from .git_workspace import ISOLATION_POLICY
from .scratch import SCOPE_POLICY


def build_conditions(task_dirs, context_length, budget_profile, budget, runtime, *, provider="lmstudio"):
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
        profiles[task_id] = task.opencode_tool_profile if provider == "lmstudio" else "cli-shell-v1"
    return {"schema": "comparison-conditions-v1", "tasks": tasks, "execution_profiles": profiles,
            "scope_policy": SCOPE_POLICY, "isolation_policy": ISOLATION_POLICY,
            "context_length": context_length,
            "budget": {"profile": budget_profile, **budget},
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "machine": platform.machine(), "harness_version": __version__, "host_fingerprint": hashlib.sha256(platform.node().encode()).hexdigest(), "runtime": runtime}}


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
        return {"kind": "opencode", "version": evidence.get("opencode_version"), "bridge_version": evidence.get("bridge_version"),
                "agent": evidence.get("agent"), "prompt_sha256": role.get("prompt_sha256"),
                "permissions_sha256": hashlib.sha256(json.dumps(evidence.get("permissions"), sort_keys=True).encode()).hexdigest()}
    except (OSError, ValueError, TypeError):
        return None
