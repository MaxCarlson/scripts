# Local Repository Fast-Forward Synchronization

Use [`pwsh/Sync-LocalRepos.ps1`](../pwsh/Sync-LocalRepos.ps1) to safely fast-forward local `main` checkouts against their remote `main` branches after approved PR merges.

## Default repositories

By default, the script inspects under `~/src` (`-Root`):

- `scripts`
- `llm-agent-toolkit`
- `shared-python-modules`

`scripts/pscripts` is a Git submodule controlled by `scripts` and is intentionally skipped if passed directly.

## One-command usage

```powershell
# Preview (default dry-run — never fetches or mutates refs/files)
pwsh -NoProfile -File .\pwsh\Sync-LocalRepos.ps1

# Apply --ff-only updates to all clean, eligible main checkouts
pwsh -NoProfile -File .\pwsh\Sync-LocalRepos.ps1 -Apply

# Machine-readable JSON output for agent/automation consumption
pwsh -NoProfile -File .\pwsh\Sync-LocalRepos.ps1 -a -j

# Target specific repositories or a custom root / JSON config
pwsh -NoProfile -File .\pwsh\Sync-LocalRepos.ps1 -r C:\Users\mcarls\src -p scripts,llm-agent-toolkit -a
pwsh -NoProfile -File .\pwsh\Sync-LocalRepos.ps1 -c .\repos.json -a -j
```

## Safety guarantees

- **Dry-run by default** (`-n` / `-DryRun`): does not run `git fetch` or modify refs/working trees; distinguishes confirmed clean fast-forwards (`would_fast_forward`) from dirty-tree fast-forwards pending Git's final safety check (`would_fast_forward_with_local_changes`).
- **`--ff-only` only** (`-a` / `-Apply`): never force-pulls, rebases, hard-resets, stashes, creates merge commits, switches branches, or repins submodules.
- **Compatible local changes preserved**: untracked files, non-conflicting tracked edits, and untracked submodule contents do not block a safe fast-forward; if `git merge --ff-only` reports an overwrite/conflict, the repository is skipped without destructive recovery and remaining changes are reported.

## Post-merge agent workflow

1. Merge an explicitly approved PR on GitHub.
2. Verify the merge commit on GitHub.
3. Invoke `pwsh -NoProfile -File pwsh/Sync-LocalRepos.ps1 -Apply -Json` locally (remote-only agents should delegate this step to an authorized local executor).
4. Report `updated`, `already_current`, `skipped`, and `failed` repositories from the JSON output.
