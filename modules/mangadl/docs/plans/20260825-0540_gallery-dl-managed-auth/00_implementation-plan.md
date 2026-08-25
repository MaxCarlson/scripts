# Managed Gallery-DL Authentication

## Objective

Add generic, per-domain browser-session management for gallery-dl-backed URLs.
The feature persists a Netscape cookie file and matching browser User-Agent
outside the repository, lets users inspect/refresh/clear profiles, reuses a
profile automatically for gallery-dl jobs, and performs at most one shared
browser refresh for a recognized authentication challenge.

## Invariants

- Backend routing remains `gallery_dl.extractor.find()` based; no
  Mangakakalot-specific downloader or host allowlist is introduced.
- Cookie values, raw CDP payloads, and Cookie headers never enter CLI output,
  errors, logs, plans, or tests.
- Explicit `--cookies`, `--cookies-browser`, and `--gallery-config` choices
  retain precedence over managed profiles.
- Profiles are resolved per canonical job URL, not as one global cookie/UA for
  a mixed-domain input file.
- Cookie expiry and an unchanged User-Agent are informational only. A real
  gallery-dl `403`, `ChallengeError`, or Cloudflare challenge for a target URL
  authoritatively marks that profile stale and permits the one bounded refresh.
- Browser navigation and gallery-dl validation use the exact gallery/series URL
  that failed, never only the site's home page.
- Chrome is the default managed-auth browser. `chrome`, `edge`, and `firefox`
  are explicit supported browser selections for credential creation and use;
  no browser is silently substituted for another.
- Browser refresh is bounded to one attempt per domain per run and uses a
  per-domain single-flight lock.
- Automated tests use mocked CDP/gallery-dl behavior; no live Cloudflare site
  is required.

## Stages

1. **S1 — Profile and UA foundation:** profile store, domain normalization,
   Netscape writer, explicit gallery User-Agent propagation, and safe
   `auth status` / `auth clear` commands.
2. **S2 — Browser refresh and probe:** Chrome/Edge CDP discovery and launch,
   Firefox profile-cookie import, matching-UA selection, atomic persistence,
   exact-target navigation, `auth refresh`, and simulation probe classification.
3. **S3 — Managed runtime retry:** per-job profile resolution, one bounded
   challenge refresh/retry, per-domain concurrency coordination, regression
   tests, README/manual validation, and merge evidence.
4. **S4 — Target catalog and visible refresh:** runtime gallery-dl site
   discovery, persistent validated target URLs, a Mangakakalot default target,
   current-directory cookie exports, forced exact-target browser navigation,
   and periodic progress while browser verification is pending.

## Acceptance Criteria

| ID | Criterion | Stage |
| --- | --- | --- |
| AC-S1-001 | Per-domain auth profiles persist non-secret metadata and Netscape cookies atomically outside the repository. | S1 |
| AC-S1-002 | Gallery-dl workers receive an explicit User-Agent when selected, while existing explicit cookie/browser/config options remain compatible. | S1 |
| AC-S1-003 | `mangadl auth status` and `mangadl auth clear` expose safe, secret-free profile management. | S1 |
| AC-S2-001 | Chrome CDP capture filters target-domain cookies, captures the matching UA, and writes a reusable profile without secret logging. | S2 |
| AC-S2-002 | `mangadl auth refresh` defaults to Chrome and accepts explicit Chrome, Edge, or Firefox selection for credential generation/use, performs a gallery-dl simulation probe, and reports actionable timeout/challenge outcomes. | S2 |
| AC-S2-003 | Refresh opens and validates the exact target URL; future expiry or an unchanged UA never overrides an observed gallery-dl challenge. | S2 |
| AC-S3-001 | Gallery-dl jobs reuse a managed profile only when explicit credential sources are absent. | S3 |
| AC-S3-002 | Recognized authentication challenges trigger at most one shared per-domain refresh and retry; 404, rate-limit, parser, and filesystem failures do not. | S3 |
| AC-S3-003 | Documentation includes the Windows Mangakakalot validation procedure without recording credential material. | S3 |
| AC-S4-001 | `mangadl auth refresh` works with no URL by using the saved or built-in Manganelo/Mangakakalot target; `--url` validates and replaces the saved target. | S4 |
| AC-S4-002 | `mangadl auth sites` derives sites/extractors from the installed gallery-dl registry and indicates which sites have usable saved targets. | S4 |
| AC-S4-003 | Missing target URLs trigger an actionable interactive prompt, and only URLs accepted by the selected gallery-dl site are persisted. | S4 |
| AC-S4-004 | Refresh always opens the exact target in the selected browser and emits immediate plus periodic challenge/probe progress until success or timeout. | S4 |
| AC-S4-005 | Generated cookie files default to `<domain>-cookies.txt` in the invocation directory unless `--cookie-file` overrides it. | S4 |

## Deferred Secondary Fallback

Gallery-dl browser emulation (for example `-o browser=chrome:windows`) may be
added later as an opt-in fallback if fresh cookies plus the exact captured UA
still fail. It is not mandatory for this plan because the live-confirmed
primary recovery is fresh domain cookies, matching UA, and exact-target
validation. It must not be enabled globally or replace the primary flow.

## Verification Strategy

Each stage runs its focused offline pytest tests, then the full module suite:

```powershell
python -m pytest modules/mangadl/tests -q -o addopts=""
```

S2/S3 additionally require one user-controlled Windows manual validation with
the existing cookie file at `B:\Hent\tmphent3\mangakakalot-cookies.txt` or a
new Chrome-derived profile. The live step remains simulation-only until the
user explicitly authorizes a download.

## Merge Boundary

Do not merge this branch directly to `main`. After S3 passes, commit/push the
completed branch, integrate through `agent/unified`, run the affected module
validation there, and obtain user approval for the `main` merge.
