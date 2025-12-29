# Briefing for New Claude Code Session

**Date**: 2025-12-28
**Location**: WSL Ubuntu, `~/src/scripts/modules/knowledge_manager/`
**Task**: PostgreSQL migration and agent orchestrator setup

---

## Current Situation

We're building a **multi-agent orchestrator** that uses:
- **knowledge_manager** (existing TUI for projects/tasks) + SQLite DB
- **ai_orchestrator** (new module for CLI/model management)
- **PostgreSQL** (migration target for cross-device access + real-time updates)
- **Local LLMs** (RTX 5090 with Qwen models via llama.cpp)

---

## What's Been Done ✅

1. **Docker Setup Complete**:
   - `docker/docker-compose.yml` - PostgreSQL 16 container
   - `docker/init-scripts/01_init_schema.sql` - Full schema with LISTEN/NOTIFY
   - `docker/migrate.load` - pgloader script for SQLite → PostgreSQL
   - `docker/README.md` - Complete setup guide
   - `docker/.env.example` - Configuration template

2. **Documentation**:
   - `POSTGRESQL_MIGRATION_STATUS.md` - Detailed progress tracking
   - Research specs in `research-output/Claude-V4-multi-agent-orchestration.md`

3. **Commits**:
   - Committed all Docker infrastructure (Git Bash)
   - Ready to pull in WSL

---

## What You Need to Do ⏳

### Immediate Tasks (Phase 3 - pgloader Migration)

1. **Pull latest code**:
   ```bash
   cd ~/src/scripts
   git pull
   cd modules/knowledge_manager/docker
   ```

2. **Create .env file**:
   ```bash
   cp .env.example .env
   nano .env  # Change POSTGRES_PASSWORD!
   ```

3. **Start PostgreSQL container**:
   ```bash
   docker compose up -d
   docker compose logs -f postgres  # Verify it started
   ```

4. **Install pgloader**:
   ```bash
   sudo apt-get update
   sudo apt-get install -y pgloader postgresql-client
   ```

5. **Run migration**:
   ```bash
   # Edit migrate.load to verify source DB path (should be /mnt/c/Users/mcarls/...)
   pgloader migrate.load
   ```

6. **Verify migration**:
   ```bash
   docker compose exec postgres psql -U km_user -d knowledge_manager -c "
     SELECT 'projects' as table, COUNT(*) FROM projects
     UNION ALL SELECT 'tasks', COUNT(*) FROM tasks
     UNION ALL SELECT 'task_links', COUNT(*) FROM task_links;"
   ```

7. **Update status**:
   ```bash
   # Mark Phase 3 complete in POSTGRESQL_MIGRATION_STATUS.md
   ```

### After Migration (Phase 4 - DB Adapter Updates)

See `POSTGRESQL_MIGRATION_STATUS.md` Phase 4 for:
- Adding asyncpg support to `knowledge_manager/db.py`
- Creating dual SQLite/PostgreSQL support
- Environment variable configuration

---

## Key Files to Reference

| File | Purpose |
|------|---------|
| `POSTGRESQL_MIGRATION_STATUS.md` | **Main progress tracker** - read this first! |
| `docker/README.md` | Setup instructions, troubleshooting |
| `docker/migrate.load` | Migration script (edit if needed) |
| `research-output/Claude-V4-multi-agent-orchestration.md` | Full architecture spec (800 lines) |
| `TODOS.md` | Feature roadmap for knowledge_manager |
| `IMPLEMENTATION_STATUS.md` | Current TUI feature status |

---

## Important Context

### Database Schema (8 tables):
- `projects` - Top-level organization
- `tasks` - Hierarchical tasks (can have parent_task_id)
- `task_links` - **Cross-project bidirectional linking** (new feature!)
- `tags`, `project_tags`, `task_tags` - Tagging system
- `notes` - Attached to projects/tasks
- `attachments` - File metadata

### Key Features to Preserve:
- ✅ Cross-project task linking with `@project-name` syntax
- ✅ Hierarchical task structure (parent/subtasks)
- ✅ Foreign key CASCADE relationships
- ✅ ISO8601 timestamps and UUID primary keys

### Available Tools:
- **Claude Code** CLI (`claude` command) - installed
- **OpenAI Codex** CLI (`codex` command) - installed
- **Gemini CLI** (`gemini` command) - installed
- **LM Studio** running Qwen models on RTX 5090

---

## Questions/Issues?

1. **Check status doc first**: `POSTGRESQL_MIGRATION_STATUS.md` → "Known Issues & Blockers"
2. **Docker issues**: See `docker/README.md` → "Troubleshooting"
3. **Migration fails**: Check pgloader logs at `~/.local/share/pgloader/pgloader.log`

---

## Session Handoff Protocol

When you complete work:

1. ✅ Update checkboxes in `POSTGRESQL_MIGRATION_STATUS.md`
2. ✅ Update "Last Updated" timestamp and "Last Editor" at top
3. ✅ Move phase status from 🚧 → ✅ when complete
4. ✅ Commit changes with descriptive message
5. ✅ Update this briefing if needed for next session

---

## Long-Term Goal

Build a **minimal viable agent orchestrator** that:
- Assigns tasks from knowledge_manager to AI CLIs
- Uses PostgreSQL for cross-device access
- Tracks agent work in real-time (LISTEN/NOTIFY)
- Manages local LLMs on RTX 5090 (orchestrator + hot-swapped workers)

**Next major phases after PostgreSQL**:
- Phase 4: Update Python code for PostgreSQL support
- Phase 5: Test TUI with PostgreSQL backend
- Phase 6: Build task queue system
- Phase 7: CLI tool integration layer
- Phase 8: Local LLM routing with llama.cpp

---

## Quick Start Command

```bash
cd ~/src/scripts/modules/knowledge_manager
git pull
cat POSTGRESQL_MIGRATION_STATUS.md  # Read the full status
cd docker
cp .env.example .env && nano .env
docker compose up -d
```

**Good luck!** 🚀

---

**End of Briefing**
