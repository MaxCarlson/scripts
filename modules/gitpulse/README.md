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

Each subcommand exposes an abbreviated two-character form and a single-character quick alias for rapid typing.

| Command | Aliases | Description |
| ------- | ------- | ----------- |
| `sync` | `sy`, `s` | Shows `git status`, pulls from upstream, optionally commits staged files (with commit/skip/split choices), offers to stage unstaged files, and pushes. |
| `status-pull` | `sp`, `p` | Displays `git status`, then pulls remote updates. |
| `refresh` | `rf`, `r` | Executes `git fetch --all --prune` and prints a concise status view. |
| `stash-sync` | `ss`, `z` | Stashes pending work, pulls with rebase, then pops the stash. |
| `tag-sync` | `ts`, `t` | Fetches and prunes all remote tags. |
| `branch-report` | `br`, `b` | Fetches metadata and shows `git branch -vv` for ahead/behind inspection. |
| `rebase-update` | `ru`, `u` | Fetches everything and rebases the current branch onto `origin/<branch>`. |
| `clean-reset` | `cr`, `c` | Runs `git reset --hard HEAD` and `git clean -fd` (confirmation respected). |
| `log-graph` | `lg`, `l` | Renders `git log --graph --decorate --oneline --all` with a configurable limit. |
| `diff-back` | `db`, `d` | Shows the diff between `HEAD` and `HEAD~N`. |
| `smart-commit` | `sc`, `m` | Guides the user through staging (optional paths), reviewing, committing, and optionally syncing changes. |

### Smart Commit Workflow

`gk smart-commit` accepts:

- `-p/--paths`: Optional file paths to stage; otherwise everything is staged.
- `-m/--message`: Use a provided commit message; omit to let GitPulse suggest one based on the staged files.
- `-y/--yes`: Auto-accepts “proceed with commit”, message default, and post-commit pull/push prompts.

The command stages files, shows the user `git status`, asks if the commit should proceed, lets the user edit/accept the suggested message, performs the commit, then offers to `git pull` and `git push`.

### Sync Workflow

`gk s` (`gk sy` or `gk sync`) serves as the “sync everywhere” command for mirrored repos:

- Show `git status`, pull, and detect staged vs. unstaged files.
- Offer `[y]es/[n]o/[s]plit` for staged commits. Split commits the staged set first, then loops through the unstaged changes.
- If unstaged or untracked files remain, prompt to run `git add --all` and then (optionally) commit that newly staged set.
- Automatically generate commit messages grouped by modified/added/deleted filenames while still allowing manual overrides when `-y/--yes` is not supplied.

This keeps multiple clones synchronized with minimal keystrokes while still supporting deliberate split commits when staged and unstaged work need to be separated.

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
