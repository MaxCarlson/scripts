# Cross-Repository Setup

## Purpose

`development-ledger setup` configures another repository to use the shared planning, validation-history, and remote/local handoff system. The target repository does not need to contain a copy of this Python module, but the module must be installed or invoked from the `scripts` checkout when setup or ledger commands run.

## Safety model

- Setup is dry-run by default.
- `-w/--write` is required to modify the target.
- Existing instruction-file content is preserved.
- Only text between development-ledger managed markers is replaced on later runs.
- Existing user-maintained `docs/README.md`, `docs/HANDOFF.md`, and `docs/plans/README.md` files are never overwritten.
- Unmarked files at uniquely module-owned paths produce a conflict instead of being overwritten.
- `-f/--force` applies only to explicitly replaceable setup-owned files and configuration; malformed instruction markers still block setup.
- Scope paths must already exist, remain inside the target repository, and cannot contain `..`.

## Basic setup

Preview a root-only installation:

```powershell
python -m development_ledger setup -r C:\src\project
```

Apply it:

```powershell
python -m development_ledger setup -r C:\src\project -w
```

The default agent set is:

- Codex through `AGENTS.md`
- Claude Code through `CLAUDE.md`
- Gemini CLI through `GEMINI.md`
- GitHub Copilot through `.github/copilot-instructions.md`

`AGENTS.md` remains the canonical concise rule set even when Codex is not selected, because Claude, Gemini, and some Copilot environments can consume or import it.

## Independent planning scopes

A scope is a repository-relative directory whose adjacent `docs/` folder owns plans, handoffs, and ledger output for that subtree.

```powershell
python -m development_ledger setup `
    -r C:\src\project `
    -s apps/web `
    -s services/api `
    -w
```

This produces native scoped instruction files inside `apps/web/` and `services/api/`, plus their local `docs/` trees.

The root `docs/` area remains responsible for repository-wide work.

## Module convenience targeting

`-m/--module` expands one name to `modules/<name>`:

```powershell
python -m development_ledger setup -r C:\src\project -m backup -m viewer -w
```

`-A/--all-modules` discovers every immediate directory below `modules/`:

```powershell
python -m development_ledger setup -r C:\src\project -A -w
```

Module names must be single path segments. Use `--scope` for any other layout.

## Agent selection

Repeat `-a/--agent` to limit generated wrappers:

```powershell
python -m development_ledger setup -r C:\src\project -a codex -a claude -w
```

Supported values:

- `codex`
- `claude`
- `gemini`
- `copilot`

The configuration records the union of agents configured across setup runs; the installer does not automatically delete previously generated wrappers.

## Created repository topology

A root-only setup creates or manages:

```text
repo/
├── .development-ledger.json
├── AGENTS.md
├── CLAUDE.md                 # when selected
├── GEMINI.md                 # when selected
├── .github/
│   └── copilot-instructions.md
└── docs/
    ├── README.md
    ├── HANDOFF.md
    ├── agent/
    │   └── DEVELOPMENT_LEDGER_WORKFLOW.md
    └── plans/
        └── README.md
```

Each additional scope creates:

```text
scope/
├── AGENTS.md
├── CLAUDE.md                 # when selected
├── GEMINI.md                 # when selected
└── docs/
    ├── README.md
    ├── HANDOFF.md
    └── plans/
        └── README.md
```

Copilot path-specific files are stored centrally under `.github/instructions/` with an `applyTo` glob for each scope.

## Existing instruction files

When an instruction file already exists, setup appends this bounded region:

```markdown
<!-- development-ledger:managed-instructions:start -->
...
<!-- development-ledger:managed-instructions:end -->
```

Later setup runs replace only that region. Content before and after it is retained exactly except for final newline normalization.

If one marker is missing or duplicate marker blocks exist, setup reports a conflict and makes no changes.

## Instruction strategy

- `AGENTS.md` contains essential workflow and safety rules inline because Codex automatically scopes nested `AGENTS.md` files but does not document a general Markdown import syntax.
- `CLAUDE.md` imports the local `AGENTS.md` and shared workflow using Claude Code's documented `@path` imports.
- `GEMINI.md` uses Gemini CLI's documented `@path` imports and hierarchical context.
- Copilot instructions contain essential rules inline and add references where the Copilot environment supports them.

See `INSTRUCTION_DISCOVERY_RESEARCH.md` for sources and rationale.

## Configuration

`.development-ledger.json` records:

- repository name,
- configured agents,
- instruction strategy,
- root workflow document,
- every independent scope,
- docs and plan roots for each scope.

Setup merges newly requested scopes into the existing configuration rather than removing previously registered scopes.

## Machine-readable dry runs

```powershell
python -m development_ledger setup -r C:\src\project -s apps/web -F json
```

The result includes every operation with one of:

- `create`
- `update`
- `unchanged`
- `conflict`

No operation is applied without `--write`.

## Standalone and dedicated entry points

```powershell
development-ledger-setup -r C:\src\project -m backup -w
```

```powershell
python setup_development_ledger.py -r C:\src\project -m backup -w
```

Both invoke the same setup implementation as `development-ledger setup`.

## Session refresh

After setup changes instruction files, begin a new coding-agent session or use the agent's explicit memory reload command when available. Existing sessions may retain instruction context loaded before the update.
