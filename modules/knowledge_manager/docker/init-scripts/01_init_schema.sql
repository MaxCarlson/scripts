-- PostgreSQL Schema Initialization for Knowledge Manager
-- This script creates the database schema matching the SQLite structure
-- with PostgreSQL-native types and enhancements

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create ENUM types for status fields
CREATE TYPE project_status AS ENUM ('active', 'backlog', 'completed');
CREATE TYPE task_status AS ENUM ('todo', 'in-progress', 'done');

-- ============================================================================
-- PROJECTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    status project_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description_md_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_modified_at ON projects(modified_at DESC);

-- ============================================================================
-- TASKS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    status task_status NOT NULL DEFAULT 'todo',
    project_id UUID,
    parent_task_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    priority INTEGER CHECK (priority BETWEEN 1 AND 5),
    due_date DATE,
    details_md_path TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_modified_at ON tasks(modified_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date) WHERE due_date IS NOT NULL;

-- ============================================================================
-- TASK_LINKS TABLE (Cross-project bidirectional linking)
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_links (
    task_id UUID NOT NULL,
    project_id UUID NOT NULL,
    is_origin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (task_id, project_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_links_task_id ON task_links(task_id);
CREATE INDEX IF NOT EXISTS idx_task_links_project_id ON task_links(project_id);
CREATE INDEX IF NOT EXISTS idx_task_links_origin ON task_links(project_id) WHERE is_origin = TRUE;

-- ============================================================================
-- TAGS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    color TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);

-- ============================================================================
-- PROJECT_TAGS TABLE (Many-to-many relationship)
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_tags (
    project_id UUID NOT NULL,
    tag_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, tag_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_project_tags_project_id ON project_tags(project_id);
CREATE INDEX IF NOT EXISTS idx_project_tags_tag_id ON project_tags(tag_id);

-- ============================================================================
-- TASK_TAGS TABLE (Many-to-many relationship)
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_tags (
    task_id UUID NOT NULL,
    tag_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_tags_task_id ON task_tags(task_id);
CREATE INDEX IF NOT EXISTS idx_task_tags_tag_id ON task_tags(tag_id);

-- ============================================================================
-- NOTES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content TEXT NOT NULL,
    project_id UUID,
    task_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    CHECK (project_id IS NOT NULL OR task_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_notes_project_id ON notes(project_id);
CREATE INDEX IF NOT EXISTS idx_notes_task_id ON notes(task_id);
CREATE INDEX IF NOT EXISTS idx_notes_modified_at ON notes(modified_at DESC);

-- ============================================================================
-- ATTACHMENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS attachments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT,
    project_id UUID,
    task_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    CHECK (project_id IS NOT NULL OR task_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_attachments_project_id ON attachments(project_id);
CREATE INDEX IF NOT EXISTS idx_attachments_task_id ON attachments(task_id);

-- ============================================================================
-- TRIGGER FUNCTIONS FOR UPDATED_AT
-- ============================================================================

-- Function to automatically update modified_at timestamp
CREATE OR REPLACE FUNCTION update_modified_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.modified_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to projects
CREATE TRIGGER update_projects_modified_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_at_column();

-- Apply trigger to tasks
CREATE TRIGGER update_tasks_modified_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_at_column();

-- Apply trigger to task_links
CREATE TRIGGER update_task_links_modified_at
    BEFORE UPDATE ON task_links
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_at_column();

-- Apply trigger to notes
CREATE TRIGGER update_notes_modified_at
    BEFORE UPDATE ON notes
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_at_column();

-- ============================================================================
-- LISTEN/NOTIFY FUNCTIONS (For real-time updates)
-- ============================================================================

-- Function to notify on task changes
CREATE OR REPLACE FUNCTION notify_task_changes()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('task_updates', json_build_object(
        'operation', TG_OP,
        'table', TG_TABLE_NAME,
        'id', COALESCE(NEW.id, OLD.id),
        'data', CASE
            WHEN TG_OP = 'DELETE' THEN row_to_json(OLD)
            ELSE row_to_json(NEW)
        END,
        'timestamp', NOW()
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Apply LISTEN/NOTIFY triggers
CREATE TRIGGER tasks_notify
    AFTER INSERT OR UPDATE OR DELETE ON tasks
    FOR EACH ROW EXECUTE FUNCTION notify_task_changes();

CREATE TRIGGER projects_notify
    AFTER INSERT OR UPDATE OR DELETE ON projects
    FOR EACH ROW EXECUTE FUNCTION notify_task_changes();

CREATE TRIGGER task_links_notify
    AFTER INSERT OR UPDATE OR DELETE ON task_links
    FOR EACH ROW EXECUTE FUNCTION notify_task_changes();

-- ============================================================================
-- VIEWS (Optional - helpful for queries)
-- ============================================================================

-- View for tasks with full project info
CREATE OR REPLACE VIEW tasks_with_project AS
SELECT
    t.*,
    p.name as project_name,
    p.status as project_status
FROM tasks t
LEFT JOIN projects p ON t.project_id = p.id;

-- View for task hierarchy (tasks with parent info)
CREATE OR REPLACE VIEW task_hierarchy AS
SELECT
    t.id,
    t.title,
    t.status,
    t.project_id,
    t.parent_task_id,
    parent.title as parent_title,
    t.priority,
    t.due_date,
    t.created_at,
    t.modified_at,
    t.completed_at
FROM tasks t
LEFT JOIN tasks parent ON t.parent_task_id = parent.id;

-- ============================================================================
-- UTILITY FUNCTIONS
-- ============================================================================

-- Function to get task count by project
CREATE OR REPLACE FUNCTION get_project_task_counts(p_project_id UUID)
RETURNS TABLE (
    total INTEGER,
    todo INTEGER,
    in_progress INTEGER,
    done INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::INTEGER as total,
        COUNT(*) FILTER (WHERE status = 'todo')::INTEGER as todo,
        COUNT(*) FILTER (WHERE status = 'in-progress')::INTEGER as in_progress,
        COUNT(*) FILTER (WHERE status = 'done')::INTEGER as done
    FROM tasks
    WHERE project_id = p_project_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- INITIAL DATA (Optional - for testing)
-- ============================================================================

-- You can add initial test data here if needed
-- INSERT INTO projects (name, status) VALUES ('Test Project', 'active');

-- ============================================================================
-- PERMISSIONS (Optional - if creating specific users)
-- ============================================================================

-- Grant permissions to the application user
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO km_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO km_user;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO km_user;

-- ============================================================================
-- VERIFICATION QUERIES (Run these after migration to verify)
-- ============================================================================

-- Check table row counts
-- SELECT 'projects' as table_name, COUNT(*) FROM projects
-- UNION ALL SELECT 'tasks', COUNT(*) FROM tasks
-- UNION ALL SELECT 'task_links', COUNT(*) FROM task_links
-- UNION ALL SELECT 'tags', COUNT(*) FROM tags;

-- Check foreign key integrity
-- SELECT COUNT(*) FROM tasks WHERE project_id IS NOT NULL
--   AND project_id NOT IN (SELECT id FROM projects);

-- List all indexes
-- SELECT tablename, indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'public'
-- ORDER BY tablename, indexname;
