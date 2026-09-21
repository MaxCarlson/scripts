# Managed Gallery-DL Auth Status

## State

S1-S5 are complete. S6 is in progress to make series directories direct
children of every user-selected destination and close the failed manual-run
acceptance findings. S5 corrected the generic gallery-dl output-integrity
regressions found by the first real multi-URL download. The silent timeout was replaced with phase/remaining-time
progress, no-URL Mangakakalot refresh works, runtime site discovery/selection
and saved validated targets are implemented, cookie exports default to the
invocation directory, and exact-target navigation is forced.

Offline verification passes (`143 passed`). User-controlled `mangadl auth
refresh` with no URL succeeded from `B:\Hent\tmphent3`, wrote
`mangakakalot.gg-cookies.txt`, and showed browser/probe progress. A dry-run of
`urls20.txt` accepted 25 unique URLs, routed all 25 to gallery-dl, reported one
duplicate, and reported no unsupported URLs.

The earlier controlled live baseline passed: after exact-target refresh,
gallery-dl downloaded 42 distinct images (1,300,372 bytes) from the first
`like-no-other` chapter in 9.2 seconds; mangadl downloaded the same 42 images
in 3.7 seconds. A four-worker mangadl run completed 4/4 chapters with 702
images (22,438,146 bytes) in 11.9 seconds using one bounded retry. A later
25-URL run disproved that small-run concurrency conclusion: synchronous auth
refresh blocked TUI input/rendering, refresh messages escaped the dashboard,
and already-running same-domain workers continued with credentials loaded
before the shared profile replacement. The activity/raw logs remained present
and workers 2-4 continued downloading, so this was a coordination/display
failure rather than lost work. S6 now includes that remediation plus
destination-local control-path defaults and human-readable dry-run output.
The remediation was implemented in version 1.15.0 and is included in the
current 1.17.0 partial-safety release candidate. The full offline suite passes
with 182 tests; compile and Ruff pass; local human and JSON dry-runs route the
Mangakakalot target without creating the destination control directory. A live
chapter-0 run now confirms direct destination-root layout, and a live TTY run
confirms responsive activity/raw-log/worker view switching. A current
four-URL/four-worker run also completed 4/4 chapters with 702 images and
22,438,146 bytes without a retry. Only the potentially large complete-series
S7 dependency remains pending.

Exact verification commands:

```powershell
python -m pytest tests -q -o addopts=""
python -m compileall -q mangadl tests
python -m ruff check mangadl tests
mangadl --version
mangadl run config -u 'https://www.mangakakalot.gg/manga/like-no-other' -d 'C:\tmp\mangadl-dry-run-output' -n
mangadl run config -u 'https://www.mangakakalot.gg/manga/like-no-other' -d 'C:\tmp\mangadl-dry-run-output' -n -J
```

Current combined results: `182 passed`; compile exit 0; Ruff `All checks passed!`;
`mangadl 1.17.0`; both dry-runs exit 0; no destination `.mangadl` directory
was created.

Additional offline integrations prove that two same-domain jobs share exactly
one background refresh and both succeed on their second attempts, a streamed
Cloudflare challenge terminates a stale backend process promptly rather than
waiting through its retry walk, and an ordinary run constructs every control
path from `-d` without shell variables.

## Next Action

Decide whether to run the potentially large complete-series gate or defer S7
to a follow-up branch. The feature remains unmerged pending the existing
integration boundary and explicit final merge approval.

S7 input-wide authentication preflight is planned but explicitly blocked on
S6 live acceptance. It will deduplicate and route the complete input, group
gallery-dl URLs by auth domain, visibly create/replace one profile per domain,
and expose force-one/force-all controls without storing secrets in the repo.
