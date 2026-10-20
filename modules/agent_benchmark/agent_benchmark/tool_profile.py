"""Project-local, auditable file tools for tasks verified by the harness."""
from __future__ import annotations

import json
from pathlib import Path

FILE_AGENT = "benchmark-files"
FILE_PROFILE = "file-tools-v1"
SAFE_PERMISSIONS = {"read", "edit", "glob", "grep", "list", "StructuredOutput"}
FILE_PROMPT = (
    "Implement the requested deliverable using read/edit/write file tools only. "
    "Do not run tests, invoke a shell, create test scripts, delegate, browse the web, or load skills. "
    "The harness runs the hidden verifier after your final answer; tests are not available in this workspace. "
    "Only modify task-allowed deliverables. Use literal replacement text in edit/write, never diff prefixes. "
    "Finish promptly after implementing the solution. Report checks as not run (harness verifies). "
    "Respect allowed paths and protected files; do not modify .git or opencode.json."
)


def configure_file_agent(workspace: Path) -> None:
    """Only called while building a fresh owned trial, before its initial snapshot."""
    path = workspace / "opencode.json"
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    agents = config.setdefault("agent", {})
    if FILE_AGENT in agents:
        raise ValueError("Task seed already defines the reserved benchmark-files agent")
    agents[FILE_AGENT] = {
        "description": "Benchmark file implementation; hidden verification is performed by the harness",
        "mode": "primary", "prompt": FILE_PROMPT,
        "permission": {"*": "deny", **{name: "allow" for name in sorted(SAFE_PERMISSIONS)},
                       "external_directory": "deny"},
    }
    path.write_text(json.dumps(config, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def validate_file_agent(role: dict) -> None:
    """Fail before session creation if effective permissions are missing or broadened."""
    rules = role.get("permission")
    if not isinstance(rules, list):
        raise ValueError("Cannot verify benchmark-files effective permissions")
    deny_positions = [i for i, rule in enumerate(rules) if isinstance(rule, dict)
                      and rule.get("permission") == "*" and rule.get("pattern") == "*"
                      and rule.get("action") == "deny"]
    if not deny_positions:
        raise ValueError("benchmark-files is missing its default-deny tool policy")
    effective = rules[deny_positions[-1] + 1:]
    for rule in effective:
        if not isinstance(rule, dict) or (rule.get("action") != "deny"
                                        and rule.get("permission") not in SAFE_PERMISSIONS | {"external_directory"}):
            raise ValueError(f"benchmark-files has an unexpected effective tool permission: {rule}")
    for tool in ("read", "edit"):
        actions = [r.get("action") for r in effective if r.get("permission") == tool and r.get("pattern") == "*"]
        if not actions or actions[-1] != "allow":
            raise ValueError(f"benchmark-files cannot use required {tool} tools")
