"""Template generators for each resource type.

Generates properly-formatted markdown files with YAML frontmatter
following the awesome-copilot specification patterns.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from .resource_types import to_kebab_case


def generate_agent(
    name: str,
    description: str,
    model: Optional[str] = None,
    tools: Optional[List[str]] = None,
) -> str:
    """Generate an agent markdown file with frontmatter and skeleton body."""
    slug = to_kebab_case(name)
    display_name = name.replace("-", " ").title()

    fm_lines = [
        "---",
        f"name: '{display_name}'",
        f"description: '{_escape_yaml(description)}'",
    ]
    if model:
        fm_lines.append(f"model: {model}")
    if tools:
        tools_str = ", ".join(f"'{t}'" for t in tools)
        fm_lines.append(f"tools: [{tools_str}]")
    fm_lines.append("---")

    body = f"""
# {display_name}

You are {display_name}, a specialized AI coding agent.

## Mission

{description}

## Core Principles

- Confirm understanding of the task before taking action.
- Prefer existing project patterns and conventions.
- Explain decisions and trade-offs when relevant.

## Workflow

1. **Understand** -- Read relevant code and context before acting.
2. **Plan** -- Outline approach and get confirmation on non-trivial changes.
3. **Execute** -- Implement changes following project conventions.
4. **Verify** -- Run tests and validate the changes work as expected.
"""
    return "\n".join(fm_lines) + "\n" + body.lstrip("\n")


def generate_prompt(
    name: str,
    description: str,
    tools: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> str:
    """Generate a prompt markdown file with frontmatter and skeleton body."""
    display_name = name.replace("-", " ").title()

    fm_lines = [
        "---",
        f"description: '{_escape_yaml(description)}'",
    ]
    if tools:
        tools_str = ", ".join(f"'{t}'" for t in tools)
        fm_lines.append(f"tools: [{tools_str}]")
    if model:
        fm_lines.append(f"model: {model}")
    fm_lines.append("---")

    body = f"""
# {display_name}

## Instructions

{description}

## Workflow

1. Analyze the current context and gather relevant information.
2. Apply the prompt logic to produce the desired output.
3. Verify the output meets quality standards.

## Expected Output

Describe the expected output format and content here.
"""
    return "\n".join(fm_lines) + "\n" + body.lstrip("\n")


def generate_instruction(
    name: str,
    description: str,
    apply_to: str,
) -> str:
    """Generate an instruction markdown file with frontmatter and skeleton body."""
    display_name = name.replace("-", " ").title()

    fm_lines = [
        "---",
        f"description: '{_escape_yaml(description)}'",
        f"applyTo: '{apply_to}'",
        "---",
    ]

    body = f"""
# {display_name}

{description}

## Conventions

- Follow existing project patterns and style.
- Maintain consistency with the surrounding codebase.

## Guidelines

<!-- Add specific coding standards, naming conventions, or rules here -->

## Examples

<!-- Add before/after examples showing correct usage -->
"""
    return "\n".join(fm_lines) + "\n" + body.lstrip("\n")


def generate_skill(
    name: str,
    description: str,
    license_type: Optional[str] = None,
    allowed_tools: Optional[str] = None,
    with_refs: bool = False,
    with_scripts: bool = False,
    with_assets: bool = False,
) -> Dict[str, Optional[str]]:
    """Generate a skill folder structure.

    Returns a dict mapping relative paths to file contents.
    Paths ending with '/' are directories (content is None).
    """
    slug = to_kebab_case(name)

    fm_lines = [
        "---",
        f"name: {slug}",
        f"description: '{_escape_yaml(description)}'",
    ]
    if license_type:
        fm_lines.append(f"license: {license_type}")
    if allowed_tools:
        fm_lines.append(f"allowed-tools: {allowed_tools}")
    fm_lines.append("---")

    display_name = name.replace("-", " ").title()
    body = f"""
# {display_name}

## Overview

{description}

## When to Use This Skill

- Describe specific triggers and scenarios here.
- Include keywords that agents should match on.

## Workflow

1. **Step 1** -- Describe the first action.
2. **Step 2** -- Describe the next action.
3. **Step 3** -- Describe validation/output.
"""

    files: Dict[str, Optional[str]] = {
        "SKILL.md": "\n".join(fm_lines) + "\n" + body.lstrip("\n"),
    }

    if with_refs:
        files["references/"] = None
        files["references/.gitkeep"] = ""

    if with_scripts:
        files["scripts/"] = None
        files["scripts/.gitkeep"] = ""

    if with_assets:
        files["assets/"] = None
        files["assets/.gitkeep"] = ""

    return files


def write_skill_folder(base_dir: Path, name: str, files: Dict[str, Optional[str]]) -> Path:
    """Write the skill folder structure to disk.

    Args:
        base_dir: Parent directory (e.g., custom_agents/skills/)
        name: Skill name (kebab-case)
        files: Dict from generate_skill()

    Returns:
        Path to the created skill folder.
    """
    slug = to_kebab_case(name)
    skill_dir = base_dir / slug
    skill_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in files.items():
        full_path = skill_dir / rel_path
        if rel_path.endswith("/"):
            full_path.mkdir(parents=True, exist_ok=True)
        else:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content or "")

    return skill_dir


def generate_hook(
    name: str,
    description: str,
    events: Optional[List[str]] = None,
) -> Dict[str, Optional[str]]:
    """Generate a hook folder structure with hooks.json + shell script.

    Returns a dict mapping relative paths to file contents.
    Paths ending with '/' are directories (content is None).
    """
    if events is None:
        events = ["sessionStart"]

    hooks_config: Dict[str, Any] = {"version": 1, "hooks": {}}
    for event in events:
        hooks_config["hooks"][event] = [
            {
                "type": "command",
                "command": f"./{to_kebab_case(name)}.sh",
            }
        ]

    import json
    hooks_json = json.dumps(hooks_config, indent=2)

    slug = to_kebab_case(name)
    shell_script = (
        "#!/usr/bin/env bash\n"
        f"# {description}\n"
        f'# Hook: {slug}\n'
        f'# Events: {", ".join(events)}\n'
        "\n"
        'set -euo pipefail\n'
        "\n"
        '# Add your hook logic here\n'
        'echo "Hook triggered: $0"\n'
    )

    readme = (
        f"# {name.replace('-', ' ').title()}\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Events\n"
        f"\n"
    )
    for event in events:
        readme += f"- `{event}`\n"

    return {
        "hooks.json": hooks_json,
        f"{slug}.sh": shell_script,
        "README.md": readme,
    }


def write_hook_folder(base_dir: Path, name: str, files: Dict[str, Optional[str]]) -> Path:
    """Write the hook folder structure to disk.

    Args:
        base_dir: Parent directory (e.g., custom_agents/hooks/)
        name: Hook name (kebab-case)
        files: Dict from generate_hook()

    Returns:
        Path to the created hook folder.
    """
    slug = to_kebab_case(name)
    hook_dir = base_dir / slug
    hook_dir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in files.items():
        full_path = hook_dir / rel_path
        if rel_path.endswith("/"):
            full_path.mkdir(parents=True, exist_ok=True)
        else:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content or "")

    # Make shell scripts executable
    for rel_path in files:
        if rel_path.endswith(".sh"):
            (hook_dir / rel_path).chmod(0o755)

    return hook_dir


def generate_collection(
    name: str,
    description: str,
    tags: Optional[List[str]] = None,
    items: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Generate a .collection.yml file content."""
    slug = to_kebab_case(name)
    display_name = name.replace("-", " ").title()

    lines = [
        f"id: {slug}",
        f"name: '{_escape_yaml(display_name)}'",
        f"description: '{_escape_yaml(description)}'",
    ]

    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {tag}")
    else:
        lines.append("tags: []")

    if items:
        lines.append("items:")
        for item in items:
            lines.append(f"  - type: {item.get('type', 'agent')}")
            lines.append(f"    path: {item.get('path', '')}")
    else:
        lines.append("items:")
        lines.append("  # - type: agent")
        lines.append("  #   path: agents/my-agent.agent.md")

    lines.append(f"display:")
    lines.append(f"  icon: collection")
    lines.append(f"  color: blue")
    lines.append("")

    return "\n".join(lines)


def _escape_yaml(s: str) -> str:
    """Escape a string for use inside single-quoted YAML values."""
    return s.replace("'", "''")
