# Managed Gallery-DL Auth Status

## State

S1-S5 are complete. S5 corrected the generic gallery-dl output-integrity
regressions found by the first real multi-URL download. The silent timeout was replaced with phase/remaining-time
progress, no-URL Mangakakalot refresh works, runtime site discovery/selection
and saved validated targets are implemented, cookie exports default to the
invocation directory, and exact-target navigation is forced.

Offline verification passes (`143 passed`). User-controlled `mangadl auth
refresh` with no URL succeeded from `B:\Hent\tmphent3`, wrote
`mangakakalot.gg-cookies.txt`, and showed browser/probe progress. A dry-run of
`urls20.txt` accepted 25 unique URLs, routed all 25 to gallery-dl, reported one
duplicate, and reported no unsupported URLs.

The controlled live baseline now passes: after exact-target refresh,
gallery-dl downloaded 42 distinct images (1,300,372 bytes) from the first
`like-no-other` chapter in 9.2 seconds; mangadl downloaded the same 42 images
in 3.7 seconds. A four-worker mangadl run completed 4/4 chapters with 702
images (22,438,146 bytes) in 11.9 seconds using one bounded retry. The full
offline suite passes with 146 tests on version 1.14.1.

## Next Action

Publish the completed S5 patch and switch to `main` as requested. The feature
remains unmerged pending the existing integration boundary.
