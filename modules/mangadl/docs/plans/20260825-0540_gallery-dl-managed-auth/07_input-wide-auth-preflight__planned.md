# Stage S7 — Input-Wide Authentication Preflight

## Dependency Gate

Do not implement this stage until S6 proves all of the following for the
existing Mangakakalot domain:

1. mangadl creates/replaces and validates a Chrome-derived cookie profile;
2. one complete cookie-protected series URL downloads successfully;
3. its series folder is a direct child of the selected destination; and
4. one URL file completes through multiple workers with correct output and
   bounded retry behavior.

## Objective

Before worker dispatch, make authentication requirements for a complete input
set visible and manageable. Reuse gallery-dl's installed extractor registry;
do not maintain a hardcoded support-site list.

## Preflight Model

1. Parse all CLI URLs and input files using the existing canonicalization and
   duplicate handling.
2. Report canonical unique URLs and rejected duplicates/invalid entries.
3. Resolve backends normally and identify every gallery-dl-routed URL.
4. Group those URLs by normalized authentication/base domain.
5. Resolve each domain's exact refresh target by strict precedence: an explicit
   URL supplied now (validate, use, and save/replace), the domain's previously
   saved URL, then a built-in validated target where available. Prompt only
   when that domain has never had any usable target. Never validate only a
   homepage.
6. Before launching download workers, visibly create or replace at most one
   managed profile per represented domain according to the selected refresh
   policy.
7. Report for every domain: URL count, representative URL, profile state,
   browser, cookie path, and `created`, `replaced`, `reused`, or `failed`.
   Never print cookie values or raw CDP payloads.

## CLI Requirements

- Preserve the existing single-target `mangadl auth refresh --url URL` command
  as the explicit one-domain replacement path. A supplied URL overrides and
  durably replaces the prior URL paired with that base domain.
- Add an input-aware auth command or equivalent run preflight control that
  accepts the same repeatable `--input-file` and `--url` sources as `run`.
- Add explicit force replacement for one selected domain and force replacement
  for every gallery-dl domain represented in the parsed input.
- Add an explicit opt-out/reuse control so unattended runs can avoid browser
  launch when required.
- Every new argument must have both short and long forms.

## Storage and Security

Do not store secret-bearing cookie files inside the mangadl source module or
repository. Continue using the platform-standard per-user auth store (for
example `%APPDATA%\mangadl\auth\<domain>` on Windows), or an explicit
`--auth-dir`. Optional user-facing cookie exports may use an explicit output
directory, but source-controlled paths are never a default.

Writes remain atomic and logs show only domain, cookie count/names where safe,
expiry metadata, UA presence, and paths—not values.

Saved domain-to-target URL metadata is non-secret and persists independently
of cookie/profile files. Clearing or replacing cookies must not discard the
saved target. Removing a saved target requires a separate explicit action.

## Module Catalog

Add a tracked, human-readable `modules/mangadl/AUTH_TARGETS.md` catalog. It
documents known gallery-dl site/module names, normalized base domains,
built-in or intentionally synchronized representative URLs, browser/profile
policy, runtime config/auth paths, and the commands that create, replace,
inspect, clear, and synchronize entries.

The Markdown file contains no cookie values, Cookie headers, raw CDP output,
or other secret-bearing session data. It is documentation and a portable seed,
not the silently mutated per-run database. The writable per-machine authority
remains the platform auth store's `targets.json`, because installed package and
source directories may be read-only and normal runs must not dirty Git.

Provide an explicit catalog export/synchronization command that can render the
current non-secret target inventory to `AUTH_TARGETS.md` when the user asks.
Automatic browser/auth preflight updates the runtime store immediately but
does not rewrite tracked source files implicitly.

## Concurrency

Preflight refreshes are once per normalized domain. If several input URLs share
a domain, they use one refresh result. Normal download concurrency begins only
after preflight finishes or reports a policy-approved failure. Runtime
challenge recovery remains bounded and single-flight per domain.

## Verification

- Unit-test URL deduplication, runtime route discovery, domain grouping,
  representative URL selection, and new/replaced/reused reporting.
- Mock multi-domain browser refresh and prove one call per domain.
- Test force-one, force-all, opt-out, partial failure, and secret-free output.
- Test deterministic Markdown catalog export and prove no secret fields or
  cookie values are included.
- Live-validate Mangakakalot first, then add another real domain only when a
  supported cookie-requiring target is available.
