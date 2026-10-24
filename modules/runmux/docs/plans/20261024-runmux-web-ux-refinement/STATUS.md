# Runmux Web UI UX Refinement Status

Updated: 2026-10-24

## Current state

Implementation and focused validation are complete on
`codex/runmux-web-ux-20261024`, based on `origin/main` at
`3e84e8c9a5de3c83b268c7988944e34da716fb2b`.

- The explorer groups records by actual Runmux status and keeps collapse state
  when the list refreshes.
- Selecting a run opens a browser-only process tab. Tabs can be switched or
  closed without process lifecycle operations.
- The former summary cards and page heading were removed to give the existing
  Output, Terminal, and Details workspace more height.
- Existing HTTP authentication, terminal WebSocket, supervisor attachments,
  and FIFO input-lock gates are unchanged.
- See `00-implementation-plan.md` for the gap assessment and test evidence.

## Verification

- Node syntax check and frontend harness passed.
- Focused Runmux web and adapter tests: 18 passed.
- Headless screenshots at 1920×1080, 1366×768, and 768×1024 showed no
  horizontal overflow.
- Authenticated Chrome interaction used only `.pytest_tmp_root/web-ux-visual`.

## Delivery state

Commit and push to the dedicated review branch are the remaining steps.
Do not merge into `main`.
