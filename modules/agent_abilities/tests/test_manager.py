"""Tests for agent_abilities manager module."""
import tempfile
import os
from pathlib import Path
import pytest

from agent_abilities.manager import (
    list_resources,
    add_resource,
    remove_resource,
    create_resource,
    scan_for_resources,
    get_resource_info,
    parse_frontmatter,
    parse_hooks_json,
    parse_collection_yaml,
    parse_resource,
    validate_resource,
    CENTRAL_DIR,
    CLI_DIRS,
)
from agent_abilities.resource_types import detect_resource_type
from agent_abilities.templates import generate_hook, generate_collection


@pytest.fixture
def temp_skill_dir():
    """Create a temporary skill directory with SKILL.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_md = Path(tmpdir) / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: test-skill\n"
            "description: A test skill for pytest verification\n"
            "metadata:\n"
            "  version: 1.0.0\n"
            "compatibility:\n"
            "  - codex-cli\n"
            "  - claude-code\n"
            "---\n"
            "\n"
            "# Test Skill\n"
            "\n"
            "This is a test skill.\n"
        )
        yield tmpdir


@pytest.fixture
def temp_agent_file():
    """Create a temporary agent file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_file = Path(tmpdir) / "test-agent.agent.md"
        agent_file.write_text(
            "---\n"
            "description: A test agent for pytest verification\n"
            "model: claude-opus-4-6\n"
            "---\n"
            "\n"
            "# Test Agent\n"
            "\n"
            "You are a test agent.\n"
        )
        yield str(agent_file)


@pytest.fixture
def temp_prompt_file():
    """Create a temporary prompt file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_file = Path(tmpdir) / "test-prompt.prompt.md"
        prompt_file.write_text(
            "---\n"
            "description: A test prompt for pytest verification\n"
            "---\n"
            "\n"
            "# Test Prompt\n"
            "\n"
            "Do the test thing.\n"
        )
        yield str(prompt_file)


@pytest.fixture
def temp_instruction_file():
    """Create a temporary instruction file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        instr_file = Path(tmpdir) / "test-rules.instructions.md"
        instr_file.write_text(
            "---\n"
            "description: Test coding standards\n"
            "applyTo: '**.py'\n"
            "---\n"
            "\n"
            "# Test Rules\n"
            "\n"
            "Follow these test rules.\n"
        )
        yield str(instr_file)


# ── Frontmatter Parsing ─────────────────────────────────────────────────────


def test_parse_frontmatter_skill(temp_skill_dir):
    """Test parsing SKILL.md frontmatter."""
    result = parse_frontmatter(Path(temp_skill_dir) / "SKILL.md")

    assert result is not None
    assert result["name"] == "test-skill"
    assert result["description"] == "A test skill for pytest verification"
    assert result["metadata"]["version"] == "1.0.0"


def test_parse_frontmatter_agent(temp_agent_file):
    """Test parsing agent file frontmatter."""
    result = parse_frontmatter(Path(temp_agent_file))

    assert result is not None
    assert result["description"] == "A test agent for pytest verification"
    assert result["model"] == "claude-opus-4-6"


def test_parse_frontmatter_missing():
    """Test parsing nonexistent file returns None."""
    result = parse_frontmatter(Path("/nonexistent/file.md"))
    assert result is None


# ── Resource Parsing ─────────────────────────────────────────────────────────


def test_parse_resource_skill(temp_skill_dir):
    """Test parsing a skill resource."""
    result = parse_resource(Path(temp_skill_dir), "skill")

    assert result is not None
    assert result["type"] == "skill"
    assert result["name"] == "test-skill"


def test_parse_resource_agent(temp_agent_file):
    """Test parsing an agent resource."""
    result = parse_resource(Path(temp_agent_file), "agent")

    assert result is not None
    assert result["type"] == "agent"


def test_parse_resource_auto_detect(temp_agent_file):
    """Test auto-detecting resource type."""
    result = parse_resource(Path(temp_agent_file))

    assert result is not None
    assert result["type"] == "agent"


# ── Scan ─────────────────────────────────────────────────────────────────────


def test_scan_for_skills(temp_skill_dir):
    """Test scanning for skill resources."""
    skills = scan_for_resources(temp_skill_dir)

    assert len(skills) >= 1
    names = [s["name"] for s in skills]
    assert "test-skill" in names


def test_scan_empty_directory():
    """Test scanning directory with no resources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        found = scan_for_resources(tmpdir)
        assert found == []


def test_scan_mixed_resources():
    """Test scanning a directory with multiple resource types."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create an agent file
        agent = Path(tmpdir) / "my-agent.agent.md"
        agent.write_text("---\ndescription: test agent\n---\n\n# Agent\n")

        # Create a skill folder
        skill_dir = Path(tmpdir) / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: test skill for scanning\n---\n\n# Skill\n"
        )

        found = scan_for_resources(tmpdir)
        types_found = {r["type"] for r in found}
        assert "agent" in types_found
        assert "skill" in types_found


# ── Add / Remove ─────────────────────────────────────────────────────────────


def test_add_and_remove_skill(temp_skill_dir):
    """Test adding and removing a skill resource."""
    success, msg = add_resource(temp_skill_dir, "skill", "pytest-test-skill")
    assert success
    assert "pytest-test-skill" in msg

    # Verify via get_resource_info
    info = get_resource_info("pytest-test-skill", "skill")
    assert info is not None
    assert info["description"] == "A test skill for pytest verification"

    # Remove
    success, msg = remove_resource("pytest-test-skill", "skill")
    assert success

    # Verify removed
    info = get_resource_info("pytest-test-skill", "skill")
    assert info is None


def test_add_nonexistent_path():
    """Test adding from nonexistent path fails."""
    success, msg = add_resource("/nonexistent/path/to/resource", "agent")
    assert not success
    assert "not exist" in msg.lower() or "does not exist" in msg.lower()


def test_remove_nonexistent_resource():
    """Test removing nonexistent resource fails."""
    success, msg = remove_resource("definitely-not-real-xyz", "agent")
    assert not success


# ── List ─────────────────────────────────────────────────────────────────────


def test_list_resources():
    """Test listing resources returns a list."""
    resources = list_resources()
    assert isinstance(resources, list)


def test_list_resources_filtered():
    """Test listing with type filter."""
    resources = list_resources(resource_type="skill")
    assert isinstance(resources, list)
    for r in resources:
        assert r["type"] == "skill"


# ── Validate ─────────────────────────────────────────────────────────────────


def test_validate_valid_skill():
    """Test validation passes for a valid skill with matching folder name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill for pytest verification\n---\n\n# Test\n"
        )
        is_valid, errors = validate_resource(str(skill_dir))
        assert is_valid, f"Unexpected errors: {errors}"
        assert errors == []


def test_validate_valid_agent(temp_agent_file):
    """Test validation passes for a valid agent."""
    is_valid, errors = validate_resource(temp_agent_file)
    assert is_valid
    assert errors == []


def test_validate_invalid_instruction():
    """Test validation fails for instruction missing applyTo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_instr = Path(tmpdir) / "bad.instructions.md"
        bad_instr.write_text("---\ndescription: missing applyTo\n---\n\n# Bad\n")

        is_valid, errors = validate_resource(str(bad_instr))
        assert not is_valid
        assert any("applyTo" in e for e in errors)


# ── Create ───────────────────────────────────────────────────────────────────


def test_create_resource_agent(tmp_path, monkeypatch):
    """Test creating an agent resource."""
    # Temporarily override SOURCE_DIR to use tmp_path
    import agent_abilities.manager as mgr
    monkeypatch.setattr(mgr, "SOURCE_DIR", tmp_path)

    success, msg, path = create_resource("agent", "test-create-agent", "A created agent")
    assert success
    assert path is not None
    assert path.exists()
    assert path.name == "test-create-agent.agent.md"

    # Verify frontmatter
    content = path.read_text()
    assert "description:" in content
    assert "A created agent" in content


def test_create_resource_skill(tmp_path, monkeypatch):
    """Test creating a skill resource."""
    import agent_abilities.manager as mgr
    monkeypatch.setattr(mgr, "SOURCE_DIR", tmp_path)

    success, msg, path = create_resource("skill", "test-create-skill", "A created skill for testing")
    assert success
    assert path is not None
    assert path.is_dir()
    assert (path / "SKILL.md").exists()

    content = (path / "SKILL.md").read_text()
    assert "name: test-create-skill" in content
    assert "A created skill for testing" in content


# ── Hook Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def temp_hook_dir():
    """Create a temporary hook directory with hooks.json + shell script."""
    with tempfile.TemporaryDirectory() as tmpdir:
        hook_dir = Path(tmpdir) / "test-hook"
        hook_dir.mkdir()
        import json
        hooks_config = {
            "version": 1,
            "hooks": {
                "sessionStart": [{"type": "command", "command": "./start.sh"}],
                "sessionEnd": [{"type": "command", "command": "./end.sh"}],
            },
        }
        (hook_dir / "hooks.json").write_text(json.dumps(hooks_config, indent=2))
        (hook_dir / "start.sh").write_text("#!/bin/bash\necho 'started'\n")
        (hook_dir / "end.sh").write_text("#!/bin/bash\necho 'ended'\n")
        (hook_dir / "README.md").write_text("# Test Hook\n\nA test hook.\n")
        yield str(hook_dir)


@pytest.fixture
def temp_collection_file():
    """Create a temporary .collection.yml file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        col_file = Path(tmpdir) / "test-tools.collection.yml"
        col_file.write_text(
            "id: test-tools\n"
            "name: 'Test Tools'\n"
            "description: 'A test collection'\n"
            "tags:\n"
            "  - testing\n"
            "  - tools\n"
            "items:\n"
            "  - type: agent\n"
            "    path: agents/my-agent.agent.md\n"
        )
        yield str(col_file)


# ── Hook Tests ────────────────────────────────────────────────────────────


def test_parse_hooks_json(temp_hook_dir):
    """Test parsing a hooks.json file."""
    result = parse_hooks_json(Path(temp_hook_dir) / "hooks.json")

    assert result is not None
    assert result["version"] == 1
    assert "sessionStart" in result["events"]
    assert "sessionEnd" in result["events"]
    assert "description" in result


def test_parse_hooks_json_missing():
    """Test parsing nonexistent hooks.json returns None."""
    result = parse_hooks_json(Path("/nonexistent/hooks.json"))
    assert result is None


def test_detect_hook_type(temp_hook_dir):
    """Test detect_resource_type identifies hook directories."""
    result = detect_resource_type(temp_hook_dir)
    assert result == "hook"


def test_parse_resource_hook(temp_hook_dir):
    """Test parsing a hook resource."""
    result = parse_resource(Path(temp_hook_dir), "hook")

    assert result is not None
    assert result["type"] == "hook"
    assert "events" in result


def test_scan_finds_hooks():
    """Test scanning finds hook directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        import json
        hook_dir = Path(tmpdir) / "my-hook"
        hook_dir.mkdir()
        hooks_config = {
            "version": 1,
            "hooks": {"sessionEnd": [{"type": "command", "command": "./run.sh"}]},
        }
        (hook_dir / "hooks.json").write_text(json.dumps(hooks_config))

        found = scan_for_resources(tmpdir)
        types_found = {r["type"] for r in found}
        assert "hook" in types_found


def test_create_hook(tmp_path, monkeypatch):
    """Test creating a hook resource from template."""
    import agent_abilities.manager as mgr
    monkeypatch.setattr(mgr, "SOURCE_DIR", tmp_path)

    success, msg, path = create_resource(
        "hook", "test-hook", "Auto-commit on session end",
        events=["sessionEnd"],
    )
    assert success
    assert path is not None
    assert path.is_dir()
    assert (path / "hooks.json").exists()

    import json
    config = json.loads((path / "hooks.json").read_text())
    assert "sessionEnd" in config["hooks"]


def test_generate_hook_template():
    """Test generate_hook returns correct structure."""
    files = generate_hook("my-hook", "A test hook", events=["sessionStart", "sessionEnd"])

    assert "hooks.json" in files
    assert "my-hook.sh" in files
    assert "README.md" in files

    import json
    config = json.loads(files["hooks.json"])
    assert config["version"] == 1
    assert "sessionStart" in config["hooks"]
    assert "sessionEnd" in config["hooks"]


# ── Collection Tests ──────────────────────────────────────────────────────


def test_parse_collection_yaml(temp_collection_file):
    """Test parsing a .collection.yml file."""
    result = parse_collection_yaml(Path(temp_collection_file))

    assert result is not None
    assert result["id"] == "test-tools"
    assert result["name"] == "Test Tools"
    assert result["description"] == "A test collection"
    assert "testing" in result["tags"]
    assert len(result["items"]) == 1


def test_parse_collection_yaml_missing():
    """Test parsing nonexistent collection file returns None."""
    result = parse_collection_yaml(Path("/nonexistent/file.collection.yml"))
    assert result is None


def test_detect_collection_type(temp_collection_file):
    """Test detect_resource_type identifies collection files."""
    result = detect_resource_type(temp_collection_file)
    assert result == "collection"


def test_parse_resource_collection(temp_collection_file):
    """Test parsing a collection resource."""
    result = parse_resource(Path(temp_collection_file), "collection")

    assert result is not None
    assert result["type"] == "collection"
    assert result["name"] == "Test Tools"


def test_scan_finds_collections():
    """Test scanning finds .collection.yml files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        col_file = Path(tmpdir) / "my-col.collection.yml"
        col_file.write_text(
            "id: my-col\nname: 'My Collection'\ndescription: 'Test'\ntags: []\nitems: []\n"
        )

        found = scan_for_resources(tmpdir)
        types_found = {r["type"] for r in found}
        assert "collection" in types_found


def test_create_collection(tmp_path, monkeypatch):
    """Test creating a collection resource from template."""
    import agent_abilities.manager as mgr
    monkeypatch.setattr(mgr, "SOURCE_DIR", tmp_path)

    success, msg, path = create_resource(
        "collection", "my-tools", "A curated collection",
        tags=["dev", "tools"],
    )
    assert success
    assert path is not None
    assert path.exists()
    assert path.name == "my-tools.collection.yml"

    content = path.read_text()
    assert "id: my-tools" in content
    assert "A curated collection" in content


def test_generate_collection_template():
    """Test generate_collection returns valid YAML content."""
    content = generate_collection(
        "my-tools", "Test collection",
        tags=["a", "b"],
        items=[{"type": "agent", "path": "agents/x.agent.md"}],
    )
    assert "id: my-tools" in content
    assert "Test collection" in content
    assert "  - a" in content
    assert "  - b" in content
    assert "path: agents/x.agent.md" in content


# ── Copilot CLI Target ────────────────────────────────────────────────────


def test_copilot_in_cli_dirs():
    """Test that copilot is registered as a CLI target."""
    assert "copilot" in CLI_DIRS
    assert ".github" in str(CLI_DIRS["copilot"])
    assert "copilot" in str(CLI_DIRS["copilot"])


# ── Scan Mixed with New Types ────────────────────────────────────────────


def test_scan_all_six_types():
    """Test scanning a directory with all 6 resource types."""
    with tempfile.TemporaryDirectory() as tmpdir:
        import json
        base = Path(tmpdir)

        # Agent
        (base / "test.agent.md").write_text(
            "---\ndescription: test agent\n---\n\n# Agent\n"
        )
        # Prompt
        (base / "test.prompt.md").write_text(
            "---\ndescription: test prompt\n---\n\n# Prompt\n"
        )
        # Instruction
        (base / "test.instructions.md").write_text(
            "---\ndescription: test rules\napplyTo: '**'\n---\n\n# Rules\n"
        )
        # Skill
        skill_dir = base / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: test skill desc\n---\n\n# Skill\n"
        )
        # Hook
        hook_dir = base / "test-hook"
        hook_dir.mkdir()
        (hook_dir / "hooks.json").write_text(json.dumps({
            "version": 1,
            "hooks": {"sessionStart": [{"type": "command", "command": "./run.sh"}]},
        }))
        # Collection
        (base / "test.collection.yml").write_text(
            "id: test\nname: 'Test'\ndescription: 'Test col'\ntags: []\nitems: []\n"
        )

        found = scan_for_resources(tmpdir)
        types_found = {r["type"] for r in found}
        assert types_found == {"agent", "prompt", "instruction", "skill", "hook", "collection"}
