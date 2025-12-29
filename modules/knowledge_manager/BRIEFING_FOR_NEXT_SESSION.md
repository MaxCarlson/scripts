# Briefing for New Claude Code Session

**Date**: 2025-12-29
**Location**: WSL Ubuntu, `~/scripts/` and `~/projects/ai-orchestrator/`
**Status**: PostgreSQL migration COMPLETE ✅ - Ready for orchestrator development

---

## Current Situation

**PostgreSQL Migration: COMPLETE** 🎉
- All data migrated: 25 projects, 236 tasks, 76 task links
- kmtui verified working with PostgreSQL in Docker
- Both repos (scripts, ai-orchestrator) committed and pushed

**What's Working**:
- PostgreSQL 16 running in Docker (container: km-postgres)
- kmtui displaying all projects/tasks from PostgreSQL
- LISTEN/NOTIFY triggers configured for real-time updates
- Shared Docker volume (docker_postgres_data) between repos

---

## Repository Structure

### ~/scripts/ (knowledge_manager module)
- Python TUI and CLI tools
- PostgreSQL adapter (db_postgres.py)
- Shell function: `kmtui` (configured for PostgreSQL)
- Docker setup for local development/testing

### ~/projects/ai-orchestrator/ (NEW)
- Multi-agent orchestrator system
- Shares PostgreSQL database with scripts repo
- FastAPI orchestrator service (TODO: implement)
- CLI integrations (TODO: implement)
- LLM router for RTX 5090 (TODO: implement)

---

## What's Been Completed ✅

### Phase 1-5: PostgreSQL Migration (COMPLETE)
1. ✅ Database schema analysis and documentation
2. ✅ Docker Compose setup with PostgreSQL 16
3. ✅ pgloader migration (SQLite → PostgreSQL)
4. ✅ Python adapter updates (PostgreSQL-only, removed SQLite)
5. ✅ Testing and verification (CRUD operations working)
6. ✅ Shell function fixes (kmtui using correct Python venv)
7. ✅ Docker volume configuration (shared data between repos)

### Key Fixes Applied
- **SQL placeholders**: All 58 instances of `?` replaced with `%s`
- **Type conversions**: Added _to_uuid(), _to_datetime(), _to_date() helpers
- **kmtui shell function**: Uses ~/scripts/.venv/bin/python with PostgreSQL env vars
- **Docker volume**: External volume (docker_postgres_data) shared between repos
- **PGDATA**: Configured to match existing data directory structure

---

## What's Next ⏳

### Immediate Tasks (Orchestrator Development)

**Priority 1: Task Queue System**
- [ ] Design filesystem-based task queue structure
- [ ] Implement task submission from kmtui
- [ ] Create task status tracking (queued, in-progress, completed)
- [ ] Add task assignment to AI CLIs

**Priority 2: CLI Integrations**
- [ ] Create wrapper scripts for Claude Code CLI
- [ ] Create wrapper scripts for OpenAI Codex CLI
- [ ] Create wrapper scripts for Gemini CLI
- [ ] Implement task result capture and storage

**Priority 3: Orchestrator Service**
- [ ] Implement FastAPI endpoints in docker/orchestrator/main.py
- [ ] Add LISTEN/NOTIFY subscription (already scaffolded)
- [ ] Create task polling and assignment logic
- [ ] Add health checks and monitoring

**Priority 4: LLM Router (RTX 5090)**
- [ ] Design LLM routing strategy
- [ ] Integrate with llama.cpp server
- [ ] Implement model hot-swapping
- [ ] Add queue management for local models

---

## Quick Reference

### Start PostgreSQL
```bash
cd ~/projects/ai-orchestrator
docker compose up -d postgres
docker compose logs -f postgres  # Monitor logs
```

### Test kmtui
```bash
kmtui  # Should show all 25 projects from PostgreSQL
```

### Direct PostgreSQL Access
```bash
docker compose exec postgres psql -U km_user -d knowledge_manager
```

### Check Container Status
```bash
docker ps  # Should see km-postgres running
docker volume ls | grep postgres  # Should see docker_postgres_data
```

---

## Key Files to Reference

| File | Purpose |
|------|---------|
| `POSTGRESQL_MIGRATION_STATUS.md` | Complete migration documentation |
| `~/projects/ai-orchestrator/docker-compose.yml` | Multi-service orchestration config |
| `~/projects/ai-orchestrator/docker/orchestrator/main.py` | Orchestrator service (needs implementation) |
| `~/scripts/modules/knowledge_manager/db.py` | PostgreSQL CRUD operations |
| `~/dotfiles/zsh_configs/knowledge_manager.zsh` | kmtui shell function |

---

## Environment Configuration

### PostgreSQL Connection (Both Repos)
```bash
KM_DB_TYPE=postgresql
KM_POSTGRES_HOST=localhost
KM_POSTGRES_PORT=5432
KM_POSTGRES_DB=knowledge_manager
KM_POSTGRES_USER=km_user
KM_POSTGRES_PASSWORD=<from .env file>
```

### Docker Services
- **postgres**: localhost:5432 (PostgreSQL 16)
- **orchestrator**: localhost:8000 (FastAPI - TODO)
- **pgadmin**: localhost:5050 (optional, profile: admin)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Multi-Agent System                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────┐  │
│  │   kmtui      │      │  ai_orch     │      │   CLIs   │  │
│  │  (Textual)   │──────│  (FastAPI)   │──────│ claude   │  │
│  │              │      │              │      │ codex    │  │
│  └──────────────┘      └──────────────┘      │ gemini   │  │
│         │                     │               └──────────┘  │
│         │                     │                     │        │
│         └─────────────────────┴─────────────────────┘        │
│                              │                               │
│                    ┌─────────▼─────────┐                     │
│                    │   PostgreSQL 16   │                     │
│                    │  (Docker Volume)  │                     │
│                    │  LISTEN/NOTIFY    │                     │
│                    └───────────────────┘                     │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              LLM Router (RTX 5090)                    │  │
│  │  llama.cpp server → Qwen models (hot-swappable)      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Session Handoff Protocol

When you complete work:

1. ✅ Test changes thoroughly (kmtui, psql queries, etc.)
2. ✅ Update relevant documentation files
3. ✅ Commit changes with descriptive messages
4. ✅ Push to GitHub (both repos if needed)
5. ✅ Update this briefing for next session

---

## Questions/Issues?

1. **PostgreSQL issues**: Check `POSTGRESQL_MIGRATION_STATUS.md` → "Resolved Issues"
2. **Docker issues**: `docker compose logs <service-name>`
3. **kmtui not working**: Check `~/dotfiles/zsh_configs/knowledge_manager.zsh`
4. **Connection refused**: Verify PostgreSQL container is running

---

## Long-Term Goals

**Phase 6-8: Orchestrator Development**
- Build task queue system (filesystem or PostgreSQL-based)
- Integrate AI CLIs (claude, codex, gemini)
- Implement LLM router for local RTX 5090 models
- Add real-time updates via LISTEN/NOTIFY subscriptions
- Create monitoring and health check dashboard

**Future Enhancements**:
- Vector database for semantic search
- Multi-device synchronization
- Agent performance tracking
- Cost optimization for API calls
- Fallback strategies for model unavailability

---

## Quick Start for Next Session

```bash
# Verify PostgreSQL is running
cd ~/projects/ai-orchestrator
docker compose ps

# If not running, start it
docker compose up -d postgres

# Test kmtui
kmtui

# Start orchestrator development
cd ~/projects/ai-orchestrator/docker/orchestrator
# Edit main.py to implement task polling and assignment
```

**Ready to build the orchestrator!** 🚀

---

**End of Briefing**
