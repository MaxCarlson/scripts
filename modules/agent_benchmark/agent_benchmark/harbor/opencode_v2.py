"""OpenCode v2 candidate agent adapter for Harbor benchmark infrastructure.

This module provides an isolated, version-pinned OpenCode v2 candidate (@opencode/cli@2.2.5)
adapter compatible with Harbor 0.25.0's dynamic agent import path mechanism.

Key migration differences from legacy OpenCode v1 (opencode-ai):
1. Package Identity: Installs '@opencode/cli@2.2.5' via npm, replacing deprecated 'opencode-ai'.
2. Automated Permissions: Uses '--auto' flag for headless CI automation, replacing removed '--dangerously-skip-permissions'.
3. Daemon Isolation: Uses '--standalone' to spawn an isolated private server instance inside the container.
4. Output Contract: Uses '--format json' to stream newline-delimited JSON events.
5. VCS Safety: Omits unsolicited OPENCODE_FAKE_VCS='git' injection in non-git benchmark directories.
"""

from __future__ import annotations

import os
import shlex

PINNED_OPENCODE_V2_VERSION = "2.2.5"
OPENCODE_V2_PACKAGE = f"@opencode/cli@{PINNED_OPENCODE_V2_VERSION}"
DEFAULT_OUTPUT_FILENAME = "opencode.txt"


def build_opencode_v2_run_command(
    *,
    model_name: str,
    instruction: str,
    output_filename: str = DEFAULT_OUTPUT_FILENAME,
    resume: bool = False,
    cli_flags: str = "",
    thinking: bool = True,
    auto: bool = True,
    standalone: bool = True,
) -> str:
    """Build the exact container shell command string for OpenCode v2 execution.

    Flags used:
    - --standalone: global flag for running private isolated server without background service daemon
    - run: subcommand to execute a session
    - --model: provider/model identifier (flag of `run`)
    - --format json: structured JSON Lines event stream (flag of `run`)
    - --thinking: include reasoning blocks in output (flag of `run`)
    - --auto: auto-approve permissions in headless execution (flag of `run`)
    """
    escaped_instruction = shlex.quote(instruction)
    escaped_output = shlex.quote(output_filename)
    escaped_model = shlex.quote(model_name)

    global_flags: list[str] = []
    if standalone:
        global_flags.append("--standalone")

    run_flags: list[str] = [
        "run",
        f"--model={escaped_model}",
        "--format json",
    ]
    if resume:
        run_flags.append("--continue")
    if cli_flags:
        run_flags.append(cli_flags.strip())
    if thinking:
        run_flags.append("--thinking")
    if auto:
        run_flags.append("--auto")

    cmd_parts = ["opencode", *global_flags, *run_flags, "--", escaped_instruction]
    command_str = " ".join(cmd_parts)
    return (
        "[ -f ~/.nvm/nvm.sh ] && . ~/.nvm/nvm.sh; "
        f"{command_str} "
        f"2>&1 </dev/null | stdbuf -oL tee {escaped_output}"
    )


def build_opencode_v2_install_command(
    version: str = PINNED_OPENCODE_V2_VERSION,
) -> str:
    """Build the container installation command for OpenCode v2."""
    package_spec = f"@opencode/cli@{version}"
    return (
        "set -euo pipefail; "
        "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then "
        "node --version && npm --version; "
        "else [ -f ~/.nvm/nvm.sh ] && . ~/.nvm/nvm.sh; fi && "
        f"(npm i -g --fetch-retries=5 --fetch-retry-mintimeout=2000 --fetch-retry-maxtimeout=30000 {package_spec} || "
        f"(sleep 3 && npm i -g --fetch-retries=5 {package_spec})) && "
        "opencode --version"
    )


def is_harbor_available() -> bool:
    """Return whether Harbor 0.25.0 base classes are available in the current environment."""
    return _HARBOR_AVAILABLE


# Attempt import of Harbor base classes when running inside Harbor's Python environment
try:
    from harbor.agents.installed.base import (
        BaseEnvironment,
        NonZeroAgentExitCodeError,
        with_prompt_template,
    )
    from harbor.agents.installed.node_install import nvm_node_install_snippet
    from harbor.agents.installed.opencode import OpenCode
    from harbor.models.agent.context import AgentContext
    _HARBOR_AVAILABLE = True
except ImportError:
    _HARBOR_AVAILABLE = False
    OpenCode = object  # type: ignore[misc,assignment]


if _HARBOR_AVAILABLE:

    class OpenCodeV2(OpenCode):
        """OpenCode v2 candidate adapter for Harbor evaluation jobs."""

        @staticmethod
        def name() -> str:
            return "opencode-v2"

        def version(self) -> str | None:
            return PINNED_OPENCODE_V2_VERSION

        async def install(self, environment: BaseEnvironment) -> None:
            """Install pinned @opencode/cli package into the container."""
            await self.ensure_system_dependencies(
                environment, ("curl", "bash", "coreutils", "nodejs", "npm")
            )
            await self.exec_as_agent(
                environment,
                command=(
                    "set -euo pipefail; "
                    "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then "
                    "node --version && npm --version; "
                    f"else {nvm_node_install_snippet()}; fi && "
                    f"(npm i -g --fetch-retries=5 --fetch-retry-mintimeout=2000 --fetch-retry-maxtimeout=30000 {OPENCODE_V2_PACKAGE} || "
                    f"(sleep 3 && npm i -g --fetch-retries=5 {OPENCODE_V2_PACKAGE})) && "
                    "opencode --version"
                ),
            )

        @with_prompt_template
        async def run(
            self,
            instruction: str,
            environment: BaseEnvironment,
            context: AgentContext,
        ) -> None:
            """Execute OpenCode v2 with v2 CLI options and headless isolation."""
            self._instruction = instruction

            if not self.model_name:
                raise ValueError("Model name must be in the format provider/model_name")

            env = dict(self.model_connection.env)
            # Only pass OPENCODE_FAKE_VCS if explicitly set in environment
            if os.environ.get("OPENCODE_FAKE_VCS"):
                env["OPENCODE_FAKE_VCS"] = os.environ["OPENCODE_FAKE_VCS"]

            env["XDG_DATA_HOME"] = (
                self.environment_logs_dir / "opencode" / "xdg-data"
            ).as_posix()
            env["XDG_STATE_HOME"] = (
                self.environment_logs_dir / "opencode" / "xdg-state"
            ).as_posix()

            skills_command = self._build_register_skills_command()
            if skills_command:
                await self.exec_as_agent(environment, command=skills_command, env=env)

            mcp_command = self._build_register_config_command()
            if mcp_command:
                await self.exec_as_agent(environment, command=mcp_command, env=env)

            cli_flags = self.build_cli_flags()
            output_posix = (self.environment_logs_dir / self._OUTPUT_FILENAME).as_posix()

            run_cmd = build_opencode_v2_run_command(
                model_name=self._execution_model_name(),
                instruction=instruction,
                output_filename=output_posix,
                resume=self._resume,
                cli_flags=cli_flags,
                thinking=True,
                auto=True,
                standalone=True,
            )

            await self.exec_as_agent(
                environment,
                command=run_cmd,
                env=env,
            )

            if messages := self._error_messages():
                raise NonZeroAgentExitCodeError(
                    "OpenCode v2 emitted error event(s): " + "; ".join(messages[:3])
                )
else:
    # Standalone stub for testing and inspection when Harbor is not installed in the active venv
    class OpenCodeV2:  # type: ignore[no-redef]
        """OpenCode v2 stub when harbor is not installed in the current Python interpreter."""

        @staticmethod
        def name() -> str:
            return "opencode-v2"

        def version(self) -> str | None:
            return PINNED_OPENCODE_V2_VERSION
