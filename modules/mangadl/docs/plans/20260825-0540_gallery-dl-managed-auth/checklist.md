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
