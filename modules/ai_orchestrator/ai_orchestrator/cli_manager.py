"""CLI Manager - Selects best CLI tools for specific jobs."""

import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict
from pathlib import Path


class JobType(Enum):
    """Types of jobs that CLIs can handle."""
    CODE_GENERATION = "code_generation"
    CODE_ANALYSIS = "code_analysis"
    TEXT_GENERATION = "text_generation"
    CHAT = "chat"
    RESEARCH = "research"
    FILE_OPERATIONS = "file_operations"
    SYSTEM_ADMIN = "system_admin"
    DATA_PROCESSING = "data_processing"


@dataclass
class CLITool:
    """Represents a CLI tool with its capabilities."""
    name: str
    command: str
    description: str
    job_types: List[JobType]
    priority: int = 5  # 1-10, higher is better
    requires_network: bool = False
    requires_api_key: bool = False
    installed: bool = False
    version: Optional[str] = None


class CLIManager:
    """Manages and selects the best CLI tools for specific jobs."""

    def __init__(self):
        """Initialize CLI manager with known tools."""
        self.tools: Dict[str, CLITool] = {}
        self._register_default_tools()
        self._check_installations()

    def _register_default_tools(self):
        """Register commonly used CLI tools."""
        tools = [
            # Code generation/analysis
            CLITool(
                name="claude-code",
                command="claude",
                description="Claude Code CLI for software development",
                job_types=[JobType.CODE_GENERATION, JobType.CODE_ANALYSIS, JobType.RESEARCH],
                priority=10,
                requires_network=True,
                requires_api_key=True,
            ),
            CLITool(
                name="codex",
                command="codex",
                description="Custom Codex CLI wrapper",
                job_types=[JobType.CODE_GENERATION, JobType.CODE_ANALYSIS],
                priority=8,
                requires_network=True,
                requires_api_key=True,
            ),
            CLITool(
                name="gemini",
                command="gemini",
                description="Google Gemini CLI",
                job_types=[JobType.TEXT_GENERATION, JobType.CHAT, JobType.RESEARCH],
                priority=7,
                requires_network=True,
                requires_api_key=True,
            ),

            # LM Studio (local)
            CLITool(
                name="lmstui",
                command="lmst",
                description="LM Studio CLI (local inference)",
                job_types=[JobType.CODE_GENERATION, JobType.TEXT_GENERATION, JobType.CHAT],
                priority=6,
                requires_network=False,
                requires_api_key=False,
            ),

            # File operations
            CLITool(
                name="ripgrep",
                command="rg",
                description="Fast text search tool",
                job_types=[JobType.FILE_OPERATIONS, JobType.CODE_ANALYSIS],
                priority=10,
                requires_network=False,
            ),
            CLITool(
                name="fd",
                command="fd",
                description="Fast file finder",
                job_types=[JobType.FILE_OPERATIONS],
                priority=10,
                requires_network=False,
            ),
            CLITool(
                name="bat",
                command="bat",
                description="Better cat with syntax highlighting",
                job_types=[JobType.FILE_OPERATIONS],
                priority=7,
                requires_network=False,
            ),

            # Data processing
            CLITool(
                name="jq",
                command="jq",
                description="JSON processor",
                job_types=[JobType.DATA_PROCESSING],
                priority=9,
                requires_network=False,
            ),
        ]

        for tool in tools:
            self.tools[tool.name] = tool

    def _check_installations(self):
        """Check which tools are actually installed."""
        for tool in self.tools.values():
            # Check if command exists in PATH
            tool.installed = shutil.which(tool.command) is not None

            # Try to get version if installed
            if tool.installed:
                # For now, just mark as installed
                # Could run `tool.command --version` to get version
                pass

    def get_best_tool(self, job_type: JobType, require_local: bool = False) -> Optional[CLITool]:
        """
        Get the best available tool for a specific job type.

        Args:
            job_type: Type of job to perform
            require_local: Only return tools that don't require network

        Returns:
            Best available tool or None
        """
        candidates = [
            tool for tool in self.tools.values()
            if job_type in tool.job_types
            and tool.installed
            and (not require_local or not tool.requires_network)
        ]

        if not candidates:
            return None

        # Sort by priority (descending)
        candidates.sort(key=lambda t: t.priority, reverse=True)
        return candidates[0]

    def get_all_tools_for_job(self, job_type: JobType, installed_only: bool = True) -> List[CLITool]:
        """
        Get all tools that can handle a specific job type.

        Args:
            job_type: Type of job to perform
            installed_only: Only return installed tools

        Returns:
            List of tools sorted by priority
        """
        candidates = [
            tool for tool in self.tools.values()
            if job_type in tool.job_types
            and (not installed_only or tool.installed)
        ]

        candidates.sort(key=lambda t: t.priority, reverse=True)
        return candidates

    def register_tool(self, tool: CLITool):
        """
        Register a new CLI tool.

        Args:
            tool: CLITool to register
        """
        self.tools[tool.name] = tool
        tool.installed = shutil.which(tool.command) is not None

    def list_all_tools(self, installed_only: bool = False) -> List[CLITool]:
        """
        List all registered tools.

        Args:
            installed_only: Only return installed tools

        Returns:
            List of all tools
        """
        tools = list(self.tools.values())
        if installed_only:
            tools = [t for t in tools if t.installed]
        return tools

    def get_tool_status(self) -> Dict[str, Dict]:
        """
        Get status of all tools.

        Returns:
            Dictionary mapping tool name to status info
        """
        return {
            name: {
                "command": tool.command,
                "installed": tool.installed,
                "version": tool.version,
                "priority": tool.priority,
                "requires_network": tool.requires_network,
                "requires_api_key": tool.requires_api_key,
                "job_types": [jt.value for jt in tool.job_types],
            }
            for name, tool in self.tools.items()
        }
