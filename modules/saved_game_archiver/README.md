# Saved Game Archiver

`Saved Game Archiver` (SGA) discovers Steam and non-Steam games, resolves save locations, tracks gameplay sessions/playtime, and stores every **distinct stable save state** in a content-addressed archive.

The design intentionally separates:

- **game installation identity** from save-location identity;
- **logical save-file identity** (`game + source + relative path`) from physical blob deduplication;
- **backup checks** from **restore points created**;
- Steam-imported historical playtime from SGA-observed play sessions.

## Safety defaults

Mutating CLI operations preview by default. Use `-y` / `--apply` to write configuration, alter the catalog, install scheduler tasks, or export files.

The archive never creates a new restore point when the complete logical save state is unchanged. Files with identical bytes may share one SHA-256 blob while remaining independent manifest entries.

## Default policies

- Normal GFS retention: `24h 7d 4w 12m` = 24 hourly, 7 daily, 4 weekly, 12 monthly **changed states**.
- Running-game focus: `change 15m` = capture every stable write burst plus a 15-minute safety check.
- In-session retention: keep in-session snapshots from the latest 2 gameplay cycles.
- Exit checkpoints: keep the latest 10 final session states. If the final state already exists, it is pinned without duplicating save data.

## Discovery

SGA combines:

1. Steam libraries and `appmanifest_*.acf` files.
2. User-configured game roots; every new direct child directory becomes an installed-game candidate.
3. Executable scoring plus process observation and manual overrides.
4. The Ludusavi manifest for save paths and Windows registry keys.
5. Steam userdata/common save-path fallbacks.

Games may remain in `discovered_no_save` until their first launch creates save data.

## Persistent files

By default SGA stores state under the platform user-state directory:

- `config.json` — user settings, roots, schedule/retention, hooks.
- `catalog.json` — tracked games, executables, save sources, stable state indices, playtime.
- `events.jsonl` — append-only gameplay/save/checkpoint history.
- `archive/` — SHA-256 blobs plus immutable snapshot manifests.

The archive root may itself live in a Google Drive-synced directory. `hooks.post_snapshot` can invoke `rclone`, Restic/RRBackup, or another backup framework.

## CLI

```text
saved-game-archiver config ...
saved-game-archiver schedule ...
saved-game-archiver modify ...
saved-game-archiver stats ...
saved-game-archiver watch ...
saved-game-archiver run ...
```

Useful examples:

```powershell
sga config game-root add D:\Games --apply
sga modify scan --refresh-manifest --apply
sga schedule running --rates change 15m --keep-cycles 2 --exit-keep 10 --apply
sga schedule set --retention "24h 7d 4w 12m" --maintenance-interval 15m --apply
sga stats overview
sga stats timeline "Game Name"
sga stats all-timeline
sga stats playtime
sga stats hourly
sga stats doctor --scheduler
```

## Save-state indices and friendly export names

SGA assigns persistent logical save-state indices (`0`, `1`, ...) and never silently renumbers existing state keys. Directory-oriented games are naturally grouped by their character/profile directory. Flat/ambiguous save layouts default conservatively to separate state keys until corrected with `modify state set`.

Friendly exports use:

```text
GameName_STATEINDEX_YYYYMMDD-HHMMSS_PLAYTIME__OriginalStem.ext
```

The requested `game/index/date/time/playtime` prefix is therefore present, while the original stem prevents collisions when one character has many simultaneous save files.

## Local validation

The repository root validation dispatcher owns authoritative Windows checks:

```powershell
./Invoke-Tests.ps1 -Target saved-game-archiver
```

Windows acceptance should verify Steam library/playtime parsing, Task Scheduler integration, live process matching, Windows registry save export, watchdog behavior, and the TermDash watcher UI before merging the feature branch.
