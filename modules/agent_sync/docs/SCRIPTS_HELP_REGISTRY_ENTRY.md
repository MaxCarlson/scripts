# scripts_help registry entry

Add this under the existing `"LLM & AI Tools"` section if missing:

~~~python
{
    "name": "agent-sync (module)",
    "path": "modules/agent_sync",
    "desc": "Repo-local multi-agent handoff, delegation, review, and verification across Claude, Codex, Gemini, Copilot, and local LLM workers",
    "help_cmd": ["agent-sync", "--help"],
    "version": "0.2.0",
},
~~~
