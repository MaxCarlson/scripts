# Status

Updated: 2026-10-24

## Current state

Implementation and focused validation are complete on
`codex/runmux-web-launch-20261024`.

- Added a session- and same-origin-protected `/api/runs` POST and
  `/api/launch-defaults` GET. The POST validates bounded fields and calls
  `create_managed_run` with structured argv and the resolved working directory.
- Added a `+` workspace tab and empty-registry actions. The form accepts one
  argument per line, preserves errors, blocks duplicate submits, and selects
  the real run and output after success.
- Preserved the existing terminal path and release behavior; opening the form
  closes its browser terminal attachment so supervisor input locks are released.
- Updated the package version to 0.13.0, Runmux README and handoffs, and the
  master roadmap. The supplied FullDoc and UI reference image are included.

## Verification

- Focused web tests: `python -m pytest tests/web_test.py tests/web_adapter_test.py tests/web_cli_test.py -q` — 24 passed.
- Dashboard: `node tests/dashboard_test.js` — passed.
- Syntax: `node --check src/runmux/web_static/assets/dashboard.js` — passed.
- Ruff: `ruff check src/runmux/web.py tests/web_test.py` — passed. `cli.py` has unrelated existing Ruff findings.
- Python: `python -m compileall -q src/runmux` — passed; `python -m runmux --version` — `0.13.0`.
- Metadata check confirmed project and import versions match and wheel config includes web static assets.
- `python -m build --wheel --no-isolation` could not run because `hatchling.build` is unavailable in this environment.
- Full Runmux suite: 155 passed, 4 unrelated CLI/history failures. All four were rerun against the untouched `origin/main` checkout and reproduced there.
- Authenticated browser smoke used a synthetic registry and process: empty-state New Process form, launch, registry listing, output display, and close-view while the process remained Running all behaved as required.

## Remaining limits

- Wheel artifact creation remains unverified until the build environment has
  Hatchling available. Browser access intentionally grants local process
  execution to the holder of the startup login code.

## Next action

Commit and push this dedicated branch, then provide the commit SHA. Do not merge.
