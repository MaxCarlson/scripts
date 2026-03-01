# Web UI Tools - Design Document

**Date**: 2026-02-20
**Status**: Approved

## Problem

1. `orchestrator_web_viewer` exists in two locations with diverging code
   - `~/scripts/modules/orchestrator_web_viewer/` (stale fork, missing files)
   - `~/projects/ai-orchestrator/orchestrator_web_viewer/` (active superset)
2. The module is tightly coupled to ai-orchestrator but was meant to be general
3. `koweb -s` can't detect Docker-based servers (only scans host processes)
4. The web UI needs a better interactive dashboard aesthetic (Grafana-style)

## Solution

Create `web_ui_tools` as a reusable FastAPI web dashboard framework with a
plugin architecture. The ai-orchestrator becomes the first plugin.

## Architecture

### Module Structure

```
scripts/modules/web_ui_tools/
├── web_ui_tools/
│   ├── __init__.py              # __version__, public API
│   ├── app.py                   # FastAPI app factory + plugin loading
│   ├── cli.py                   # webui CLI (argparse, -a/--arg format)
│   ├── config.py                # Config class (env vars, CLI overrides)
│   ├── auth.py                  # HTTP Basic Auth
│   ├── websocket/
│   │   ├── __init__.py
│   │   └── manager.py           # WebSocket connection manager
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── protocol.py          # WebUIPlugin Protocol class
│   │   └── loader.py            # Entry point scanner (importlib.metadata)
│   ├── termdash/
│   │   ├── __init__.py
│   │   ├── router.py            # /api/termdash/* endpoints
│   │   └── viewer.py            # termdash.html page serving
│   ├── builtins/
│   │   ├── __init__.py
│   │   ├── health.py            # /health, /api/system/*
│   │   └── logs.py              # /api/logs/*
│   └── static/
│       ├── index.html           # Dashboard shell (Grafana-style)
│       ├── app.js               # Core framework JS
│       └── style.css            # Dark theme
├── skills/
│   └── web-ui-dev/              # Visual iteration skill (CREATED)
│       ├── SKILL.md
│       └── references/
│           ├── design-system.md
│           └── visual-qa-checklist.md
├── pyproject.toml
├── tests/
└── README.md
```

### Plugin Protocol

```python
class WebUIPlugin(Protocol):
    name: str
    version: str

    def register(self, app: FastAPI) -> None:
        """Register routers, mount static dirs, add hooks."""
        ...

    def get_nav_items(self) -> list[dict]:
        """Return sidebar navigation items."""
        ...
```

### Plugin Discovery

Plugins declare entry points in their pyproject.toml:

```toml
[project.entry-points."webui.plugins"]
orchestrator = "orchestrator_web_viewer.plugin:OrchestratorPlugin"
```

`web_ui_tools` discovers them at startup via `importlib.metadata.entry_points`.

### CLI

```
webui                        # Start server (default port 3000)
webui -r -v                 # Dev mode (auto-reload + verbose)
webui -s                    # Stop servers (host + Docker)
webui --list-plugins        # Show discovered plugins
koweb                       # Backwards-compat alias
```

`webui -s` fix: check Docker containers in addition to host processes:
```python
docker ps --filter "name=*koweb*" --format "{{.ID}}"
```

### Frontend Design (Grafana-style)

- Background: #0f0f0f, panels: #1a1a2e
- Accent: #00d4aa (teal-green)
- Font: Inter (UI), JetBrains Mono (data)
- CSS Grid layout with metric cards, tables, live feeds
- Sidebar navigation with plugin tabs
- All real-time updates via WebSocket (no polling)
- Full design system in `skills/web-ui-dev/references/design-system.md`

## Migration Plan

### Phase 1: Framework + First Plugin
1. Create `web_ui_tools` module with framework skeleton
2. Implement plugin protocol + entry-point discovery
3. Extract auth, WebSocket, config, termdash into framework
4. Move orchestrator-specific routers to plugin class in ai-orchestrator
5. Update ai-orchestrator pyproject.toml with entry point
6. Fix `webui -s` to detect Docker containers
7. Delete stale `scripts/modules/orchestrator_web_viewer/`
8. Update ai-orchestrator docker-compose.yml
9. Write tests for framework + plugin loading
10. Verify SKILL.md works for visual iteration

### Phase 2: Grafana-Style UI Redesign
1. Design the dashboard shell (sidebar, grid, metric cards)
2. Build reusable frontend components
3. Create plugin panel rendering system
4. Redesign orchestrator plugin panels
5. Add WebSocket-driven real-time updates
6. Visual testing via Playwright screenshots (using web-ui-dev skill)

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Module name | `web_ui_tools` | General-purpose, not orchestrator-specific |
| CLI name | `webui` (koweb as alias) | Clean break, self-documenting |
| Plugin discovery | Entry points | Zero config, just install the module |
| UI style | Grafana-like | Data-dense, dark, real-time metric panels |
| Framework | Full plugin architecture | Avoids future refactor, clean from start |

## Completed Deliverables

- [x] `web-ui-dev` skill created with design system references
- [x] `setup_skills.py` for automatic skill symlinking in setup chain
- [x] Skill registered in `~/.claude/skills/`, `~/.codex/skills/`, `~/.cursor/skills/`
