# `ag` information display design

## Intent

Make `ag` useful as a quick lookup for the commands and shortcuts configured in this scripts environment. Keep the default results focused, readable, and descriptive; provide an explicit way to inspect the wider command inventory.

## Goals

- By default, search repo-registered commands and shell aliases/functions defined by user profiles or user-owned configuration modules. Exclude operating-system commands and executables from this curated view.
- Show `Name` and a concise `Help` description by default. Registered commands use their script or module summary; shell commands use available help synopsis or a concise fallback. Add explicit concise descriptions for the clipboard entry points.
- Add `-A/--all` to include the broader live shell inventory and PATH executables. Preserve `-x/--executables` as a way to add PATH executables to the existing results.
- Add `-D/--definitions` to append the current target/definition as an optional third column and allow matching that definition when requested.
- Use color by command kind/source for interactive table output. Respect `NO_COLOR`, avoid ANSI codes for JSON, and keep piped output plain.
- Preserve the existing `ag` command and JSON schema.

## Non-goals

- Do not invoke commands to collect their help at search time; the lookup must remain read-only and fast.
- Do not add a separate `fg` command, which would conflict with POSIX job-control `fg`.
- Do not change the external Silver Searcher collision warning or command registration lifecycle.

## Constraints

- Existing behavior reads the scripts command registry, live shell inventory, and optionally PATH executables. The live inventory currently mixes configured shortcuts with system/module functions, so adapters must distinguish curated entries from the broader inventory.
- The `CommandEntry` model already carries a description and a target; display should use these as Help and Definition respectively.
- `scripts-help` changes its default result set and table columns, so the package version and README version must reflect the breaking CLI output change.
- Add no runtime dependency for color; auto-color only when output is a terminal.

## Approaches

1. **One `ag` command with curated and all modes — selected.** Keep one search command, use the curated set by default, and add `-A/--all` for broad results. This matches the requested focused default while preserving a single command surface and the existing `-x/--executables` behavior.
2. **Separate `fg` full-search command.** This is easy to discover, but it adds another entry point and shadows the common POSIX foreground-job command. It is not selected.

## Decisions

- The default data set consists of repo-registered commands plus aliases/functions whose source path belongs to the user's profile, configuration, or project checkout.
- The all view also includes system-provided shell commands and PATH executables.
- Pattern matching uses names and help summaries in the default view. Raw definitions are displayed and searched only when `-D/--definitions` is present.
- Interactive color is automatic and disabled for JSON or non-terminal output; `NO_COLOR` disables it.

## Builder calls

- Determine shell-entry ownership from source paths/profile metadata in each adapter, with tests for user-configured and system-provided entries.
- Keep descriptions short enough for a terminal table and truncate the optional definition column to a bounded width.
- Update CLI help, README usage, package version, and focused tests alongside the implementation.
