"""Resource type definitions for agent abilities.

Each resource type defines the schema, naming conventions, and file structure
for a category of AI agent resources (agents, prompts, instructions, skills).
Modeled after the awesome-copilot specification.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ResourceType:
    """Schema definition for a resource type."""

    name: str
    extension: Optional[str]
    subdir: str
    required_frontmatter: List[str]
    optional_frontmatter: List[str] = field(default_factory=list)
    is_folder: bool = False
    entry_file: Optional[str] = None
    description: str = ""

    def filename_for(self, resource_name: str) -> str:
        """Generate the canonical filename for a resource name."""
        slug = to_kebab_case(resource_name)
        if self.is_folder:
            return slug
        return f"{slug}{self.extension}"

    def validate_name(self, name: str) -> Optional[str]:
        """Validate a resource name. Returns error message or None."""
        if not name:
            return "Name cannot be empty"
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$', name):
            return f"Name '{name}' must be kebab-case (lowercase, hyphens, no leading/trailing hyphens)"
        if self.name == "skill" and len(name) > 64:
            return f"Skill name must be <= 64 characters, got {len(name)}"
        return None

    def validate_frontmatter(self, fm: dict) -> List[str]:
        """Validate frontmatter dict. Returns list of error messages."""
        errors = []
        for field_name in self.required_frontmatter:
            if field_name not in fm or not fm[field_name]:
                errors.append(f"Missing required field: {field_name}")

        if self.name == "skill":
            desc = fm.get("description", "")
            if isinstance(desc, str) and (len(desc) < 10 or len(desc) > 1024):
                errors.append(f"Skill description must be 10-1024 chars, got {len(desc)}")

        return errors


def to_kebab_case(s: str) -> str:
    """Convert a string to kebab-case."""
    s = re.sub(r'[^a-zA-Z0-9\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s)
    s = s.strip('-').lower()
    return s


RESOURCE_TYPES: Dict[str, ResourceType] = {
    "agent": ResourceType(
        name="agent",
        extension=".agent.md",
        subdir="agents",
        required_frontmatter=["description"],
        optional_frontmatter=["name", "model", "tools"],
        description="Custom AI agent definitions with system prompts and tool access",
    ),
    "prompt": ResourceType(
        name="prompt",
        extension=".prompt.md",
        subdir="prompts",
        required_frontmatter=["description"],
        optional_frontmatter=["tools", "model"],
        description="Reusable prompt templates for specific tasks and workflows",
    ),
    "instruction": ResourceType(
        name="instruction",
        extension=".instructions.md",
        subdir="instructions",
        required_frontmatter=["description", "applyTo"],
        optional_frontmatter=[],
        description="Coding standards and guidelines applied to file patterns",
    ),
    "skill": ResourceType(
        name="skill",
        extension=None,
        subdir="skills",
        required_frontmatter=["name", "description"],
        optional_frontmatter=["license", "allowed-tools"],
        is_folder=True,
        entry_file="SKILL.md",
        description="Self-contained folders with instructions and bundled resources",
    ),
    "hook": ResourceType(
        name="hook",
        extension=None,
        subdir="hooks",
        required_frontmatter=[],
        optional_frontmatter=[],
        is_folder=True,
        entry_file="hooks.json",
        description="Automated workflows triggered by agent session events (sessionStart, sessionEnd, etc.)",
    ),
    "collection": ResourceType(
        name="collection",
        extension=".collection.yml",
        subdir="collections",
        required_frontmatter=["id", "name", "description"],
        optional_frontmatter=["tags", "items", "display"],
        description="Curated groups of related agents, prompts, instructions, and skills",
    ),
}


def detect_resource_type(path_str: str) -> Optional[str]:
    """Detect resource type from a file path or directory structure.

    Returns the type key ('agent', 'prompt', 'instruction', 'skill') or None.
    """
    from pathlib import Path
    p = Path(path_str)

    if p.is_dir():
        if (p / "SKILL.md").exists():
            return "skill"
        if (p / "hooks.json").exists():
            return "hook"
        return None

    name = p.name
    if name.endswith(".collection.yml"):
        return "collection"
    for type_key, rtype in RESOURCE_TYPES.items():
        if rtype.extension and name.endswith(rtype.extension):
            return type_key

    return None
