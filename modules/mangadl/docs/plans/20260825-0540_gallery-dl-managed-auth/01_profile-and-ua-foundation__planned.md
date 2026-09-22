# Stage S1 — Profile and UA Foundation

## Scope

Implement the safe, offline core required by all later stages:

1. Generic URL/domain normalization and OS-specific default auth directory.
2. A profile store with atomic metadata/cookie persistence and Netscape cookie
   formatting, including HttpOnly and expiry handling.
3. Explicit gallery-dl User-Agent propagation through CLI options, manager,
   worker arguments, and subprocess construction. Browser selection defaults
   to Chrome and accepts explicit Chrome, Edge, or Firefox values for later
   managed-auth stages.
4. `mangadl auth status` and `mangadl auth clear` with no secret disclosure.
5. Focused unit tests for persistence, formatting, option precedence, and
   worker command construction.

## Exclusions

- No Chrome launch/CDP access, network probe, automatic retry, or live-site
  test in S1.
- No browser cookie/cookie-file mutation outside temporary test directories.

## Completion Gate

- New APIs have no Mangakakalot-specific names or routing behavior.
- Existing explicit `-C/--cookies`, `-B/--cookies-browser`, and `-g/--gallery-config`
  behavior remains covered.
- Focused tests and the full mangadl suite pass before S2 planning begins.
