"""Project-local, auditable file tools for tasks verified by the harness."""
from __future__ import annotations

import json
import re
import os
from urllib.parse import urlparse

import psutil
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


def _server_environment(server_url: str) -> dict | None:
    """Correlate the loopback listener to a local OpenCode process; expose no secrets."""
    url = urlparse(server_url)
    if url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.scheme != "http":
        return None
    port = url.port or 80
    try:
        listeners = {c.pid for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN
                     and c.laddr.port == port and c.laddr.ip in {"127.0.0.1", "0.0.0.0", "::", "::1"}}
        if len(listeners) != 1 or None in listeners:
            return None
        process = psutil.Process(next(iter(listeners)))
        executable = process.exe()
        if Path(executable).name.lower() not in {"opencode", "opencode.exe"}:
            return None
        # Read only the relevant startup setting into retained evidence; never log full env/cmdline.
        environment = process.environ()
        if environment.get("OPENCODE_TEST_HOME"):
            return None  # Unsupported alternate home layout; fail closed.
        data_home = environment.get("XDG_DATA_HOME")
        return {"pid": process.pid, "process_started": process.create_time(), "executable": executable,
                "xdg_data_home": data_home, "source": "correlated_loopback_listener_environment"}
    except (psutil.Error, OSError, ValueError):
        return None


def runtime_output_evidence(paths: object, version: object, server_url: str) -> dict | None:
    """Verify the pinned runtime's data root independently of any permission allowance."""
    if version != "1.19.3" or not isinstance(paths, dict) or not isinstance(paths.get("home"), str):
        return None
    runtime = _server_environment(server_url)
    if runtime is None:
        return None
    data_home = runtime["xdg_data_home"]
    root = Path(data_home) if data_home else Path(paths["home"]) / ".local/share"
    if not root.is_absolute() or any(c in str(root) for c in ("*", "?")) or ".." in root.parts:
        return None
    output = root / "opencode/tool-output"
    try:
        # OpenCode may not create tool-output until the first truncated tool result.
        if (not (root / "opencode").is_dir() or output.exists() and not output.is_dir()
                or any(p.is_symlink() or p.is_junction() for p in (output, *output.parents))):
            return None
    except OSError:
        return None
    return {**runtime, "directory": str(output), "runtime_version": version,
            "server_home": paths["home"], "path_case_sensitive": os.name != "nt"}


def _match(pattern: str, value: str) -> bool:
    # OpenCode wildcard semantics: only * and ? are operators, not [] or regex.
    return re.fullmatch(re.escape(pattern).replace(r"\*", ".*").replace(r"\?", "."), value, re.DOTALL) is not None


def validate_file_agent(role: dict, *, trusted_output_directory: Path | None = None) -> None:
    """Validate the ordered effective tool contract before session creation."""
    if role.get("name") != FILE_AGENT or role.get("mode") != "primary" or role.get("prompt") != FILE_PROMPT:
        raise ValueError("benchmark-files role name, mode or prompt identity differs from the declared profile")
    rules = role.get("permission")
    if not isinstance(rules, list) or any(
        not isinstance(r, dict) or any(not isinstance(r.get(k), str) or not r[k] for k in ("permission", "pattern", "action"))
        or r["action"] not in {"allow", "deny", "ask"} for r in rules
    ):
        raise ValueError("Cannot verify malformed benchmark-files effective permissions")
    roots = [i for i, r in enumerate(rules) if r == {"permission": "*", "pattern": "*", "action": "deny"}]
    if not roots:
        raise ValueError("benchmark-files is missing its default-deny tool policy")
    effective = rules[roots[-1] + 1:]
    for index, rule in enumerate(effective):
        # A later complete denial for this key overrides every target of this rule.
        if any(r["action"] == "deny" and r["pattern"] == "*" and r["permission"] in (rule["permission"], "*")
               for r in effective[index + 1:]):
            continue
        if rule["action"] == "deny":
            continue
        permission = rule["permission"]
        if rule["action"] != "allow":
            raise ValueError(f"benchmark-files has an interactive effective permission: {rule}")
        if permission == "external_directory":
            expected = (str(trusted_output_directory).replace("\\", "/").rstrip("/") + "/*"
                        if trusted_output_directory is not None else None)
            actual = rule["pattern"].replace("\\", "/")
            if expected is None or actual != expected:
                raise ValueError(f"Unverified external_directory allowance: {rule['pattern']}")
        elif permission not in SAFE_PERMISSIONS:
            raise ValueError(f"benchmark-files has an unexpected effective tool permission: {rule}")
    for tool in ("read", "edit"):
        matches = [r["action"] for r in rules if _match(r["permission"], tool) and r["pattern"] == "*"]
        broad = [i for i, r in enumerate(rules) if _match(r["permission"], tool) and r["pattern"] == "*"]
        narrow_denials = any(_match(r["permission"], tool) and r["action"] != "allow"
                             for r in rules[broad[-1] + 1:]) if broad else True
        if not matches or matches[-1] != "allow" or narrow_denials:
            raise ValueError(f"benchmark-files cannot use required {tool} tools")


def validate_execution_profile(profile: str) -> None:
    if profile == "sandboxed-shell-v1":
        raise ValueError("sandboxed-shell-v1 is unavailable: worker AND verifier containment has not been demonstrated. No host-shell fallback is permitted.")
    if profile not in {"shell-v1", FILE_PROFILE}:
        raise ValueError(f"Unknown task OpenCode tool profile: {profile}")
