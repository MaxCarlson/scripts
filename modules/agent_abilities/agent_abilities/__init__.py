"""
Agent Abilities - Universal resource manager for AI coding agents.

Manages agents, prompts, instructions, and skills for Claude Code, Codex CLI,
Cursor, and other AI coding assistants.
"""
from .manager import (
    list_resources,
    add_resource,
    remove_resource,
    create_resource,
    prune,
    sync_to_cli,
    sync_all_clis,
    scan_for_resources,
    auto_register_from_scan,
    get_resource_info,
    validate_resource,
    CENTRAL_DIR,
    SOURCE_DIR,
    CLI_DIRS,
)
from .resource_types import RESOURCE_TYPES, ResourceType, detect_resource_type, to_kebab_case
from .templates import (
    generate_agent,
    generate_collection,
    generate_hook,
    generate_prompt,
    generate_instruction,
    generate_skill,
)

__version__ = "0.3.0"

__all__ = [
    # Manager
    "list_resources",
    "add_resource",
    "remove_resource",
    "create_resource",
    "prune",
    "sync_to_cli",
    "sync_all_clis",
    "scan_for_resources",
    "auto_register_from_scan",
    "get_resource_info",
    "validate_resource",
    "CENTRAL_DIR",
    "SOURCE_DIR",
    "CLI_DIRS",
    # Resource types
    "RESOURCE_TYPES",
    "ResourceType",
    "detect_resource_type",
    "to_kebab_case",
    # Templates
    "generate_agent",
    "generate_collection",
    "generate_hook",
    "generate_prompt",
    "generate_instruction",
    "generate_skill",
]
