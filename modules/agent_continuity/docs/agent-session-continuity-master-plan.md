# GUI–Agent Session Continuity Module
## Unified Master Implementation Plan — Version 3.0

**Status:** Research-informed architecture; pending local capability verification  
**Date:** November 19, 2026  
**Document type:** Governing implementation master plan  
**Suggested filename:** `agent-session-continuity-master-plan.md`  
**Target environments:** Windows 11, PowerShell 7+, WSL2/Ubuntu  
**Target providers:** OpenAI Codex CLI and Google Antigravity CLI (`agy`)  
**Candidate implementation host:** `scripts` repository  
**Related integration project:** `ai-orchestrator`  
**Primary architecture:** Hybrid hook-first session registry with minimal workflow identifiers, provider-independent event storage, and bounded historical recovery

---

# 1. Executive Summary

## 1.1 Objective

Develop a local-first software module that reliably associates long-lived consumer ChatGPT GUI conversations with the native coding-agent sessions used to execute their implementation handoffs.

The module must preserve the user's existing development workflow:

1. A ChatGPT GUI conversation performs research, architectural analysis, planning, and handoff generation.
2. The user copies an implementation handoff into Codex or AGY.
3. The coding agent inspects repositories, implements changes, tests, and reports results.
4. The user copies the agent's completion summary into the associated ChatGPT GUI conversation.
5. The GUI model evaluates progress and produces subsequent handoffs.
6. Work may alternate between Codex and AGY because of usage quotas or other operational constraints.
7. Native agent conversations may be started fresh or resumed through their normal interfaces.

A single ChatGPT GUI conversation may therefore be associated with multiple Codex and AGY sessions across Windows and WSL2.

The primary deliverable is a dependable way to answer:

> For this ChatGPT GUI conversation, which coding-agent sessions belong to it, which session contains the latest relevant work, and how do I resume the appropriate session?

The system should eliminate routine manual history searches and repeated handoff-content matching.

## 1.2 Primary design objective

**Maximize reliable workflow-to-session association while minimizing additional user actions.**

The module must not require the user to abandon native Codex or AGY commands, use a custom launcher for every session, or operate a complex orchestration platform.

The target daily experience is:

- Register each GUI workflow once.
- Have ChatGPT include one small workflow identifier in implementation handoffs.
- Continue using Codex and AGY normally.
- Allow native hooks or other verified integration mechanisms to observe sessions.
- Retrieve the associated sessions through one command.
- Resolve ambiguous associations only when necessary.

## 1.3 Recommended architecture

The research favors a **hybrid hook-first architecture** comprising:

1. A persistent local workflow registry.
2. Minimal, stable workflow identifiers embedded in handoffs.
3. Native provider lifecycle integrations where verified.
4. Thin, fail-open event capture adapters.
5. Environment-isolated event persistence.
6. A provider-independent SQLite materialized index.
7. Rule-based association and provenance tracking.
8. Native session lookup and resume support.
9. Bounded, read-only historical recovery.
10. Optional enrichment and orchestration interfaces.

The architecture deliberately separates two problems:

**Session discovery:** Determining which native sessions exist and what activity occurred.

**Workflow association:** Determining which ChatGPT GUI conversation a native session or particular turn belongs to.

Neither problem should be assumed to solve the other.

---

# 2. Source Basis and Confidence

This plan synthesizes:

- Gemini's architectural research on Codex, AGY, ChatGPT GUI identity, and session association.
- Gemini's synthesized implementation plan v2.0.
- ChatGPT's earlier Master Implementation Plan Draft 1.
- The user's stated workflow, preferences, and operational constraints.

## 2.1 Research-supported architecture

The supplied research strongly supports investigating native hooks as the primary session-discovery mechanism, with lightweight workflow tags as the primary association mechanism.

It also identifies several implementation hazards:

- Codex session indexes and transcript files may become inconsistent.
- Large rollout files can make retrospective scanning expensive.
- AGY's CLI, desktop, and IDE session stores may be distinct.
- Hook schemas and behavior can vary by provider version.
- Windows and WSL2 maintain separate runtime and filesystem contexts.
- A shared repository cannot reliably identify a GUI workflow.
- Consumer ChatGPT conversations do not provide an established local session-association interface.

These findings motivate the architecture but do not replace local verification.

## 2.2 Verification policy

The following must be treated as **provisional until checked against the installed versions**:

- Exact Codex hook events, payload fields, and configuration schema.
- Exact AGY hook events, payload fields, and configuration schema.
- Hook behavior when sessions are resumed or forked.
- AGY `lastUserInput`, `invocationNum`, and `initialNumSteps` semantics.
- Codex `commandWindows`, hook trust, and async execution behavior.
- AGY status-line fields and execution behavior.
- Native resume command syntax.
- Native transcript and SQLite storage schemas.
- Session ID persistence and fork lineage.
- Cross-environment filesystem and event transport behavior.

The implementation agent must not convert research claims into hardcoded contracts without evidence.

## 2.3 Decision authority

This document governs the overall architecture and implementation sequence.

Phase 0 may revise provider adapters, storage transport, or implementation ownership when local evidence contradicts research assumptions.

Material architectural changes must be documented through an architecture decision record rather than silently incorporated.

---

# 3. Problem Definition

## 3.1 Three independent identity domains

The user's workflow spans three domains.

### Coordination domain

Consumer ChatGPT GUI conversations contain:

- Research.
- Architectural decisions.
- Implementation handoffs.
- Agent completion reports.
- Follow-up planning.
- Project-specific historical context.

Each GUI conversation has an observable browser identity, typically represented by a conversation URL.

### Execution domain

Codex and AGY maintain their own:

- Native session identifiers.
- Conversation histories.
- Resume mechanisms.
- Runtime metadata.
- Working directories.
- Provider-specific storage.

One GUI conversation may involve many execution sessions.

### Codebase domain

Git repositories contain implementation state.

However, repository identity is not workflow identity.

Multiple ChatGPT GUI conversations may coordinate independent work within the same repository.

## 3.2 Current failure mode

The user may return to a GUI conversation after working on several other projects and no longer remember:

- Which provider executed the most recent handoff.
- Which native session ID was used.
- Whether the session was resumed.
- Whether a newer session was created.
- Whether an older session contains the latest validated work.
- Which session should be continued next.

The current workaround involves providing another coding agent with GUI conversation names and recent handoffs, then asking it to search native histories for matching sessions.

This is repetitive, consumes agent resources, and depends on retrospective inference.

## 3.3 Why repository and timestamp matching are insufficient

A repository may contain several simultaneous workflows.

A recently active session may belong to a different GUI conversation.

An older session may have been resumed after a newer session was created.

A session may be opened without a new implementation turn.

A session may contain unsuccessful work even though it was recently active.

Consequently, the module must maintain explicit identity and evidence relationships rather than selecting sessions solely by directory or timestamp.

---

# 4. Scope, Requirements, and Non-Goals

## 4.1 Required capabilities

The primary release must support:

1. Persistent workflow registration.
2. Association of one workflow with multiple GUI conversation references.
3. Association of one workflow with multiple native sessions.
4. Codex and AGY provider identities.
5. Windows and WSL2 environment identities.
6. Native session discovery where supported.
7. Native session resumption where supported.
8. Manual session linking as a universal fallback.
9. Automatic association from explicit workflow identifiers.
10. Preservation of associations across native resumes.
11. Explicit conflict detection.
12. Multiple workflows using the same repository.
13. Historical session recovery.
14. Evidence-aware session lookup.
15. Distinction between activity, completed turns, summaries, and validated checkpoints.
16. Structured CLI output.
17. Safe recovery from registry/index failures.

## 4.2 Hard constraints

The design must:

- Preserve native Codex and AGY launch/resume workflows.
- Never infer workflow ownership from repository identity alone.
- Never silently promote heuristic associations to confirmed status.
- Never modify native provider session stores during discovery.
- Avoid simultaneous Windows/WSL writes to one shared SQLite database.
- Avoid full transcript scans during routine lookup.
- Remain usable when provider hooks are unavailable.
- Require explicit authorization before changing provider configuration.
- Avoid introducing a background daemon unless its necessity is demonstrated.

## 4.3 Non-goals

The primary release will not:

- Automate the entire ChatGPT GUI-to-agent development cycle.
- Read or modify ChatGPT conversations through unsupported APIs.
- Require browser extensions.
- Monitor the clipboard continuously.
- Replace native session histories.
- Manage agent quotas or provider accounts.
- Automatically merge Git branches.
- Automatically execute new implementation handoffs.
- Run cloud embedding services for routine association.
- Implement an agent scheduler.
- Store complete transcripts in the registry.
- Require the user to operate a managed launcher.

These may be considered separately if future requirements justify them.

---

# 5. Architectural Overview

## 5.1 Logical topology

```text
                CHATGPT GUI
          Research / Planning / Handoffs
                       |
                Workflow-ID token
                       |
                       v
          +-------------------------+
          | Workflow Identity       |
          | Registry                |
          +-------------------------+
                       |
                       v
          +-------------------------+
          | Association Engine      |
          | Evidence + Provenance   |
          +-------------------------+
                       ^
                       |
           Normalized Session Events
                       |
          +-------------------------+
          | Event Materializer      |
          | SQLite Query Index      |
          +-------------------------+
                       ^
                       |
          +-------------------------+
          | Environment-Isolated    |
          | Durable Event Storage   |
          +-------------------------+
                 ^           ^
                 |           |
          +-----------+ +-----------+
          | Codex     | | AGY       |
          | Adapter   | | Adapter   |
          +-----------+ +-----------+
                 ^           ^
                 |           |
          Native Codex   Native AGY
          Sessions       Sessions

          +-------------------------+
          | agents CLI / Python API |
          | find / link / resume    |
          | recover / doctor        |
          +-------------------------+
```

The diagram describes logical responsibilities.

It does not imply that each component requires a separate service or process.

## 5.2 Primary implementation units

| Component | Responsibility |
|---|---|
| Workflow registry | Persistent GUI workflow identities and references |
| Provider adapters | Normalize native Codex/AGY capabilities and events |
| Hook shims | Capture native events with minimal execution overhead |
| Event transport | Persist events safely across runtime boundaries |
| Materializer | Build queryable state from durable events |
| Association engine | Resolve explicit identifiers and preserve provenance |
| Continuity queries | Select sessions according to distinct activity semantics |
| Recovery adapters | Read historical metadata with strict resource limits |
| Resume dispatcher | Produce or invoke supported native resume operations |
| CLI | User-facing commands and structured output |
| Diagnostics | Verify installation, event flow, and data integrity |

---

# 6. Workflow Identity Design

## 6.1 Stable workflow identity

Each workflow receives:

- An immutable internal workflow ID.
- A human-readable slug.
- A display title.
- Zero or more ChatGPT GUI conversation references.
- Optional repository associations.
- Creation and update timestamps.
- An active/archived state.

The immutable ID is the authoritative identity.

The slug is a convenient alias and must not be the sole durable identifier if renaming is supported.

Example:

```text
workflow_id: wf_7d3a92
slug: procwatch
title: ProcWatch Development
gui_url: https://chatgpt.com/c/<conversation-uuid>
```

The exact ID format is provisional.

## 6.2 GUI conversation references

A workflow may have multiple GUI conversation references.

This supports cases such as:

- A continuation conversation.
- A manually associated successor thread.
- A branched conversation.
- A conversation URL change.

A new GUI conversation must not automatically inherit ownership merely because it has a similar title or shares a repository.

Associating multiple GUI conversations with one workflow requires an explicit relationship or equivalent trustworthy evidence.

## 6.3 Minimal handoff identifier

Use one canonical marker:

```text
Workflow-ID: wf_7d3a92
```

A human-readable slug may be supported as an alias:

```text
Workflow-ID: procwatch
```

However, the registry should resolve aliases to immutable workflow IDs before recording associations.

For backward compatibility, the parser may also accept:

```text
[wf:procwatch]
```

An optional handoff identifier can be added later:

```text
Workflow-ID: wf_7d3a92
Handoff-ID: phase-06
```

The second field is not required for initial session association.

## 6.4 User setup

A workflow registration command should provide a short instruction for the user to place in the associated ChatGPT GUI conversation:

> Begin each implementation handoff with `Workflow-ID: wf_7d3a92`.

The module should not assume it can automatically modify the GUI conversation's instructions.

Clipboard copying is an optional convenience, not a requirement.

## 6.5 Tag validation

A workflow marker is strong evidence, but not cryptographic proof.

The parser must:

- Accept only known, registered workflow IDs or aliases.
- Prefer an exact, standalone marker near the beginning of a submitted handoff.
- Avoid treating quoted examples or code snippets as authoritative markers.
- Apply length and format limits.
- Reject malformed or conflicting identifiers.
- Preserve the original association when conflicting evidence appears.
- Never execute content extracted from prompts.

An exact marker establishes a strong link to a workflow, subject to conflict checks.

It must not be represented as mathematically certain or immune to copying errors.

---

# 7. Native Provider Integration

## 7.1 Provider adapter contract

All provider-specific behavior must be isolated behind a common interface.

Conceptual operations:

```text
detect_installation()
get_version()
get_capabilities()
normalize_hook_event()
discover_sessions()
get_session_metadata()
scan_history()
resolve_resume_command()
get_health_status()
```

The actual Python interface should be finalized after repository inspection.

Each adapter must explicitly report unsupported capabilities.

A provider should remain usable through manual linking even if its discovery adapter fails.

## 7.2 Codex adapter

### Research-supported integration candidates

Investigate Codex lifecycle hooks for:

- Session creation or startup.
- Native resumption.
- User prompt submission.
- Completed assistant turns.
- Session termination.
- Fork lineage.

Candidate event names from the supplied research include:

```text
SessionStart
UserPromptSubmit
Stop
SessionEnd
```

Verify names and schemas against the installed Codex version.

### Event capture

Where supported:

- Session startup updates `last_seen_at`.
- Prompt submission updates `last_turn_at`.
- Completed assistant turns update `last_completed_turn_at`.
- Workflow tags in submitted prompts establish association evidence.
- Native session IDs establish continuity across resumes.
- Fork events or metadata establish parent-child relationships.

Do not assume that opening a session advances its native `updated_at` field.

### Hook installation

Prefer supported user-level hooks.

Preserve existing configuration and unrelated hooks.

Avoid legacy notification mechanisms when the installed Codex version provides a more reliable supported hook interface.

Use a stable hook entrypoint where appropriate, but verify whether trust is based on the command path, command content, or another mechanism.

Do not assume that keeping a script filename unchanged guarantees trust persistence.

### Historical fallback

Investigate read-only access to:

- Native session metadata indexes.
- Native SQLite metadata stores.
- Session title indexes.
- Archived-session metadata.
- Rollout headers or bounded excerpts.

Never deserialize an entire multi-gigabyte rollout during ordinary lookup.

Compressed rollout formats require a bounded decompression strategy, not arbitrary tail reads of compressed bytes.

## 7.3 AGY adapter

### Research-supported integration candidates

Investigate AGY lifecycle hooks for:

```text
SessionStart
PreInvocation
PostInvocation
Stop
```

The research suggests that `PreInvocation` may be necessary to observe resumed sessions, while `SessionStart` may only fire for newly created sessions.

Verify this behavior locally.

### Prompt extraction

Prefer direct hook payload fields when supported.

If prompt text is unavailable:

- Inspect a bounded transcript excerpt.
- Use provider-specific parsers isolated from core logic.
- Apply strict size and time limits.
- Report unavailable data rather than fabricating it.

Verify `lastUserInput`, `conversationId`, `transcriptPath`, `invocationNum`, and `initialNumSteps` semantics before implementing deduplication.

### Hook safety

Do not install `PreToolUse` telemetry hooks unless research and local testing establish that they cannot accidentally deny tool execution.

Use only documented, validated stdout behavior.

An empty JSON object is not universally safe across every hook type.

### Optional status-line integration

AGY status-line telemetry may provide:

- Session identity.
- Conversation title.
- Working directory.
- Agent state.
- Model information.
- Quota-related metadata.

Treat this as an optional enrichment mechanism.

It should not be required for core workflow association.

If enabled, implement throttling, error handling, and data minimization.

### Surface isolation

Do not assume AGY CLI, desktop, and IDE share one session store or resume mechanism.

Track provider surface explicitly when observable.

Support only verified surfaces in the primary release.

## 7.4 New sessions, resumes, and forks

A native resume should retain the existing session record when the provider preserves its session ID.

A native fork should create a new session record.

Fork lineage should be recorded only when supported by reliable metadata.

A fork may be proposed for association with its parent's workflow, but the module must not silently treat all forks as belonging to the same workflow if conflicting evidence exists.

## 7.5 Native resume safety

The resume dispatcher must:

- Resolve the correct provider and runtime environment.
- Resolve the full native session ID.
- Check whether the session is still available when possible.
- Preserve the original native working directory when necessary.
- Construct commands as argument arrays rather than concatenated shell strings.
- Quote paths correctly for PowerShell and WSL.
- Avoid ambiguous automatic selection.
- Require `--apply` before launching a process.
- Provide a verified manual command if programmatic resumption is unsupported.

A query may display a suggested resume command without executing it.

---

# 8. Event Storage and Windows/WSL2 Coordination

## 8.1 Design objective

Support concurrent native sessions across Windows and WSL2 without allowing both environments to write directly to one shared SQLite database.

The system should be local-first, recoverable, and operational without a resident daemon.

## 8.2 Durable event source

Use append-only or immutable event records as the authoritative history for registry mutations.

Events must cover both:

**Observed events**

- Session started.
- Session resumed or seen.
- Prompt submitted.
- Assistant turn completed.
- Workflow tag observed.
- Native metadata updated.

**User-authorized events**

- Workflow registered or updated.
- GUI conversation associated.
- Session manually linked or unlinked.
- Candidate rejected.
- Association conflict resolved.
- Session marked abandoned.
- Checkpoint explicitly validated.

This is essential.

If manual links or checkpoint decisions exist only inside SQLite, deleting SQLite cannot reconstruct the full registry.

## 8.3 Environment-isolated persistence

The provisional strategy is:

- Windows hooks write to Windows-owned event storage.
- WSL2 hooks write to WSL-owned event storage.
- A designated materializer reads both streams.
- Only one runtime owns writes to the authoritative SQLite index.

The precise event transport must be selected in Phase 0.

Candidate approaches include:

1. Per-environment append-only JSONL spools.
2. Per-process or per-session spool files.
3. Immutable per-event JSON files with atomic rename.
4. Environment-local spools ingested through a controlled cross-OS bridge.

A single shared JSONL file is not automatically safe merely because SQLite has been removed from the hot path.

Concurrent hooks within the same operating system can still interleave writes or leave partial records.

## 8.4 Recommended initial transport

Prefer **environment-isolated, single-writer or atomic-record event persistence**.

For example:

```text
Windows:
  local event spool
  native Windows filesystem

WSL2:
  local event spool
  native WSL filesystem

Materializer:
  reads/imports environment spools
  writes one authoritative SQLite index
```

A Windows-readable WSL spool under `/mnt/c/` may be used if local testing confirms acceptable durability, atomicity, and performance.

Do not assume that cross-filesystem rename, locking, or append behavior is identical across NTFS and WSL2 filesystem boundaries.

## 8.5 SQLite materialization

SQLite is the preferred query index, subject to repository and filesystem verification.

The materializer must support:

- Transactional event ingestion.
- Idempotent replay.
- Stable event IDs.
- Incremental cursors.
- Schema migrations.
- Corrupt or partial record detection.
- Crash recovery.
- Duplicate suppression.
- Safe rebuild from durable event sources.

Only the designated writer may modify the authoritative SQLite database.

If `agents` is invoked inside WSL, it must use a verified access mechanism rather than opening the same Windows-owned SQLite file for writes over `/mnt/c/`.

## 8.6 Rebuild guarantee

The registry should be reconstructible from:

- Workflow registration events.
- GUI reference events.
- Native session events.
- Association decisions.
- User status changes.
- Checkpoint events.

Optional snapshots may accelerate replay.

The rebuild guarantee must be tested, including preservation of manual decisions.

## 8.7 Hook execution constraints

Hooks should perform the minimum necessary work:

1. Read a bounded input payload.
2. Extract identifiers and supported metadata.
3. Create a normalized event.
4. Persist the event safely.
5. Exit without disrupting the provider.

Avoid on the critical path:

- Git subprocesses where they materially increase latency.
- Full transcript reads.
- SQLite migrations.
- Provider discovery scans.
- Semantic similarity calculations.
- Network requests.

Git enrichment can be deferred to lookup or background-free on-demand processing.

A hook should fail open when telemetry cannot be persisted, subject to the provider's verified hook contract.

---

# 9. Association Engine

## 9.1 Evidence hierarchy

Use discrete evidence levels rather than uncalibrated probabilities.

| Level | Evidence | Treatment |
|---|---|---|
| Confirmed | Explicit user association or approval | Authoritative unless subsequently changed |
| Strong | Valid workflow marker, verified launch linkage, exact registered identity, trusted inherited session binding | Automatic association if no conflict |
| Candidate | Partial content match, contextual correlation, branch/timestamp similarity | Requires confirmation |
| Unknown | Insufficient evidence | Remains unassociated |
| Rejected | User-rejected candidate | Suppressed unless materially new evidence appears |

## 9.2 Association precedence

Recommended precedence:

1. Explicit user confirmation.
2. Direct workflow marker in the current turn.
3. Verified existing session association.
4. Verified fork or launch linkage.
5. Exact registered handoff fingerprint.
6. Heuristic candidates.

Higher-priority conflicting evidence must trigger review rather than silently overwriting the existing relationship.

## 9.3 Session-level and turn-level association

A critical edge case is **reusing one native session for a different GUI workflow**.

The implementation must distinguish:

- A session's historical workflow associations.
- The workflow associated with a particular turn.
- The currently active workflow binding, if unambiguous.

If a session already linked to Workflow A receives a valid marker for Workflow B:

1. Preserve the historical Workflow A association.
2. Record the new marker as evidence for Workflow B.
3. Flag an association transition or conflict.
4. Stop blindly inheriting Workflow A for subsequent turns.
5. Require explicit confirmation when the intended transition is ambiguous.

A native session may therefore have multiple workflow associations over time.

The data model must support this rather than enforcing an unconditional one-session-to-one-workflow relationship.

## 9.4 Session lineage inheritance

When a session has an unambiguous active workflow association, subsequent untagged turns may inherit that association.

This supports normal native resumption without repeated tagging.

Inheritance stops or becomes provisional when:

- A different workflow marker appears.
- The user explicitly changes the association.
- The session is forked into an uncertain context.
- Evidence indicates repurposing.
- Conflicting strong evidence exists.

## 9.5 Heuristic matching

Historical and untagged sessions may use:

- Exact normalized handoff hashes.
- Distinctive prompt excerpts.
- Lexical similarity.
- Session titles.
- Working directories.
- Git branch metadata.
- Temporal proximity.

Repository identity and recency are supporting evidence only.

Semantic similarity should not be required for the MVP.

## 9.6 Confidence presentation

Do not display arbitrary values such as `0.98` as though they were calibrated probabilities.

Initial output should show:

```text
Association: Candidate
Evidence:
  - Distinctive handoff excerpt matched
  - Repository matches
  - Session activity occurred near handoff date
Action:
  Confirmation required
```

Numeric ranking may be added after evaluation against a labeled historical dataset.

---

# 10. Continuity and Progress Semantics

The module must avoid presenting one ambiguous "latest session" value as authoritative.

## 10.1 Required continuity queries

| Query | Meaning |
|---|---|
| Latest created | Newest native session created for the workflow |
| Latest seen | Most recently observed session startup or resume |
| Latest turn | Most recent session with a submitted or completed turn |
| Latest by provider | Most recent relevant session separately for Codex and AGY |
| Latest completed turn | Most recent session with an observed completed assistant turn |
| Latest reported summary | Most recent session with an identified agent completion report |
| Latest validated checkpoint | Most recent checkpoint with recorded validation evidence |

## 10.2 Important distinctions

A session startup is not a completed turn.

A completed assistant turn is not necessarily a handoff completion summary.

An agent-generated summary is not proof that the user copied it into ChatGPT.

A Git commit is not proof that tests passed.

A clean working tree is not proof that the implementation was accepted.

A recent session is not necessarily the correct session to resume.

These distinctions must be reflected in both the schema and CLI output.

## 10.3 Summary tracking

Provider `Stop` hooks can establish that an assistant turn completed when their semantics are verified.

They must not automatically classify every completed turn as an implementation summary.

Summary identification may initially require:

- Explicit user marking.
- A recognized structured completion report.
- A later verified summary-detection rule.

Store only a bounded preview by default, with an option to disable preview storage.

## 10.4 Validated checkpoints

A validated checkpoint must include sufficient evidence to support the claim.

Suggested fields:

- Repository identity.
- Commit SHA.
- Branch or worktree identity.
- Validation command or procedure.
- Actual exit code.
- Validation log or stable artifact reference.
- Validation timestamp.
- Evidence source.
- User acceptance status, if applicable.

The system must distinguish:

- Observed commit.
- Agent-reported validation.
- Executed and recorded validation.
- User-accepted checkpoint.

A user-supplied exit code must be labeled as user-reported unless independently verified.

## 10.5 Resume recommendation

The CLI may suggest a resume target based on recent relevant work.

However, when multiple sessions have conflicting branches, incomplete work, or uncertain associations, the CLI should present choices rather than claiming a uniquely correct answer.

Example:

```text
Suggested by recent activity: AGY A2
Latest validated checkpoint: Codex C3

These are different sessions.
Review branch and checkpoint state before resuming.
```

---

# 11. Data Model

The following schema is conceptual and should be finalized after Phase 0.

## 11.1 Core tables

| Table | Primary responsibility |
|---|---|
| `workflows` | Immutable workflow identity, slug, title, status |
| `gui_conversations` | ChatGPT URLs and workflow relationships |
| `environments` | Windows/WSL runtime identities |
| `sessions` | Native provider session identities and metadata |
| `turns` | Turn-level timestamps, markers, and associations |
| `associations` | Session/workflow relationships and evidence states |
| `association_evidence` | Provenance of each association decision |
| `activity_events` | Normalized native and user-generated events |
| `summaries` | Identified agent completion reports |
| `checkpoints` | Observed and validated Git/code checkpoints |
| `scan_state` | Incremental ingestion and recovery cursors |
| `provider_capabilities` | Observed provider versions and supported interfaces |
| `schema_metadata` | Database schema version and migration state |

## 11.2 Native session identity

Use a compound key:

```text
(provider, environment_id, native_session_id)
```

Do not assume native UUIDs are globally unique across providers or environments.

Environment IDs must remain stable across ordinary process restarts.

A distro name alone may not be sufficient if distributions are recreated or migrated.

## 11.3 Session metadata

Suggested fields:

```text
provider
environment_id
native_session_id
native_root_id
parent_session_id
surface
native_version
cwd_native
cwd_canonical
repository_identity
native_title
transcript_reference
created_at
first_observed_at
last_seen_at
last_turn_at
last_completed_turn_at
lifecycle_status
metadata_source
```

Unknown values must remain null or explicitly unavailable.

Do not substitute first-observed timestamps for native creation timestamps without labeling them.

## 11.4 Association records

Suggested fields:

```text
association_id
workflow_id
provider
environment_id
native_session_id
first_turn_id
last_turn_id
association_status
evidence_type
evidence_reference
confirmed_at
created_at
updated_at
```

The schema must support historical association transitions within a single native session.

## 11.5 Event records

Every durable event should include:

```text
event_id
event_schema_version
event_type
provider
environment_id
native_session_id
source_timestamp
observed_timestamp
source_adapter_version
payload
```

Events must be idempotent and replayable.

Sensitive raw hook payloads should not be persisted by default.

## 11.6 Storage minimization

Store by default:

- Identifiers.
- Timestamps.
- Association decisions.
- Evidence types.
- Prompt fingerprints where useful.
- Native metadata references.
- Minimal Git metadata.
- Optional bounded summaries.

Do not store by default:

- Complete prompts.
- Full transcripts.
- Clipboard histories.
- Authentication credentials.
- Browser cookies.
- Raw provider hook payloads.
- Sensitive environment variables.

Prompt fingerprints are correlation artifacts, not proof of content authenticity.

---

# 12. CLI and User Experience

## 12.1 Proposed command name

Use `agents` as the provisional CLI command.

Before finalizing, inspect the existing `scripts` repository for naming conflicts and established CLI conventions.

## 12.2 Core commands

| Command | Purpose |
|---|---|
| `agents wf add` | Register a GUI workflow |
| `agents wf list` | List workflows |
| `agents wf show` | Show workflow metadata |
| `agents wf archive` | Archive a workflow |
| `agents find` | Find associated sessions |
| `agents resume` | Preview or invoke native resumption |
| `agents inbox` | Review unlinked or ambiguous sessions |
| `agents link` | Confirm a session association |
| `agents unlink` | Remove or supersede an association |
| `agents status` | Mark session lifecycle status |
| `agents recover` | Recover historical sessions |
| `agents checkpoint` | Record checkpoint evidence |
| `agents doctor` | Diagnose integrations and storage |
| `agents rebuild` | Rebuild the materialized index |

## 12.3 CLI conventions

Provide short and long flags:

```text
-w, --workflow
-p, --provider
-s, --session-id
-e, --environment
-u, --url
-t, --title
-f, --file-path
-j, --json
-a, --apply
```

Mutating user commands must default to dry-run.

Read-only commands may refresh a local derived index after installation has been authorized, but must not modify native provider data.

Machine-readable output should use a stable documented JSON schema.

Errors must return meaningful nonzero exit codes.

## 12.4 Registration example

```powershell
agents wf add `
    -w procwatch `
    -t "ProcWatch Development" `
    -u "https://chatgpt.com/c/<conversation-uuid>" `
    -a
```

The command registers the workflow and returns the immutable workflow identifier.

It also provides the one-line handoff instruction.

## 12.5 Normal daily usage

The user continues to launch agents normally:

```powershell
codex
```

Or:

```powershell
agy
```

The user can resume sessions using the native provider interface.

No wrapper is required.

## 12.6 Lookup example

```powershell
agents find -w procwatch
```

Illustrative output:

```text
Workflow: ProcWatch Development
Workflow ID: wf_7d3a92

ChatGPT:
  https://chatgpt.com/c/<conversation-uuid>

ASSOCIATED SESSIONS

Provider  Environment   Session    Association  Last Turn
AGY       WSL Ubuntu    A2         Strong       2h ago
Codex     Windows       C3         Confirmed    1d ago
AGY       Windows       A1         Strong       3d ago
Codex     WSL Ubuntu    C1         Confirmed    5d ago

LATEST ACTIVITY
  AGY A2

LATEST COMPLETED TURN
  AGY A2

LATEST VALIDATED CHECKPOINT
  Codex C3

RESUME OPTIONS
  AGY A2:   <verified native command>
  Codex C3: <verified native command>

Warning:
  Latest activity and latest validated checkpoint differ.
```

The implementation must display actual native IDs and verified commands, not illustrative placeholders.

## 12.7 Ambiguity resolution

```powershell
agents inbox
```

Example:

```text
Unlinked session:
  Provider: Codex
  Session: C8
  Repository: scripts

Possible workflows:
  scripts-modernization
  wsl-monitor

Evidence:
  Shared repository
  Similar timestamps

Status:
  Candidate only

No association has been created.
```

The user may then explicitly link the session.

## 12.8 Failure taxonomy

Use structured errors such as:

```text
provider_unavailable
provider_version_unsupported
hooks_missing
hooks_untrusted
hook_schema_mismatch
metadata_inaccessible
session_not_found
session_orphaned
association_unknown
association_conflict
resume_unsupported
event_spool_unavailable
materializer_failed
registry_rebuild_required
cross_environment_unavailable
```

An unavailable provider must not be reported as proof that no sessions exist.

---

# 13. Historical Recovery

## 13.1 Objective

Recover associations for sessions created before installation without repeatedly requiring another coding agent to search all native histories.

Historical recovery is important, but it must remain isolated from the normal lookup path.

## 13.2 Recovery strategy

Use a five-stage cascade.

### Stage 1 — Explicit workflow markers

Search supported metadata or bounded transcript content for recognized workflow identifiers.

A valid marker provides strong association evidence.

### Stage 2 — Exact handoff fingerprint

Compare normalized handoff content with available native prompt records.

An exact match provides strong evidence, subject to collision and reuse checks.

### Stage 3 — Distinctive excerpt matching

Search for sufficiently distinctive portions of the supplied handoff.

Produce candidates rather than confirmed links.

### Stage 4 — Contextual matching

Combine:

- Lexical similarity.
- Session dates.
- Repository paths.
- Git branch metadata.
- Native titles.
- Other independent evidence.

Require confirmation.

### Stage 5 — Unmatched reporting

Report sessions that cannot be matched.

Do not manufacture associations.

## 13.3 Resource constraints

Recovery must:

- Use read-only native access.
- Prefer lightweight metadata indexes.
- Avoid full rollout deserialization.
- Enforce byte, time, and memory budgets.
- Support cancellation.
- Handle corrupt or missing records.
- Handle archived sessions.
- Handle compressed transcripts safely.
- Preserve scan cursors.
- Support incremental re-execution.

Large or inaccessible sessions should be skipped with explicit diagnostics unless the user authorizes deeper inspection.

## 13.4 Recovery example

```powershell
agents recover `
    -w procwatch `
    -f ".\handoff.txt"
```

Default behavior is analysis-only.

Any persistent linking requires explicit approval.

## 13.5 Recovery acceptance criteria

The system must demonstrate:

- No silently confirmed heuristic matches.
- Idempotent repeated scans.
- Bounded resource usage.
- Correct handling of missing/corrupt histories.
- Preservation of manual decisions.
- Clear reporting of unmatched sessions.

Recovery percentage and runtime targets should be established against the user's actual history after a baseline measurement.

Do not promise an arbitrary recovery rate before evaluating the available records.

---

# 14. Implementation Roadmap

The implementation should proceed through gated milestones.

Each phase must produce a validated checkpoint before dependent work begins.

## Phase 0 — Capability Verification and Repository Audit

**Type:** Read-only investigation, except explicitly authorized temporary instrumentation  
**Priority:** Mandatory prerequisite  
**Objective:** Replace research assumptions with verified local facts.

### Tasks

1. Inspect installed Codex and AGY executables on Windows and WSL2.
2. Record versions and installation paths.
3. Inspect existing hook configuration without overwriting it.
4. Verify documented hook support for installed versions.
5. Capture sanitized examples of relevant hook payloads.
6. Test one new and one resumed session per provider/runtime where practical.
7. Verify native resume command behavior.
8. Inspect native session storage formats read-only.
9. Measure history size and identify oversized rollouts.
10. Inspect `scripts` and `ai-orchestrator` repository structure.
11. Check active branches, worktrees, assignments, and dirty state.
12. Identify existing CLI, SQLite, path, telemetry, and validation utilities.
13. Test Windows/WSL event transport assumptions.
14. Select implementation ownership and canonical SQLite writer.
15. Produce architecture decision records.

### Security requirements

Temporary hook instrumentation may capture sensitive prompt data.

Use minimal test prompts, restrictive file permissions, and short retention.

Do not collect or publish raw authentication data or unrelated transcripts.

Remove temporary instrumentation after verification.

### Deliverables

- Local capability matrix.
- Provider version inventory.
- Sanitized hook fixtures.
- Native resume verification.
- Repository audit.
- Event transport decision.
- Storage ownership decision.
- Architecture decision record.
- Updated interface contracts.

### Exit gate

No provider-specific implementation proceeds until the relevant hook and resume behavior is verified or explicitly marked unsupported.

---

## Phase 1 — Registry, Manual Continuity, and Durable Event Foundation

**Milestone:** M1  
**Objective:** Deliver an independently useful system before relying on native hooks.

### Implementation

1. Workflow identity and registration.
2. GUI conversation reference management.
3. Environment identities.
4. Provider-neutral session records.
5. Manual association and unlinking.
6. Association provenance.
7. Durable event persistence.
8. SQLite materialization.
9. Schema migrations.
10. Replay and rebuild support.
11. Core continuity queries.
12. Basic CLI and JSON output.
13. Dry-run mutation controls.
14. Unit and integration tests.

### Required CLI

```text
agents wf add
agents wf list
agents wf show
agents find
agents link
agents unlink
agents inbox
agents rebuild
```

### Acceptance tests

- Two workflows share one repository without association leakage.
- One workflow contains multiple provider sessions.
- Windows and WSL environment identities remain distinct.
- Manual linking and unlinking survive restart.
- A rebuilt SQLite index preserves all user decisions.
- Repeated event ingestion creates no duplicate records.
- Mutating commands preview changes without `--apply`.
- Structured JSON output remains stable.

### Exit gate

A user can register a GUI workflow, associate native sessions manually, and reliably find them.

This is the first usable release.

---

## Phase 2 — Native Provider Discovery and Automatic Association

**Milestone:** M2  
**Objective:** Remove routine manual linking for tagged handoffs while preserving native agent workflows.

### Implementation

1. Stable hook entrypoint.
2. Codex adapter.
3. AGY adapter.
4. Provider capability detection.
5. Normalized native event schema.
6. Session ID extraction.
7. New/resumed session observation.
8. Workflow marker parser.
9. Strong association rules.
10. Session lineage inheritance.
11. Turn-level association tracking.
12. Conflict detection.
13. Fork relationship handling where supported.
14. Native resume command resolution.
15. Hook installation and rollback tooling.
16. Hook health diagnostics.

### Dependency order

The normalized event schema and storage contract must be stable before parallelizing provider adapter work.

Codex and AGY adapters may then be developed in separate worktrees.

The association engine should remain independently owned to avoid conflicting changes.

### Hook installation rules

Installation must:

- Require explicit `--apply`.
- Back up existing configuration.
- Preserve unrelated hooks and settings.
- Validate generated configuration.
- Avoid duplicate hook registration.
- Provide uninstall/rollback.
- Never silently overwrite user configuration.

### Acceptance tests

- Tagged Codex handoff associates correctly.
- Tagged AGY handoff associates correctly.
- Native resumes preserve existing associations.
- Untagged follow-up turns inherit only unambiguous associations.
- A different workflow marker creates a conflict/transition rather than silent reassignment.
- Two GUI workflows in one repository remain distinct.
- Forked sessions are represented separately.
- Hook failures do not block coding-agent execution.
- Hook event replay is idempotent.
- Cross-OS ingestion does not create unsafe SQLite writes.
- Resume commands target the correct provider and environment.

### Exit gate

Routine tagged handoffs are associated automatically, and native sessions can be looked up and resumed without manual history searches.

---

## Phase 3 — Historical Recovery and Evidence-Aware Progress

**Milestone:** M3  
**Objective:** Recover existing histories and distinguish implementation progress from simple activity.

### Implementation

1. Codex read-only recovery adapter.
2. AGY read-only recovery adapter.
3. Bounded metadata scanning.
4. Exact handoff fingerprint matching.
5. Distinctive excerpt matching.
6. Contextual candidate ranking.
7. Interactive recovery review.
8. Persistent rejection decisions.
9. Recovery cursors and resumability.
10. Completed-turn tracking.
11. Explicit summary references.
12. Git metadata enrichment.
13. Checkpoint validation records.
14. Branch divergence warnings.
15. Distinct continuity pointers.

### Acceptance tests

- Historical sessions are imported without modifying native files.
- Exact workflow markers produce strong evidence.
- Weak matches remain candidates.
- Rejected candidates remain rejected.
- Oversized transcripts do not exhaust memory.
- Missing/zero-byte records are handled.
- Summary tracking is distinct from turn completion.
- Observed commits are distinct from validated checkpoints.
- Latest activity and latest validated checkpoint may correctly refer to different sessions.
- Historical import is idempotent.

### Exit gate

The module provides meaningful continuity across both new and pre-install sessions, with trustworthy progress semantics.

---

## Phase 4 — Diagnostics, Ergonomics, and Hardening

**Milestone:** M4  
**Objective:** Improve operational reliability and reduce troubleshooting effort.

### Optional and conditional implementation

1. AGY status-line enrichment.
2. Provider-version compatibility diagnostics.
3. Hook trust and installation checks.
4. Session index consistency checks.
5. Storage size warnings.
6. Event transport health checks.
7. Registry backup and restore commands.
8. Rebuild verification.
9. Optional managed launcher.
10. Optional provider-specific resume shortcuts.
11. Performance profiling.
12. Documentation and operational runbooks.

### Acceptance tests

- Provider hook failures are diagnosed accurately.
- Unsupported capabilities are reported explicitly.
- Registry corruption can be recovered without losing durable decisions.
- Native configuration can be restored.
- Performance remains acceptable with large histories.
- Optional components can be disabled without breaking the core.

### Exit gate

The module is maintainable across routine provider updates and runtime failures.

---

## Phase 5 — Optional Orchestrator Integration

**Milestone:** M5 — Future scope  
**Objective:** Expose continuity information to existing orchestration systems.

Potential capabilities:

- Python library API.
- Structured JSON contracts.
- Workflow-to-session routing.
- Agent completion report references.
- Provider-specific headless continuation.
- Integration with `ai-orchestrator`.
- Future handoff dispatch.

This phase must not be required for M1–M4.

Programmatic interaction with consumer ChatGPT GUI conversations remains a separate research and engineering problem.

---

# 15. Testing and Validation

## 15.1 Unit tests

Cover:

- Workflow ID generation.
- Slug uniqueness and alias resolution.
- GUI URL normalization.
- Provider/environment session keys.
- Marker parsing.
- Quoted-marker rejection.
- Evidence precedence.
- Association conflicts.
- Session transitions.
- Turn-level lineage.
- Event idempotency.
- Event replay.
- Partial/corrupt records.
- Schema migrations.
- Timestamp ordering.
- Checkpoint evidence states.
- Resume command construction.
- Cross-platform path normalization.

## 15.2 Integration tests

Cover:

- New native session.
- Native resume.
- Fork.
- Provider switch.
- Shared repository.
- Concurrent workflows.
- Unavailable hooks.
- Malformed hook payloads.
- Existing hook configuration.
- Hook rollback.
- Interrupted event writes.
- Concurrent event writers.
- Windows/WSL ingestion.
- Deleted materialized database.
- Historical recovery.
- Missing transcripts.
- Oversized rollouts.
- Compressed transcripts.
- Archived sessions.
- Unsupported provider version.

## 15.3 Performance targets

Targets are provisional and must be measured.

Suggested objectives:

- Routine warm-index lookup: approximately two seconds or less for 10,000 indexed sessions.
- Hook execution: minimize critical-path latency; establish a measured p95 budget during Phase 0.
- No full transcript parsing during routine lookup.
- Bounded recovery memory and I/O.
- No idle background process required.
- No coding-agent failures caused by telemetry errors.

A universal sub-50-ms Python hook target should not be treated as guaranteed, especially on Windows or when subprocesses are involved.

## 15.4 Validation artifacts

Each substantial implementation phase must report:

- Repository.
- Branch/worktree.
- Commit SHA.
- Changed files.
- Tests executed.
- Exit codes.
- Relevant logs.
- Environment details.
- Provider versions.
- Known limitations.
- Remaining uncertainties.
- Integration readiness.

Tests must not be described as passing without execution evidence.

---

# 16. Repository and Agent Workflow

## 16.1 Repository selection

The `scripts` repository is the preferred candidate, not an approved fact.

Phase 0 must compare:

- Existing package structure.
- CLI framework.
- Python dependencies.
- SQLite utilities.
- Cross-platform helpers.
- Logging and telemetry.
- Testing infrastructure.
- Current active development.

`ai-orchestrator` should initially consume the module through a clean interface rather than duplicating session-tracking logic.

## 16.2 Worktree and branch discipline

Before implementation:

1. Inspect active assignments.
2. Inspect Git status and worktrees.
3. Identify validated checkpoints.
4. Avoid interfering with active agent branches.
5. Select an isolated implementation branch.
6. Preserve uncommitted work.
7. Avoid automatic merges.

## 16.3 Parallel work

Parallelize only after shared interfaces are stable.

Suitable independent workstreams include:

- Codex provider adapter.
- AGY provider adapter.
- Historical recovery adapter.
- CLI documentation and fixtures.

Core schema changes and association semantics should have a single owner during each implementation stage.

## 16.4 Completion workflow

Agents should:

1. Plan bounded changes.
2. Implement within assigned ownership.
3. Add tests.
4. Run available validation.
5. Review diffs.
6. Update documentation.
7. Commit changes.
8. Produce a completion report.

Local validation and integration approval remain separate from agent self-reporting.

---

# 17. Security, Privacy, and Reliability

## 17.1 Least privilege

Use local-only processing wherever possible.

Do not introduce:

- Cloud transcript uploads.
- Browser cookie access.
- Persistent clipboard monitoring.
- Unnecessary network listeners.
- Automatic credential collection.

## 17.2 Provider configuration

Hook installation must be reversible and explicitly authorized.

Native provider session stores remain read-only.

## 17.3 Sensitive content

Avoid storing raw prompts or transcripts.

Temporary diagnostic captures must be minimized, access-restricted, and removed when no longer required.

Summary previews may contain sensitive information and must be optional.

## 17.4 Data integrity

Provide:

- Durable event IDs.
- Transactional materialization.
- Schema migrations.
- Replay validation.
- Backup/restore.
- Corruption detection.
- Idempotent recovery.
- Safe partial-event handling.

## 17.5 Failure isolation

A failed provider adapter must not:

- Block an agent turn.
- Delete registry associations.
- Corrupt the event store.
- Cause unrelated providers to fail.
- Present stale data as fresh.

CLI output should report when data was last successfully observed.

---

# 18. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Installed Codex hooks differ from research | High | Phase 0 capability verification |
| Installed AGY hooks differ from research | High | Phase 0 capability verification |
| Native session storage changes | Medium–High | Isolated adapters and read-only fallback |
| Hook trust resets | Medium | Stable entrypoint, diagnostics, explicit reapproval |
| Hook stdout changes provider behavior | High | Verify exact event contract; avoid unsafe hook types |
| Concurrent spool writes corrupt records | High | Single-writer or atomic-record persistence |
| Cross-OS SQLite locking | High | One designated SQLite writer |
| Manual associations lost during rebuild | High | Persist all decisions in durable events |
| Reused session changes workflow | High | Turn-level associations and conflict handling |
| Fork inherits wrong workflow | Medium | Verified lineage plus conflict checks |
| Tag missing from handoff | Medium | Unlinked inbox and manual fallback |
| Tag copied into unrelated prompt | Medium | Parser validation and conflict checks |
| Large native rollouts | High | Bounded, on-demand recovery |
| Native session indexes desynchronize | Medium | Multiple metadata sources, explicit uncertainty |
| AGY CLI/Desktop/IDE store separation | Medium | Surface-aware identities and supported-surface scope |
| Summary mistaken for validation | High | Separate completion, report, and checkpoint states |
| Repository changes during implementation | Medium | Worktree isolation and validation checkpoints |
| Sensitive prompt retention | High | Metadata-only storage and sanitized diagnostics |

---

# 19. Architecture Decision Gates

## Gate A — Provider integration

Are native hooks reliable enough to serve as the primary discovery mechanism on the installed versions?

If yes, use hooks.

If not, select a documented alternative or bounded passive fallback.

## Gate B — Workflow attribution

Can the installed provider integration observe a workflow marker without expensive transcript parsing?

If yes, use direct marker extraction.

If not, use bounded targeted transcript access or manual linking.

## Gate C — Event transport

Which event persistence mechanism provides safe concurrent writes and reliable Windows/WSL ingestion?

Select based on measured behavior.

Do not assume a shared JSONL file is atomic.

## Gate D — Registry ownership

Which runtime owns SQLite writes?

Choose one authoritative writer and define the cross-environment query/ingestion contract.

## Gate E — Repository ownership

Does `scripts` already provide the necessary package and CLI infrastructure?

If yes, integrate there.

If not, document the reason for an alternative package boundary.

## Gate F — Historical recovery depth

What proportion of existing histories is accessible through lightweight metadata?

Use actual measurements to determine whether deeper scanning is worthwhile.

## Gate G — Optional enrichment

Does status-line telemetry, managed launching, or browser assistance provide enough demonstrated benefit to justify additional complexity?

Defer otherwise.

---

# 20. Milestone Acceptance Summary

| Milestone | Required outcome |
|---|---|
| M0 — Verified architecture | Provider capabilities and repository integration points confirmed |
| M1 — Manual registry | Reliable GUI workflow registration, linking, lookup, and rebuild |
| M2 — Native continuity | Automatic discovery and strong association for supported tagged sessions |
| M3 — Historical/evidence-aware | Safe recovery, ambiguity handling, summary/checkpoint separation |
| M4 — Hardened module | Diagnostics, recovery, compatibility, and operational reliability |
| M5 — Optional integration | Clean interfaces for future orchestration |

The first major practical success criterion is achieved at **M2**:

> The user can return to an existing ChatGPT GUI workflow, run one lookup command, and identify the relevant Codex and AGY sessions without manually searching their histories.

M3 expands this capability to sessions created before installation.

---

# 21. Definition of Done

The primary module is complete when:

1. GUI workflows have stable local identities.
2. Multiple GUI conversations can be explicitly associated with one workflow.
3. Multiple native sessions can belong to one workflow.
4. Multiple workflows can use the same repository without cross-contamination.
5. Codex and AGY integrations work on the locally verified supported versions.
6. New and resumed sessions are observed wherever supported.
7. Tagged handoffs establish strong workflow associations.
8. Untagged turns inherit associations only when unambiguous.
9. Session repurposing and fork conflicts are handled safely.
10. Windows and WSL2 environments remain independently identifiable.
11. No unsafe shared SQLite writes occur.
12. Durable events preserve manual decisions and permit registry rebuild.
13. Historical recovery operates within bounded resources.
14. Weak matches never become confirmed automatically.
15. Activity, completed turns, summaries, and validated checkpoints are distinct.
16. Native resume operations use verified provider interfaces.
17. The module remains usable when hooks or native metadata are unavailable.
18. Provider configuration changes are reversible.
19. Security and data-minimization requirements are satisfied.
20. Unit tests, integration tests, documentation, and validation evidence are complete.

---

# 22. Immediate Execution Sequence

## Step 1 — Phase 0 research-to-environment reconciliation

Inspect installed Codex and AGY capabilities on Windows and WSL2.

Compare them against the supplied research.

Record discrepancies.

## Step 2 — Repository audit

Inspect `scripts` and `ai-orchestrator`, including active worktrees and validated checkpoints.

Confirm implementation ownership.

## Step 3 — Finalize interface contracts

Lock down:

- Workflow ID format.
- Event schema.
- Provider adapter interface.
- Event transport.
- SQLite writer ownership.
- Association precedence.
- CLI naming and output contracts.

## Step 4 — Publish Master Plan v3.1

Update this document with Phase 0 findings.

Do not rewrite the architecture without an evidence-backed decision.

## Step 5 — Produce Phase 1 implementation handoff

Create a self-contained agent assignment specifying:

- Repository and worktree.
- Verified current state.
- Exact scope.
- Interfaces.
- Implementation stages.
- Tests.
- Validation commands.
- Commit and reporting requirements.

## Step 6 — Deliver M1

Implement and validate the manual registry and durable event foundation.

## Step 7 — Deliver M2

Implement native provider discovery and automatic workflow association.

## Step 8 — Deliver M3

Add historical recovery and evidence-aware progress tracking.

## Step 9 — Harden and integrate selectively

Complete diagnostics and only those optional integrations supported by demonstrated needs.

---

# 23. Final Architectural Position

The recommended system is a **local-first, hook-first session continuity registry with explicit workflow identity, durable event history, provider-independent associations, and bounded historical recovery**.

The system should not attempt to control every coding-agent session.

It should observe native sessions, establish trustworthy relationships to GUI workflows, preserve those relationships over time, and provide reliable lookup and resumption.

The architecture follows this progression:

**Workflow identity → durable registry → native discovery → automatic association → historical recovery → evidence-aware continuity → optional orchestration.**

Each layer must remain useful without requiring the next.

The guiding question for every implementation decision is:

> Does this change make it easier and more reliable to find the correct Codex or AGY conversation for a specific ChatGPT GUI workflow, without unnecessarily changing how the user already works?

If a proposed feature does not materially improve that outcome, it should remain outside the core module.

---

**End of Unified Master Implementation Plan — v3.0**
