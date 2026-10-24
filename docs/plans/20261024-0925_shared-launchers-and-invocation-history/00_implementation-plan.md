# Shared Launchers and Invocation-History Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement generated cross-platform wrappers, centralized invocation recording, robust SQLite persistence, and a stable read-only query API for the `scripts` repository toolkit.

**Architecture:** A lightweight native wrapper (`.cmd` on Windows, bash on POSIX) routes CLI invocations to a unified launcher entry point (`script_logging.launcher`). The launcher validates program identity from a versioned manifest (`scripts_manifest.json`), records invocation start in a dedicated SQLite database (`invocations.sqlite3`), executes the target child process with exact stdio and argv fidelity, records completion/exit status, and exits with the child's exact return code. A separate read-only history reader and query API in `script_logging` provides deterministic pagination, statistics, and reconciliation without write locks.

**Tech Stack:** Python 3.8+ (standard library: `sqlite3`, `subprocess`, `argparse`, `pathlib`, `json`, `hashlib`, `uuid`), Windows batch (`.cmd`), POSIX shell (`bash`), `pytest`, `ruff`.

**Spec:** `Handoff 1 — Shared Launchers and Invocation-History Infrastructure` (2026-10-24 baseline `6fa307f3bd84761f6fe21f3700dceb9889fe090b`).

## Global Constraints

- Never collect environment variables, arbitrary stdin/stdout/stderr, shell command text, or credentials.
- Instrument only known generated wrappers; do not claim global shell interception.
- Logging failures must be strictly fail-open: database locking, corruption, or permission errors must not block child process execution.
- Target resolution failures remain ordinary actionable launch failures (exit code 127 with diagnostic message).
- Read-only operations (`ReadOnlyHistoryReader`) must NEVER create directories, initialize missing databases, run schema migrations, or acquire write locks.
- Preserve full Windows argv fidelity: handle quotes, spaces, empty strings, metacharacters (`%`, `!`, `^`, `&`, `|`, `<`, `>`, `(`, `)`), Unicode, and `--` across PowerShell 7 and CMD.
- The shared generator defaults to non-destructive dry-run (`-n`/`--dry-run`); wrapper migration requires explicit apply (`-a`/`--apply` or `-w`/`--write`) with pre-migration backup and rollback support.
- Bump `script_logging` version from `0.1.0` to `0.2.0` (MINOR) in `pyproject.toml` and `__init__.py`. Keep all existing `script_logging` public interfaces (`EventRecord`, `RunRecord`, `HistoryStore`) intact.

## Review Focus

1. Windows argument fidelity through batch expansion: Batch `%*` expansion dropping empty arguments `""` or corrupting metacharacters (`^`, `%`, `&`, `|`) when calling Python. Pin with a dedicated diagnostic argv-echo test suite covering both CMD and PowerShell 7.
2. Recursive launcher execution: A wrapper resolving back to itself or another launcher proxy in PATH. Pin with explicit wrapper target validation and recursion guard tests.
3. Database locking / WAL concurrency under rapid sequential or parallel invocations: Multiple concurrent processes recording invocations simultaneously. Pin with multi-process concurrency tests using SQLite WAL and busy timeouts.
4. Fail-open execution when database is completely unwritable: Target process must still run normally, preserving stdio and exit code, even if SQLite throws `OperationalError`. Pin with read-only/unwritable database tests.
5. Indiscriminate secret redaction vs true credentials: Redacting legitimate short flags like `-p 8080` or `--path` while ensuring sensitive values like `--token=<secret>`, `--token <secret>`, and userinfo in URLs are safely redacted. Pin with comprehensive redaction unit tests.

---

## File Structure & Component Boundaries

### Component 1: `modules/script_logging` Invocation Persistence & Models
- `modules/script_logging/script_logging/models.py`: Data structures for invocation records, command patterns, statistics, pagination, and reconciliation reports.
- `modules/script_logging/script_logging/redaction.py`: Privacy filtering, token/credential sanitization, URL userinfo scrubbing, and bounded truncation.
- `modules/script_logging/script_logging/invocation_store.py`: `InvocationStore` managing SQLite connection, WAL mode, schema migrations, start/finish records, and atomic counter invariants.
- `modules/script_logging/script_logging/reader.py`: `ReadOnlyHistoryReader` with SQLite URI `mode=ro`, deterministic sorting, and cursor pagination.
- `modules/script_logging/script_logging/reconciliation.py`: Recomputes pattern, program, and alias counters from immutable invocation rows.
- `modules/script_logging/script_logging/launcher.py`: Entry point for managed wrappers; resolves target from manifest, executes child, records start/finish, handles signals and fail-open errors.
- `modules/script_logging/script_logging/__init__.py`: Public API exports and version bump to `0.2.0`.

### Component 2: `scripts_setup` Generator & Migration Tooling
- `scripts_setup/launcher_generator.py`: Scans repo-owned programs (modules, standalone pyscripts, shell scripts), detects collisions, writes `scripts_manifest.json`, generates native wrappers with signature, provides dry-run, backup, apply, and rollback.
- `modules/setup.py`, `pyscripts/setup.py`, `bootstrap_latest.py`, `scripts_setup/setup_utils.py`: Refactored to delegate wrapper generation to `scripts_setup.launcher_generator`.

### Component 3: Integration & Contracts
- `CONTRACT.md`: Canonical identity, invoke/finish lifecycle, status semantics, query signatures, paging, sort behavior, schema version, state paths, representative synthetic records.
- `modules/script_logging/tests/fixtures/synthetic_history.py`: Deterministic test fixture for `scripts_help` consumer integration testing.
- `modules/script_logging/tests/argv_echo_target.py`: Diagnostic argv echo helper for cross-platform fidelity testing.

---

## Stages Overview

- **Stage 1: Invocation Store, Redaction, Schema, and Core Persistence** (`01_stage1-invocation-store-and-redaction.md`)
  - Schema setup, migrations, WAL configuration, default path resolution.
  - Redaction engine and privacy filters.
  - `start_invocation` and `finish_invocation` lifecycle with atomic counter invariants.
  - Concurrency, fail-open handling, and busy timeouts.

- **Stage 2: Read-Only Query API, Reader, and Reconciliation** (`02_stage2-readonly-reader-and-query-api.md`)
  - `ReadOnlyHistoryReader` with URI `mode=ro` (no directory or file creation).
  - Query APIs: `list_invocations`, `list_unique_commands`, `get_program_statistics`, `get_command_statistics` with cursor pagination and deterministic sorting.
  - `reconcile_invocation_summaries` (dry-run and apply).
  - Synthetic fixture for consumer (`scripts_help`) testing.

- **Stage 3: Launcher Execution Engine & Diagnostic Argv-Echo** (`03_stage3-launcher-engine-and-argv-fidelity.md`)
  - `script_logging.launcher` entry point.
  - Target resolution, recursion prevention (wrapper guard), origin tagging (`origin=launcher`, `inspection`, etc.).
  - Process execution, stdio streaming, signal / Ctrl+C handling, exit code fidelity.
  - Fail-open execution (if database fails/locks, target still executes).
  - Diagnostic argv-echo tool and test suite for Windows PowerShell 7 / CMD and POSIX argv fidelity.

- **Stage 4: Manifest Generator, Unified Wrappers, Migration & Rollback** (`04_stage4-manifest-generator-and-migration.md`)
  - Repository scanner (modules, pyscripts, shell scripts) & manifest generator (`scripts_manifest.json`).
  - Name collision & Windows case-insensitivity checks.
  - Native wrapper generator (Windows `.cmd` and POSIX bash) with managed signature.
  - Dry-run diff, backup, apply migration, and rollback tooling.
  - Integration with `modules/setup.py`, `pyscripts/setup.py`, `bootstrap_latest.py`, and `scripts_setup`.

- **Stage 5: End-to-End Validation, Overhead Benchmarks, Contract & Documentation** (`05_stage5-validation-benchmarks-and-contract.md`)
  - End-to-end integration tests (wrapper -> launcher -> database -> reader).
  - Multi-process stress & concurrency testing.
  - Startup overhead measurement (cold/warm p50/p95).
  - `CONTRACT.md` and updated repository documentation.
