# Saved Game Archiver — Implementation Plan

## Goal

Build `modules/saved_game_archiver/` as the canonical all-games save protection and gameplay-history layer for the scripts repository. The system should automatically protect Steam and non-Steam games, retain logical save identities without conflating characters/profiles, record gameplay sessions/playtime, and expose useful terminal visualizations.

## Core invariants

1. **Logical identity is lossless.** A save file is identified by `game_id + source_id + relative_path`. Identical names or bytes never merge logical identities.
2. **Physical deduplication is safe.** SHA-256 blobs may be shared by any number of logical entries.
3. **No-change means no restore point.** Scheduled checks do not manufacture redundant history.
4. **Stable state indices never silently renumber.** Automated grouping is conservative and user-correctable.
5. **Every final session state is pinned.** An exit checkpoint may reuse an existing identical snapshot.
6. **Mutations preview by default.** CLI configuration/catalog/scheduler/export writes require `-y/--apply`.
7. **Session time is consistently recorded across stores.** Steam historical playtime is imported as a baseline/current reference; SGA process sessions supply cross-store tracking.
8. **Mid-write captures are avoided.** Running-game save events are settled/stability-checked before archiving.

## Stage ordering

### Stage 1 — Persistence and identity foundation

- JSON `config.json` for user-controlled persistent settings.
- JSON `catalog.json` for game identity, install roots, executables, save sources, state indices, playtime.
- Append-only JSONL `events.jsonl` for session/save/discovery/check history.
- Immutable JSON snapshot manifests and content-addressed SHA-256 blobs.

Acceptance:
- round-trip catalog/config;
- independent logical identities with deduplicated content;
- state index stability.

### Stage 2 — Installation/save/executable discovery

- Steam roots and `libraryfolders.vdf`.
- Steam `appmanifest_*.acf` game identity/install location.
- configurable game roots where direct child folders imply installed games.
- executable scoring and manual override.
- Ludusavi manifest with ETag cache, Steam ID/name lookup, placeholders, filesystem and registry sources.
- Steam userdata fallback.
- common-location and running-session write correlation for unresolved games.

Acceptance:
- Steam/root duplicate installs reconcile;
- games may persist as `discovered_no_save` before first launch;
- correlated save candidates require confidence threshold.

### Stage 3 — Session and playtime recorder

- process-path matcher against persistent executable candidates;
- observed processes reinforce candidates;
- session start/stop events;
- tracked runtime accumulation;
- Steam local `Playtime` import with no double counting;
- crash/restart recovery from append-only events.

Acceptance:
- start/end produces one session and correct duration;
- imported baseline + tracked time remains monotonic.

### Stage 4 — Change-driven archive

- enumerate each save source without flattening paths;
- per-entry stable state index, captured time, and playtime;
- content hashing only where metadata differs;
- no snapshot for unchanged logical content;
- deletion captured as historical state transition;
- safe original/friendly exports.

Friendly export prefix:

`GameName_STATEINDEX_YYYYMMDD-HHMMSS_PLAYTIME__OriginalStem.ext`

The suffix is necessary when one character/profile owns multiple simultaneous save files.

### Stage 5 — Running-game focus and exit retention

Default running rates: `change 15m`.

- watchdog events when available; polling signature fallback;
- settle multiple writes into one stable save transaction;
- capture every distinct stable in-session state;
- configurable additional periodic safety rates;
- retain in-session history by gameplay-cycle generation (`2` cycles default);
- final capture at process exit;
- pin last `10` exit checkpoints by default, reusing identical snapshots.

### Stage 6 — Normal retention and automation

- GFS changed-state syntax `24h 7d 4w 12m`;
- inactive-game maintenance checks;
- OS scheduler plan/reconciliation;
- Windows logon watcher + periodic maintenance tasks;
- Unix cron fallback;
- post-snapshot hooks for rclone/Restic/RRBackup/etc.

### Stage 7 — Statistics and visual history

- overview and per-game detail;
- independent backup-check vs restore-point timestamps;
- per-game save-state timeline;
- overall gameplay timeline using distinct row glyphs;
- total/daily playtime visualization;
- hour-of-day histogram and per-game breakdown;
- doctor audit for roots, executables, save discovery, archive references, sessions, scheduler.

### Stage 8 — Repository integration and validation

- package metadata and entry points `saved-game-archiver` / `sga`;
- TermDash live watcher dashboard;
- scripts-help registry entry;
- root `validation-targets.json` target;
- pytest + compile + Ruff + CLI help;
- Windows environment smoke script;
- optional production read-only Steam discovery;
- explicit acceptance validation before merge.

## Deferred/extension opportunities

These should not block the first merge but fit the data model:

- calendar heatmap similar to GitHub contribution graphs;
- session-length distribution and rolling averages;
- save-frequency vs playtime graph (detect games with unusually sparse checkpoints);
- per-character share of playtime where save-state attribution can be inferred confidently;
- storage growth and deduplication-efficiency timeline;
- gap visualization showing periods where a game was played but no save data could be resolved;
- optional local web dashboard consuming the same JSON/JSONL history.
