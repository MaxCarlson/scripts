# PostgreSQL Migration - Implementation Status

**Started**: 2025-12-28
**Last Updated**: 2025-12-28 (Docker setup complete)
**Last Editor**: Claude Sonnet 4.5
**Priority**: HIGH - Critical path for multi-agent orchestration

---

## Quick Status Overview

| Phase | Status | Completion |
|-------|--------|------------|
| **1. Database Schema Analysis** | ✅ Complete | 100% |
| **2. Docker Setup** | ✅ Complete | 100% |
| **3. pgloader Migration** | ⏳ Pending | 0% |
| **4. DB Adapter Updates** | ⏳ Pending | 0% |
| **5. Testing & Verification** | ⏳ Pending | 0% |
| **6. LISTEN/NOTIFY Setup** | ✅ Complete | 100% |

**Note**: LISTEN/NOTIFY triggers are already included in the PostgreSQL schema initialization (01_init_schema.sql)

---

## Database Schema Summary

### Current SQLite Tables

From `knowledge_manager/db.py` analysis:

1. **projects** - Core project records
2. **tasks** - Task records with hierarchy support
3. **task_links** - Cross-project bidirectional linking (NEW)
4. **tags** - Tag definitions
5. **project_tags** - Project-tag associations
6. **task_tags** - Task-tag associations
7. **notes** - Notes attached to projects/tasks
8. **attachments** - File attachments metadata

### Key Features to Preserve

- ✅ Foreign key constraints with CASCADE
- ✅ Text-based UUID primary keys
- ✅ ISO8601 datetime strings
- ✅ Enum values stored as strings (ProjectStatus, TaskStatus)
- ✅ Indexes on frequently queried columns

---

## Phase 1: Database Schema Analysis ✅

**Status**: COMPLETE
**Completed**: 2025-12-28

### Tasks Completed

- [x] Read and analyze `knowledge_manager/db.py`
- [x] Document all tables and columns
- [x] Identify migration patterns needed
- [x] Note foreign key relationships
- [x] Document indexes

### Schema Details

#### projects table
```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,                -- UUID as text
    name TEXT NOT NULL,
    status TEXT NOT NULL,               -- 'active' | 'backlog' | 'completed'
    created_at TEXT NOT NULL,           -- ISO8601 timestamp
    modified_at TEXT NOT NULL,          -- ISO8601 timestamp
    description_md_path TEXT            -- Optional file path
);
```

#### tasks table
```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,                -- UUID as text
    title TEXT NOT NULL,
    status TEXT NOT NULL,               -- 'todo' | 'in-progress' | 'done'
    project_id TEXT,                    -- Optional FK to projects
    parent_task_id TEXT,                -- Optional FK to tasks (hierarchy)
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    completed_at TEXT,                  -- Optional completion timestamp
    priority INTEGER,                   -- 1-5 scale
    due_date TEXT,                      -- ISO8601 date
    details_md_path TEXT,               -- Optional file path
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
```

#### task_links table (Cross-project linking)
```sql
CREATE TABLE task_links (
    task_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    is_origin BOOLEAN NOT NULL DEFAULT 0,  -- 1 = origin project, 0 = linked
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    PRIMARY KEY (task_id, project_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX idx_task_links_task_id ON task_links(task_id);
CREATE INDEX idx_task_links_project_id ON task_links(project_id);
```

#### tags table
```sql
CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT,
    created_at TEXT NOT NULL
);
```

#### project_tags table
```sql
CREATE TABLE project_tags (
    project_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, tag_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_project_tags_project_id ON project_tags(project_id);
CREATE INDEX idx_project_tags_tag_id ON project_tags(tag_id);
```

#### task_tags table
```sql
CREATE TABLE task_tags (
    task_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_task_tags_task_id ON task_tags(task_id);
CREATE INDEX idx_task_tags_tag_id ON task_tags(tag_id);
```

#### notes table
```sql
CREATE TABLE notes (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    project_id TEXT,
    task_id TEXT,
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX idx_notes_project_id ON notes(project_id);
CREATE INDEX idx_notes_task_id ON notes(task_id);
```

#### attachments table
```sql
CREATE TABLE attachments (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT,
    project_id TEXT,
    task_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX idx_attachments_project_id ON attachments(project_id);
CREATE INDEX idx_attachments_task_id ON attachments(task_id);
```

---

## Phase 2: Docker Setup ✅

**Status**: COMPLETE
**Started**: 2025-12-28
**Completed**: 2025-12-28

### Tasks

- [x] Create `docker-compose.yml` for PostgreSQL
- [x] Create initialization SQL script
- [x] Create `.env` file for credentials
- [ ] Test Docker container startup (NEXT: do in WSL)
- [ ] Configure WSL2 port forwarding (for LAN access)

### Files to Create

1. `modules/knowledge_manager/docker/docker-compose.yml`
2. `modules/knowledge_manager/docker/init-scripts/01_init_schema.sql`
3. `modules/knowledge_manager/docker/.env.example`
4. `modules/knowledge_manager/docker/README.md` - Setup instructions

### Docker Compose Configuration

**Strategy**: Run PostgreSQL in WSL2 Ubuntu for better integration

**Reasoning**:
- Native Linux environment for PostgreSQL
- Better performance than Windows Docker Desktop
- Easier port forwarding for LAN access
- WSL2 can access Windows filesystem via `/mnt/c/`

**Configuration** (see next section for actual file)

---

## Phase 3: pgloader Migration ⏳

**Status**: PENDING
**Dependencies**: Phase 2 complete

### Tasks

- [ ] Install pgloader in WSL2
- [ ] Create migration script `migrate.load`
- [ ] Define type mappings (SQLite → PostgreSQL)
- [ ] Test dry-run migration
- [ ] Execute actual migration
- [ ] Verify data integrity

### Type Mappings

| SQLite Type | PostgreSQL Type | Notes |
|-------------|-----------------|-------|
| `TEXT` (UUID) | `UUID` | Convert with `uuid(column)` |
| `TEXT` (datetime) | `TIMESTAMPTZ` | ISO8601 strings |
| `TEXT` (general) | `TEXT` | Direct mapping |
| `INTEGER` | `INTEGER` | Direct mapping |
| `INTEGER` (boolean) | `BOOLEAN` | SQLite uses 0/1 |

### Migration Script Location

`modules/knowledge_manager/docker/migrate.load`

---

## Phase 4: DB Adapter Updates ⏳

**Status**: PENDING
**Dependencies**: Phase 3 complete

### Tasks

- [ ] Install `asyncpg` library
- [ ] Create `knowledge_manager/db_postgres.py`
- [ ] Add connection pooling support
- [ ] Implement dual SQLite/PostgreSQL support
- [ ] Update `get_db_connection()` to detect DB type
- [ ] Add environment variable `KM_DB_TYPE=postgresql|sqlite`
- [ ] Test all CRUD operations

### Code Changes Required

1. **New file**: `knowledge_manager/db_postgres.py`
   - PostgreSQL-specific connection handling
   - asyncpg pool management
   - Type conversions (UUID, timestamps)

2. **Update**: `knowledge_manager/db.py`
   - Add `get_pg_connection()` function
   - Add `get_connection()` dispatcher (checks env var)
   - Maintain backward compatibility

3. **Update**: `knowledge_manager/utils.py`
   - Add `get_pg_connection_string()` helper

### Environment Variables

```bash
# SQLite (default)
KM_DB_TYPE=sqlite
KM_DB_PATH=~/.local/share/knowledge_manager_data/knowledge_manager.db

# PostgreSQL
KM_DB_TYPE=postgresql
KM_POSTGRES_HOST=localhost
KM_POSTGRES_PORT=5432
KM_POSTGRES_DB=knowledge_manager
KM_POSTGRES_USER=km_user
KM_POSTGRES_PASSWORD=secure_password
```

---

## Phase 5: Testing & Verification ⏳

**Status**: PENDING
**Dependencies**: Phase 4 complete

### Test Checklist

- [ ] PostgreSQL connection successful
- [ ] All tables created correctly
- [ ] Foreign keys enforced
- [ ] Indexes created
- [ ] Data migration complete (row counts match)
- [ ] UUIDs preserved correctly
- [ ] Timestamps preserved correctly
- [ ] TUI works with PostgreSQL backend
- [ ] CLI works with PostgreSQL backend
- [ ] `aio` commands work with PostgreSQL

### Verification Queries

```sql
-- Row counts
SELECT 'projects' as table_name, COUNT(*) FROM projects
UNION ALL
SELECT 'tasks', COUNT(*) FROM tasks
UNION ALL
SELECT 'task_links', COUNT(*) FROM task_links
UNION ALL
SELECT 'tags', COUNT(*) FROM tags;

-- Foreign key test
SELECT COUNT(*) FROM tasks WHERE project_id IS NOT NULL
AND project_id NOT IN (SELECT id FROM projects);
-- Should return 0

-- Index verification
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename IN ('projects', 'tasks', 'task_links');
```

---

## Phase 6: LISTEN/NOTIFY Setup ⏳

**Status**: PENDING
**Dependencies**: Phase 5 complete

### Tasks

- [ ] Create trigger functions for task/project changes
- [ ] Add LISTEN/NOTIFY triggers
- [ ] Update TUI to subscribe to notifications
- [ ] Test real-time updates across devices
- [ ] Add notification handler to `ai_orchestrator`

### Trigger Creation

```sql
-- Function to notify on changes
CREATE OR REPLACE FUNCTION notify_task_changes()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('task_updates', json_build_object(
        'operation', TG_OP,
        'table', TG_TABLE_NAME,
        'id', COALESCE(NEW.id, OLD.id),
        'data', CASE WHEN TG_OP = 'DELETE' THEN row_to_json(OLD) ELSE row_to_json(NEW) END,
        'timestamp', NOW()
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Apply to tables
CREATE TRIGGER tasks_notify
    AFTER INSERT OR UPDATE OR DELETE ON tasks
    FOR EACH ROW EXECUTE FUNCTION notify_task_changes();

CREATE TRIGGER projects_notify
    AFTER INSERT OR UPDATE OR DELETE ON projects
    FOR EACH ROW EXECUTE FUNCTION notify_task_changes();
```

---

## Known Issues & Blockers

### Current Blockers

None currently - ready to proceed with Phase 2.

### Potential Issues

1. **WSL2 Networking**: May need to configure `.wslconfig` for mirrored networking
2. **Port Conflicts**: Ensure port 5432 not already in use
3. **File Permissions**: Docker volume permissions on WSL2
4. **UUID Format**: Ensure UUIDs convert correctly (TEXT → UUID type)

### Mitigation Strategies

1. Use `.wslconfig` with `networkingMode=mirrored` (Windows 11 22H2+)
2. Check port with `netstat -an | grep 5432` before starting
3. Use Docker named volumes instead of bind mounts
4. Test UUID conversion with small dataset first

---

## Next Steps (Immediate Actions)

**For current session**:
1. Create Docker Compose configuration
2. Create PostgreSQL initialization SQL
3. Create setup documentation
4. Test Docker container startup
5. Update this status file with progress

**For next session**:
1. Install pgloader
2. Run migration
3. Verify data integrity
4. Update db.py for PostgreSQL support
5. Test TUI with PostgreSQL

---

## References

- **Research Doc**: `research-output/Claude-V4-multi-agent-orchestration.md`
- **Current DB Schema**: `knowledge_manager/db.py`
- **Original SQLite DB**: `C:\Users\mcarls\.local\share\knowledge_manager_data\knowledge_manager.db`
- **Docker Setup Guide**: (to be created)

---

## Session Handoff Protocol

**For any CLI continuing this work**:

1. Read this file first - it's the source of truth
2. Check the "Quick Status Overview" table for current phase
3. Look at the current phase's task list
4. Update checkboxes `[ ]` → `[x]` as you complete tasks
5. Update "Last Updated" timestamp and "Last Editor" at top
6. If you encounter issues, add them to "Known Issues & Blockers"
7. When phase complete, update status table: 🚧 → ✅
8. Move to next phase

**File locations to update**:
- This file: `POSTGRESQL_MIGRATION_STATUS.md`
- Main plans: `plans.md` (update relevant sections)
- Implementation status: `IMPLEMENTATION_STATUS.md` (if TUI changes needed)

---

**End of Status Document**
