# GitPulse (`gk`)

GitPulse is a convenience CLI that bundles common multi-step git workflows into a single short command. It is designed for fast keyboard-driven work inside any repository across Windows, WSL2, and Termux.

## Installation

```bash
python -m pip install -e modules/gitpulse
```

Installing the module exposes the short command `gk` everywhere in your PATH.

## Global Flags

| Flag | Description |
| ---- | ----------- |
| `-R/--repo-path` | Run commands inside a different repository than the current directory. |
| `-n/--dry-run` | Print the git commands without executing them. Useful for previews in destructive flows. |
| `-y/--yes/--confirm` | Automatically answers “yes” to every confirmation prompt. |
| `-v/--verbose` | Enables debug logging for additional troubleshooting information. |

## Command Catalog

| Command | Description |
| ------- | ----------- |
| `sync` | Runs `git pull` followed by `git push` to fast-forward and publish the branch. |
| `status-pull` | Displays `git status`, then pulls remote updates. |
| `refresh` | Executes `git fetch --all --prune` and prints a concise status view. |
| `stash-sync` | Stashes pending work, pulls with rebase, then pops the stash. |
| `tag-sync` | Fetches and prunes all remote tags to keep local metadata clean. |
| `branch-report` | Fetches remote metadata and shows `git branch -vv` for quick review of ahead/behind status. |
| `rebase-update` | Fetches everything and optionally rebases the current branch onto its `origin/<branch>` counterpart. |
| `clean-reset` | Runs `git reset --hard HEAD` and `git clean -fd` after confirmation. |
| `log-graph` | Renders `git log --graph --decorate --oneline --all` with a configurable limit. |
| `diff-back` | Shows the diff between `HEAD` and `HEAD~N` for historical comparisons. |
| `smart-commit` | Guides the user through staging, confirming, committing, and optionally pulling/pushing changes. |

### Smart Commit Workflow

`gk smart-commit` accepts:

- `-p/--paths`: Optional file paths to stage; otherwise everything is staged.
- `-m/--message`: Use a provided commit message; omit to let GitPulse suggest one based on the staged files.
- `-y/--yes`: Auto-accepts “proceed with commit”, message default, and post-commit pull/push prompts.

The command stages files, shows the user `git status`, asks if the commit should proceed, lets the user edit/accept the suggested message, performs the commit, then offers to `git pull` and `git push`.

### Diff Helpers

`gk diff-back -c/--commit-count 3` prints the diff between the working tree and `HEAD~3`. This is handy for reviewing a feature’s evolution or spotting regressions introduced a few commits ago.

### Visual Log Graphs

`gk log-graph -l/--limit 200` renders a decorated commit graph with up to 200 commits, providing the nicest text-based view of branch merging history directly in the terminal.

## Error Handling

Every command executes the requested git steps sequentially and surfaces git’s exit codes immediately. Exceptions produce non-zero CLI exit statuses, keeping shell pipelines honest and surfacing real git errors directly to the user.

## Testing

```bash
pytest modules/gitpulse/tests/gitpulse_test.py -v
```

GitPulse ships with pytest-based coverage for its planning utilities. Additional mocks can be layered on top to extend coverage for custom workflows.
