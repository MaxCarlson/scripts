"""OpenCode v1 adapter that leaves Harbor's installation untouched.

The inherited Harbor implementation handles prompt templates and trajectories.
"""

from __future__ import annotations

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
            kwargs["env"] = {key: value for key, value in env.items() if key != "OPENCODE_FAKE_VCS"}
        return await super().exec_as_agent(*args, **kwargs)
