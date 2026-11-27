# ADR-001: Phase 0 Capability Verification & Architectural Decisions

- **Status:** Accepted (Phase 0 Gate Passed for Phase 1 M1)
- **Date:** 2026-11-19
- **Module:** `modules/agent_continuity` (`scripts` repository)
- **Branch / Worktree:** `feature/gui-agent-session-continuity` (`../scripts-agent-session-continuity`)
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b` (`main`)

---

## 1. Environment & Provider Inventory (Observed Read-Only Evidence)

### 1.1 Codex CLI

| Runtime | Executable | Version | Status | Verified Native Resume | Hook Support |
|---|---|---|---|---|---|
| Windows 11 | `C:\Users\mcarls\AppData\Roaming\npm\codex.ps1` (`@openai/codex-win32-x64`) | `codex-cli 0.170.0` | Installed & runnable | `codex resume <session_id>`, `codex fork <session_id>` | `codex features list` reports `hooks: stable (true)`. `codex.exe` contains `hooks.json`, `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SessionEnd`, `commandWindows`, `hook_event_name`. |
| WSL2 Ubuntu 24.04.3 LTS | `/mnt/c/Users/mcarls/AppData/Roaming/npm/codex` (Windows npm shim on WSL PATH) | N/A in WSL2 | Broken in WSL2 (`Missing optional dependency @openai/codex-linux-x64`) | N/A until native Linux `@openai/codex` is installed | Historical `~/.codex/` exists (Sep 26, 2026); no `~/.codex/hooks.json`. |

**Read-only Codex native storage observed on Windows (`~/.codex/`):**
- `state_5.sqlite`: SQLite database with `threads` table (`id`, `rollout_path`, `created_at`, `updated_at`, `source`, `model_provider`, `cwd`, `title`, `first_user_message`, `archived`, `git_sha`, `git_branch`, `git_origin_url`, `cli_version`, `attached_thread_parent_id`, `created_at_ms`, `updated_at_ms`, `recency_at_ms`, etc.) and `thread_spawn_edges`.
- `session_index.jsonl`: 575 entries (`id`, `thread_name`, `updated_at`).
- `sessions/`: 702 rollout files totaling **731.24 MB**, max single rollout **195.33 MB**. This confirms Master Plan §2.1 & §7.2: full rollout deserialization must never occur during routine lookup.
- `config.toml`: Currently uses legacy `notify` (`notify.ps1`), no `hooks.json` installed.

### 1.2 Antigravity CLI (`agy`)

| Runtime | Executable | Version | Status | Verified Native Resume | Hook Support |
|---|---|---|---|---|---|
| Windows 11 | `C:\Users\mcarls\AppData\Local\Microsoft\WinGet\Links\agy.EXE` | `1.5.12` | Installed & runnable | `agy --conversation <id>`, `agy --continue` (`-c`) | Documented in `~/.gemini/antigravity-cli/builtin/skills/agy-customizations/docs/hooks.md`: `hooks.json` in `~/.gemini/config/hooks.json` or `.agents/hooks.json`. Events: `SessionStart`, `PreInvocation`, `PostInvocation`, `Stop`, `PreToolUse`, `PostToolUse`. |
| WSL2 Ubuntu 24.04.3 LTS | `/home/mcarls/.local/bin/agy` | `1.2.11` | Installed & runnable | `agy --conversation <id>`, `agy --continue` (`-c`) | Separate `~/.gemini/antigravity-cli/` (`installation_id`: `1f32fe79-caf8-46be-bf00-d1effc5fe79a`) and `~/.gemini/antigravity/`. Note: `1.2.11` CLI `--help` omits `--remote-agent` and `--settings` present in `1.5.12`. |

**Read-only AGY native storage observed:**
- Windows `~/.gemini/antigravity-cli/`:
  - `conversation_summaries.db`: `conversation_summaries` table (`conversation_id`, `title`, `preview`, `step_count`, `last_modified_time`, `workspace_uris`, `status`, `source`, `project_id`, `agent_name`, `parent_conversation_id`, `last_user_input_time`, `last_user_input_step_index`, `app_data_dir`), `conversation_parents`, `conversations_fts`.
  - `conversations/`: 80 `.db`/WAL/SHM files totaling **1038.75 MB**, max **91.47 MB**.
  - `history.jsonl`: 1005 entries (`display`, `timestamp`, `workspace`).
  - `settings.json`: Does not currently configure hooks.
- Windows `~/.gemini/antigravity/`: Separate Antigravity 2.0 store (`conversation_summaries.db` 20 KB, 0 conversations). Confirms Master Plan §7.3 surface isolation requirement.
- AGY hook contract specifics (`hooks.md`):
  - Payloads use camelCase JSON on stdin (`conversationId`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`, `modelName`, `lastUserInput`, `hookEventName`, `cwd`; `PreInvocation` adds `invocationNum`, `initialNumSteps`; `Stop` adds `executionNum`, `terminationReason`, `error`, `fullyIdle`, `continuationActive`).
  - Output JSON on stdout varies by hook (`{}` is explicitly documented for `PostToolUse`; `SessionStart`/`PreInvocation`/`PostInvocation` accept `{}` or `injectSteps`/`terminationBehavior`; `Stop` uses `decision`).

---

## 2. Phase 0 Architecture Decisions

### Decision 1 — Repository & Package Boundary (Gate E)
- **Decision:** Host the module in `scripts` at `modules/agent_continuity` with Python package `agent_continuity`.
- **Rationale:** `scripts` already hosts modular Python CLIs (`procwatch`, `notifications`, `development_ledger`, `agent_sync`), `scripts_help` registry, and Python 3.12 + pytest + ruff tooling. `modules/ai_orchestrator` (`aio` v0.1.0) targets model/CLI selection and `knowledge_manager` tasks; keeping `agent_continuity` independent with a clean Python API preserves decoupling (`Master Plan §16.1`).
- **Runtime Dependencies:** Pure Python 3.11+ standard library (`dependencies = []`) so the package installs and runs cleanly in both Windows `.venv` and WSL2 Ubuntu Python 3.12 without requiring network package installs or native compilation.

### Decision 2 — CLI Command Name
- **Decision:** Use `agents` (`agents = "agent_continuity.cli:main"`), plus `python -m agent_continuity`.
- **Rationale:** Checked Windows `Get-Command agents`, PowerShell `Get-Alias agents`, WSL2 `which agents`, and all `modules/*/pyproject.toml` `[project.scripts]` entries: zero conflicts. Registered in `modules/scripts_help/scripts_help/registry/registry.py`.
- **Convention Compliance:** Every user-facing CLI option provides both short and long flags per `PYTHON_REPO_STANDARDS.md`. All mutating commands default to dry-run and require `-a`/`--apply`.

### Decision 3 — Workflow Identifier Format
- **Decision:** Generate immutable IDs as `wf_<6 lowercase hex chars>` (e.g., `wf_7d3a92`), checked for uniqueness against existing registry entries, supporting `^wf_[0-9a-f]{6,16}$`. Slugs are lowercase `[a-z0-9][a-z0-9_-]{0,63}`, unique across workflows, and act as aliases that resolve to `workflow_id`.
- **GUI URL Normalization:** Normalize ChatGPT conversation URLs (`https://chatgpt.com/c/<id>` or `https://chat.openai.com/c/<id>`) by trimming whitespace, stripping trailing slashes/query/fragment noise into `canonical_url` while keeping the raw `url` if needed.

### Decision 4 — Environment Identity & Compound Session Key
- **Decision:** Represent every native session with the compound primary key `(provider, environment_id, native_session_id)`.
- **Environment IDs:** Each runtime maintains a persisted `environment.json` inside its local data directory (`~/.agent_continuity/environment.json` or overridden via `AGENT_CONTINUITY_HOME`) containing a stable `environment_id` (e.g., `env_win_<host8>_<rand4>` or `env_wsl_<distro>_<rand4>`), `runtime_kind` (`windows` | `wsl` | `linux` | `macos`), `distro`, `hostname`, and `label`. A distro name alone is never assumed unique across reinstalled distros. Friendly CLI environment selectors (`windows`, `wsl`, `wsl:Ubuntu`, or exact `environment_id`) resolve unambiguously against registered environments.

### Decision 5 — Durable Event Format & Transport (Gate C)
- **Decision:** Use **atomic per-event JSON files** inside environment-isolated spool directories:
  `<spool_root>/<environment_id>/<observed_ts_compact>_<event_id>.json`, written via temporary file + `os.replace()`.
- **Rationale:** Unlike a single shared `events.jsonl` file, atomic per-event files cannot suffer interleaved line writes or partial trailing JSON lines under concurrent hook or CLI invocations, and `os.replace()` within the same filesystem avoids cross-process reader races.
- **Cross-OS Transport:** Windows hooks/CLI write to `<win_state_root>/events/<win_env_id>/`. WSL2 hooks/CLI write to WSL2-native `~/.agent_continuity/events/<wsl_env_id>/` (or an explicitly configured bridge spool root). Additional read-only external spool roots (such as WSL2's spool accessed from Windows via `\\wsl.localhost\Ubuntu\...` or staged exports) can be registered in `spool_sources` for ingestion by the designated SQLite writer.

### Decision 6 — Authoritative SQLite Writer Ownership (Gate D)
- **Decision:** One designated runtime owns writes to `index.sqlite` (Windows native runtime by default on a Windows/WSL2 host, or the active local runtime when running in an isolated `AGENT_CONTINUITY_HOME`).
- **Safety Guard:** When running under WSL2 (`is_wsl2()`), if the resolved `index.sqlite` path resides on `/mnt/<drive>/...` (Windows NTFS mount), `agent_continuity` refuses to open `index.sqlite` for writes (`cross_environment_unavailable` / unsafe cross-OS SQLite write guard). Read-only inspection or local WSL2 event spooling remains available without touching the Windows-owned SQLite file.
- **SQLite Settings:** `WAL` journal mode, `foreign_keys=ON`, `busy_timeout=5000`, schema version tracked in `schema_metadata`.

### Decision 7 — Association Data Model & Precedence
- **Decision:** Do NOT enforce a 1-session-to-1-workflow unique constraint. Store associations in `associations` keyed by `association_id` with `evidence_level` (`confirmed`, `strong`, `candidate`, `unknown`, `rejected`), `status` (`active`, `superseded`, `unlinked`, `rejected`, `conflict`), and provenance rows in `association_evidence`.
- **Conflict Behavior:** If `link` targets a session that already has an active `confirmed` or `strong` association to a different workflow, the operation detects and reports `association_conflict` unless `-X`/`--supersede` is explicitly specified (which marks the prior association `superseded` while preserving its provenance history).

### Decision 8 — Phase 2/3 Deferral Boundary
- **Deferred to Phase 2:** Installing persistent Codex/AGY hooks (`hooks.json`), live hook payload capture testing (new vs. resumed sessions), workflow marker extraction, and lineage inheritance.
- **Deferred to Phase 3:** Bounded read-only recovery scanners for Codex `state_5.sqlite`/rollouts and AGY `conversation_summaries.db`/`conversations/*.db`, handoff fingerprinting, summary previews, and automated checkpoint validation.
- **Phase 1 Scope:** Registry, manual association/unlinking, candidate rejection, durable event spools, SQLite materializer + atomic rebuild, continuity queries, dry-run-by-default CLI with JSON output, provider adapter foundation (read-only binary detection + verified resume command formatting), and diagnostics (`doctor`).
