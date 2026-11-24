"""Ownership inventory for modules transferred to llm-agent-toolkit.

This registry remains authoritative for package and CLI ownership after a source
directory is retired. A retired source path is intentionally absent; any remaining
scripts source copies must not be installed into scripts/.venv, included in
scripts_manifest.json, or exposed through scripts/bin launchers.

The five shared libraries have since moved to the independent shared-package
distribution registry. Check that registry before using this historical transfer
inventory to report current installation ownership.
"""
from __future__ import annotations

import re
from pathlib import Path

# Authoritative mapping: toolkit-owned module directory -> pyproject.toml [project].name
TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION: dict[str, str] = {
    "agent_abilities": "agent-abilities",
    "agent_benchmark": "agent-benchmark",
    "agent_memory": "agent-memory",
    "agent_skills": "agent-skills",
    "agent_sync": "agent-sync",
    "agt": "agt",
    "ai_orchestrator": "ai_orchestrator",
    "benchmark_core": "benchmark-core",
    "interactive_reports": "interactive-reports",
    "knowledge_manager": "knowledge_manager",
    "llm-interface": "api-parser",
    "llm-models": "llm-models",
    "llm-patcher": "llm-patcher",
    "llm_local": "llm-local",
    "llm_monitor": "llm-monitor",
    "lmstui": "lmstui",
    "local_agent_bridge": "local-agent-bridge",
    "orchestrator_web_viewer": "orchestrator-web-viewer",
    "resource_coordinator": "resource-coordinator",
    "resource_metrics": "resource-metrics",
    "script_logging": "script-logging",
    "web_ai_automator": "web-ai-automator",
    "web_ui_tools": "web-ui-tools",
}

TRANSFERRED_MODULE_DIRS: frozenset[str] = frozenset(TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION.keys())

# Transferred CLI console_scripts now owned and exposed exclusively by llm-agent-toolkit/bin
TRANSFERRED_CLI_COMMANDS: dict[str, str] = {
    "abilities": "agent-abilities",
    "agent-abilities": "agent-abilities",
    "agent-bench": "agent-benchmark",
    "agent-benchmark": "agent-benchmark",
    "agent_benchmark": "agent-benchmark",
    "agent-memory": "agent-memory",
    "agent-skills": "agent-skills",
    "skills": "agent-skills",
    "agent-sync": "agent-sync",
    "agt": "agt",
    "aio": "ai_orchestrator",
    "api-parser": "api-parser",
    "benchmark-core": "benchmark-core",
    "benchmark_core": "benchmark-core",
    "km": "knowledge_manager",
    "llm-monitor": "llm-monitor",
    "llm-patcher": "llm-patcher",
    "lmc": "lmstui",
    "lmst": "lmstui",
    "lmstui": "lmstui",
    "local-agent": "local-agent-bridge",
    "local_agent": "local-agent-bridge",
    "km-web": "orchestrator-web-viewer",
    "koweb": "orchestrator-web-viewer",
    "gpu-coordinator": "resource-coordinator",
    "rc": "resource-coordinator",
    "resource-coordinator": "resource-coordinator",
    "web-ai-automator": "web-ai-automator",
}


def normalize_distribution_name(name: str) -> str:
    """Normalize a Python package/distribution name according to PEP 503."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


TRANSFERRED_NORMALIZED_DISTRIBUTIONS: frozenset[str] = frozenset(
    normalize_distribution_name(dist) for dist in TRANSFERRED_MODULE_DIRECTORY_TO_DISTRIBUTION.values()
)

# Modules that remain scripts-owned even though they are installed from shared distributions.
SCRIPTS_OWNED_SHARED_MODULES: frozenset[str] = frozenset({"termdash", "cross_platform"})


def is_transferred_module_dir(path_or_name: Path | str) -> bool:
    """Return True if path_or_name names a registered toolkit-owned module directory."""
    name = Path(path_or_name).name if isinstance(path_or_name, Path) else str(path_or_name).strip().strip("/\\")
    if "/" in name or "\\" in name:
        name = Path(name).name
    return name in TRANSFERRED_MODULE_DIRS


def is_transferred_distribution(dist_name: str | None) -> bool:
    """Return True if *dist_name* is one of the 23 transferred distributions."""
    if not dist_name:
        return False
    return normalize_distribution_name(dist_name) in TRANSFERRED_NORMALIZED_DISTRIBUTIONS


def is_transferred_cli_command(command_name: str | None) -> bool:
    """Return True if *command_name* is a transferred CLI entry point owned by llm-agent-toolkit."""
    if not command_name:
        return False
    stem = command_name[:-4] if command_name.lower().endswith(".cmd") else command_name
    return stem in TRANSFERRED_CLI_COMMANDS
