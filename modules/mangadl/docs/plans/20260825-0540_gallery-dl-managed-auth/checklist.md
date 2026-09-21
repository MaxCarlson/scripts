# Managed Gallery-DL Auth Checklist

## S1 — Profile and UA Foundation

- [x] Define generic domain/profile and Netscape-cookie persistence APIs.
- [x] Implement default auth-directory selection and atomic secret-file writes.
- [x] Add explicit gallery User-Agent option propagation.
- [x] Define Chrome-default and explicit Chrome/Edge/Firefox browser-selection
  contracts for later profile creation and use.
- [x] Add secret-free `auth status` and `auth clear` commands.
- [x] Add focused offline tests, including explicit credential precedence.
- [x] Run focused tests and full mangadl pytest suite.

## S2 — Browser Refresh and Probe

- [x] Implement Chrome/Edge CDP capture, Firefox browser-cookie export, atomic
  refresh, and simulation probe.
- [x] Add `auth refresh` and mocked browser/probe tests.
- [x] Validate/open the exact target URL rather than a site homepage.
- [x] Treat real challenge output as stale auth regardless of expiry or UA age.

## S3 — Managed Runtime Retry

- [x] Resolve profiles per gallery-dl job and add one shared refresh/retry.
- [x] Add concurrency and negative-classification coverage.
- [x] Keep optional gallery-dl browser emulation deferred and non-mandatory.
- [x] Document the Windows simulation-only validation procedure.
- [x] Run final offline verification and prepare integration evidence.
- [x] Complete the user-controlled exact-target Chrome simulation validation.

## S4 — Target Catalog and Visible Refresh

- [x] Add runtime gallery-dl site discovery and `auth sites` output.
- [x] Add persistent validated site targets and URL replacement.
- [x] Make Manganelo/Mangakakalot the no-URL refresh default.
- [x] Prompt for an actual supported URL when a selected site has no target.
- [x] Default cookie exports to `<domain>-cookies.txt` in the invocation folder.
- [x] Force exact-target browser navigation on every refresh.
- [x] Add immediate and periodic refresh progress without secret output.
- [x] Add focused tests, update docs/version, and run the full suite.
- [x] Repeat user-controlled no-URL Chrome validation.

## S5 — Generic Gallery-DL Output Integrity

- [x] Reproduce the bad generic naming and HTTP 520 retry storm from raw logs.
- [x] Prove the refreshed cookie + matching UA downloads one child extractor
  with native gallery-dl naming (42 images, 1,300,372 bytes, 9.2 seconds).
- [x] Restrict legacy gallery naming to compatible extractor metadata.
- [x] Detect gallery-dl child-extractor errors even when its process exits 0.
- [x] Add focused naming, embedded-error, HTTP 520, and merge-race tests.
- [x] Run the full mangadl test suite (`146 passed`).
- [x] Repeat a single-URL download through mangadl and verify 42 distinct
  images (1,300,372 bytes, 3.7 seconds).
- [x] Validate four same-domain workers with one bounded retry: 4/4 jobs,
  702 images, 22,438,146 bytes, 11.9 seconds. No domain cap is required.

## S6 — Destination-Root Series Layout

- [x] Confirm the required `<destination>/<series>/...` library contract.
- [x] Resolve gallery-dl category wrappers without a network request.
- [x] Flatten only the native category wrapper during successful merge.
- [x] Preserve nhentai naming and fallback behavior.
- [x] Use stable URL-hash partial folders for collision-free cross-run resume.
- [x] Keep auth-refresh and transient retry budgets independent.
- [x] Add focused output-layout and regression tests.
- [x] Run the full mangadl test suite and synchronize the feature version.
- [ ] Live-validate direct series folders under a selected destination.
- [x] Default archive/state/logs beneath `<destination>/.mangadl` while
  preserving explicit overrides.
- [x] Replace default dry-run JSON with a concise human report; keep explicit
  JSON output.
- [x] Run managed-auth refresh outside the dashboard/input loop and surface
  progress inside the dashboard.
- [x] Hold every same-domain attempt that reports a challenge for the shared
  refresh, then restart it with the replacement profile.
- [x] Add focused CLI-default, dry-run, TUI-progress, and domain-refresh tests.
- [x] Abort stale gallery-dl backend attempts promptly on authoritative
  challenge output so they reach the one shared refresh without a retry storm.

## S7 — Input-Wide Authentication Preflight (Blocked on S6 Acceptance)

- [ ] Parse and report unique canonical URLs before worker launch.
- [ ] Discover gallery-dl routes from the installed extractor registry.
- [ ] Group represented gallery-dl URLs by normalized auth domain.
- [ ] Create/replace one profile per domain using an exact representative URL.
- [ ] Reuse a saved domain URL automatically; prompt only for never-known domains.
- [ ] Make explicit URLs validate and replace the saved domain target.
- [ ] Keep saved target URLs when cookies/profiles are cleared or replaced.
- [ ] Clearly report created, replaced, reused, and failed profile outcomes.
- [ ] Add forced single-domain and all-input-domain replacement controls.
- [ ] Add explicit reuse/no-browser-preflight control.
- [ ] Keep all secret-bearing auth artifacts outside the source module/repo.
- [ ] Add `modules/mangadl/AUTH_TARGETS.md` as the non-secret site/URL/config catalog.
- [ ] Add explicit runtime-target-to-Markdown catalog synchronization/export.
- [ ] Prove catalog export excludes cookies, headers, and raw browser data.
- [ ] Add mocked multi-domain, failure, concurrency, and secret-leak tests.
- [ ] Begin implementation only after every S6 acceptance gate passes.
