"""Tests for CLI Manager."""

import pytest
from ai_orchestrator.cli_manager import CLIManager, JobType


def test_cli_manager_init():
    """Test CLIManager initialization."""
    manager = CLIManager()
    assert manager is not None
    assert len(manager.tools) > 0


def test_get_best_tool_for_file_operations():
    """Test getting best tool for file operations."""
    manager = CLIManager()
    tool = manager.get_best_tool(JobType.FILE_OPERATIONS)

    # Should return something if any file operation tools are installed
    # (or None if nothing is installed)
    assert tool is None or tool.command in ["rg", "fd", "bat", "grep", "find"]


def test_get_all_tools_for_code_generation():
    """Test getting all tools for code generation."""
    manager = CLIManager()
    tools = manager.get_all_tools_for_job(JobType.CODE_GENERATION, installed_only=False)

    assert isinstance(tools, list)
    # Should have at least claude-code and codex registered
    tool_names = [t.name for t in tools]
    assert "claude-code" in tool_names


def test_list_all_tools():
    """Test listing all tools."""
    manager = CLIManager()
    tools = manager.list_all_tools(installed_only=False)

    assert isinstance(tools, list)
    assert len(tools) > 0


def test_get_tool_status():
    """Test getting tool status."""
    manager = CLIManager()
    status = manager.get_tool_status()

    assert isinstance(status, dict)
    assert "ripgrep" in status or "claude-code" in status
