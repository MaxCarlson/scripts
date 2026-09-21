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
5. **S5 — Generic gallery-dl output integrity:** preserve each extractor's
   native naming unless an explicitly compatible site override is required,
   reject partial-success exits that contain extractor errors, and prevent a
   same-domain worker burst from turning an authenticated session into a long
   sequence of per-chapter retries.
6. **S6 — Destination-root series layout:** retain extractor-native staging
   names, then remove the gallery-dl category wrapper during the successful
   merge so series directories live directly inside the user-selected
   destination. The same acceptance pass also makes normal runs self-contained,
   gives dry-run human-readable output, and prevents managed-auth refresh from
   blocking or corrupting the interactive dashboard.
7. **S7 — Input-wide authentication preflight:** after S6's single-domain
   acceptance gates pass, parse an entire input set before worker launch,
   discover gallery-dl routes at runtime, group them by auth domain, and
   visibly create or replace one managed browser session per represented
   domain with explicit single/all force-refresh controls.

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
| AC-S5-001 | Mangakakalot and other generic gallery-dl extractors retain their native directory/filename formats so distinct pages cannot collapse onto one path. | S5 |
| AC-S5-002 | A gallery-dl exit that downloaded a cover or some pages but also reported extractor HTTP errors is not marked as a successful manga completion. | S5 |
| AC-S5-003 | Live validation downloads multiple distinct images from one authenticated Mangakakalot child extractor without concurrent same-domain interference. | S5 |
| AC-S6-001 | For `-d TARGET`, a Mangakakalot series is merged as `TARGET/<series>/<chapter>/<image>` rather than `TARGET/mangakakalot/<series>/...`. | S6 |
| AC-S6-002 | Category-wrapper removal is derived from gallery-dl's selected extractor and does not reintroduce global metadata templates. | S6 |
| AC-S6-003 | Legacy nhentai/Kavita naming and concurrent merge safety remain intact. | S6 |
| AC-S6-004 | A normal run needs only input and destination; archive, state, and log paths default under a destination-local `.mangadl` control directory while explicit paths remain supported. | S6 |
| AC-S6-005 | Dry-run prints a concise human preflight by default and emits machine JSON only when explicitly requested. | S6 |
| AC-S6-006 | Runtime authentication refresh does not block dashboard rendering or keyboard handling, does not print outside the TUI, and restarts every same-domain attempt that reports a challenge with the refreshed profile. | S6 |
| AC-S7-001 | Input preflight reports canonical unique URLs, gallery-dl-routed URLs, and unique normalized auth domains before dispatch. | S7 |
| AC-S7-002 | Each represented gallery-dl domain is refreshed at most once per preflight using a representative exact supported URL, with clear new/replaced/failed status. | S7 |
| AC-S7-003 | CLI controls can force replacement for one selected domain or every gallery-dl domain represented by one or more input files. | S7 |
| AC-S7-004 | Cookie secrets remain outside the repository/module in the standard per-user auth store or an explicit auth directory. | S7 |
| AC-S7-005 | A domain's validated target URL persists independently from cookies; it is reused without prompting and replaced only by an explicit validated URL or target-removal action. | S7 |
| AC-S7-006 | `modules/mangadl/AUTH_TARGETS.md` provides a deterministic non-secret catalog of known domain/target/config information and can be explicitly synchronized from runtime target metadata. | S7 |

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
