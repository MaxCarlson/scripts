"""OpenCode v1 adapter that leaves Harbor's installation untouched.

The inherited Harbor implementation handles prompt templates and trajectories.
"""

from __future__ import annotations

import json
import os
import re

try:
    from harbor.agents.installed.opencode import OpenCode
except ImportError:
    OpenCode = object  # type: ignore[misc,assignment]


class OpenCodeV1(OpenCode):
    """Keep upstream behavior while removing its forced fake VCS setting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._version = "1.19.5"

    async def exec_as_agent(self, *args, **kwargs):
        env = kwargs.get("env")
        if env is not None:
            command = kwargs.get("command")
            if command is None and args:
                command = args[0]
            kwargs["env"] = scoped_opencode_environment(
                env, command=command, token=os.environ.get("BENCHMARK_CORRELATION_TOKEN")
            )
        return await super().exec_as_agent(*args, **kwargs)


def scoped_opencode_environment(env, *, command, token):
    """Copy the host-scoped credential only into the final OpenCode process env."""
    scoped_env = {key: value for key, value in env.items() if key != "OPENCODE_FAKE_VCS"}
    is_opencode = (
        isinstance(command, (list, tuple))
        and any(
            isinstance(part, str) and re.search(r"(?:^|[\\/])opencode(?:\.exe)?$", part, re.IGNORECASE)
            for part in command
        )
    ) or (
        isinstance(command, str)
        and re.search(r"(?:^|\s|[\\/])opencode(?:\.exe)?(?:\s|$)", command, re.IGNORECASE) is not None
    )
    if token is None or not is_opencode:
        return scoped_env
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", token):
        raise ValueError("invalid scoped benchmark correlation credential")
    content = scoped_env.get("OPENCODE_CONFIG_CONTENT", "{}")
    try:
        config = json.loads(content)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("existing OPENCODE_CONFIG_CONTENT is invalid JSON") from error
    if not isinstance(config, dict):
        raise ValueError("existing OPENCODE_CONFIG_CONTENT must be a JSON object")
    provider = config.setdefault("provider", {}).setdefault("openai", {})
    options = provider.setdefault("options", {})
    headers = options.setdefault("headers", {})
    if not isinstance(headers, dict):
        raise ValueError("OpenCode provider headers must be a JSON object")
    headers["x-benchmark-correlation-token"] = token
    scoped_env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config, separators=(",", ":"))
    return scoped_env
