# Stage 2: P1 Conservative Transactional Editing & Compare

**Parent Plan:** [00_implementation-plan.md](00_implementation-plan.md)  
**Status:** Planned  

## Scope

Deliver conservative, atomic, user-controlled modifications and database comparison:
- `init`: create new empty SQLite DB or execute user-supplied schema SQL with dry-run preview.
- `edit`: single-row edit targeting stable primary key with optimistic concurrency check (`WHERE pk = ? AND (col = ? OR ...)`), failing if rowcount != 1.
- `insert`: single-row insert with value preview and foreign key enforcement.
- `delete`: single-row delete targeting primary key with preview and atomic rollback on errors.
- `sql`: mutation runner requiring explicit `-w/--write`, safety confirmation, pre-write backup, and blocking of ATTACH and extension loading.
- `restore`: safe restore to new path or confirmed overwrite with target backup and WAL/SHM cleanup.
- `compare`: schema DDL diff and row-level diff between two independent databases.

## Deliverables

1. `db_manager/connections.py`: Write connection helper with foreign key enforcement and authorizer blocking ATTACH and extensions.
2. `db_manager/changes.py`: Mutation planning, optimistic concurrency checks, pre-write backup orchestration, rowcount verification, and database comparison.
3. `db_manager/cli.py`: Integrate `init`, `edit`, `insert`, `delete`, `sql`, `restore`, `compare` subcommands.
4. `tests/changes_test.py`, `tests/compare_test.py`.

## Verification Criteria

- Dry-run by default: no file changes occur unless `-w/--write` is supplied.
- Concurrency conflict (concurrently modified row) aborts edit and rolls back.
- Foreign key violation aborts edit/insert/delete and rolls back.
- Attempt to mutate without primary key or affecting >1 row raises an error.
