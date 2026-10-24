# Runmux Current Handoff

Last updated: 2026-10-24

## Resume Here

The Runmux Web UI UX refinement was merged into `main` on 2026-10-24
from `codex/runmux-web-ux-20261024`, based on `origin/main` at
`3e84e8c9a5de3c83b268c7988944e34da716fb2b`. See
`plans/20261024-runmux-web-ux-refinement/00-implementation-plan.md` for the
gap assessment and validation. It adds status-grouped process navigation and
browser-only process tabs, and gives the process workspace more screen space.
It preserves the existing authenticated terminal and supervisor input-lock
flow. The merge is published on `origin/main`.

The preceding interactive-terminal feature was merged into `origin/main` and
its completed record remains in `plans/20261023-runmux-web-interactive-terminal/`.

### UX refinement validation

- Desktop screenshot and interaction smoke used only the synthetic registry
  under `.pytest_tmp_root/web-ux-visual`.
- Verified status grouping, selecting two views, switching between them,
  closing one view while its process remained listed, and the Details labels.
- Browser access required an elevated local loopback server because the default
  sandbox could not bind the port; no production state was opened.
- Automated test results are recorded in the UX refinement plan.

The current isolated feature branch adds an authenticated browser terminal to
the existing read-only Web UI. Its plan and current status are in
`plans/20261023-runmux-web-interactive-terminal/`. The branch starts at the
latest fetched `origin/main`; commit and push it for review, but do not merge.

The earlier native TUI integration remains recorded below as project history;
the branch named in that historical section differs from this feature branch.

Read in this order:

1. Applicable global and repository-level LLM instructions
2. `README.md`
3. `plans/HANDOFF.md`
4. `plans/20261023-runmux-web-interactive-terminal/HANDOFF.md`
5. `plans/20261023-runmux-web-interactive-terminal/STATUS.md`
6. `plans/20261023-runmux-web-interactive-terminal/checklist.md`
7. `plans/20261023-runmux-web-interactive-terminal/00-implementation-plan.md`

## Current State

- Cycle 1 was committed as `f697615`.
- Stage 2 was committed as `1cb73e4` and manually approved on 2026-07-19.
- Integration branch is `codex/runmux-native-tui-final-integration`, based on
  `f6bf043bee4cf9a694f52ce7c2845510f3cde5d0`.
- Runmux source version is `0.11.0` on this branch.
- The read-only browser UI is available as `runmux web`; its login code is
  printed at startup and remains valid until server exit.
- The native process workspace is available as `runmux tui`; it is being
  integrated using the consolidated `cli_tui` package.
- Stage 2 automated verification passed and the user confirmed concurrent
  terminals can interact with or view the same managed run.
- Stage 4 history display, filtering, common-command, replay, interactive, and
  fzf code is implemented but awaiting user-run tests and manual validation.
- Documentation now includes a detailed project README, reusable AGENTS policy,
  and HANDOFF files in every created documentation directory.
- Current acceptance checks and remaining work are tracked in the final
  integration plan linked above.

## Cycle 2 Implementation

- SQLite attachment-session schema and lifetime counters.
- View and interact registration with heartbeat leases.
- Concurrent interact clients.
- Supervisor-owned FIFO input lock.
- First interactor receives initial ownership.
- Lowercase `l` requests ownership from Ctrl-X command mode.
- Ten-second minimum tenure and 250 ms input-idle transfer.
- Immediate holder-disconnect handoff.
- Stale-session expiration.
- Input from non-holders is discarded rather than replayed.
- `runmux ls/list` and JSON expose attachment and lock counts.

## Verification Evidence

```text
pytest --tb=short -q .\modules\runmux\  -> 72 passed
ruff check ...                         -> passed
black --check --line-length 120 ...    -> passed
python -m compileall ...               -> passed
coverage                               -> 54% overall, store 89%
real IPC smoke                         -> I:2 V:1 T:3 L:1 Q:1
```

## Manual Validation

The user confirmed on 2026-07-19 that multiple terminals can interact with or
view the same managed run. The original validation procedure was:

1. Start an indefinitely interactive managed program.
2. Open two `runmux interact` clients for the same run.
3. Verify Ctrl-X works independently in both clients.
4. Verify only the first client initially controls program input.
5. In the second client press Ctrl-X, then lowercase `l`.
6. Verify it reports queue position 1.
7. After minimum tenure and holder inactivity, verify control transfers.
8. Add a view client and check live output.
9. Check `runmux ls` current/lifetime and lock counts.
10. Detach clients and confirm current counts drop while lifetime totals remain.

## Known Risks

- Stage 3 persistent configuration remains incomplete even though attachment
  status rendering exists in the current code.
- Stage 4 storage migration/retention remains unfinished.
- Existing overall coverage remains modest because older CLI/supervisor paths
  have limited tests, though new state/store logic has direct coverage.

## Next Action

Complete the focused TUI, web UI, lifecycle, package import-boundary,
concurrency, Ruff, and diff checks. Record any remaining Windows terminal
acceptance check in the plan. The authorized deliverable is a review branch;
do not merge it into `main`.
