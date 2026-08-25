# Managed Gallery-DL Auth Handoff

## Branch and Stage

- Branch: `agent/mangadl-gallery-auth`
- Base: `agent/unified` at `78f07e6`
- Current stage: S3 complete; ready for integration commit

## Current Evidence

- `main` is current with `origin/main` in this checkout.
- The generic profile store, Chrome/Edge CDP capture, Firefox cookie export,
  exact-target gallery-dl probe, UA propagation, auth CLI, and manager-owned
  bounded refresh/retry are implemented.
- `python -m pytest` passes with `133 passed`.
- `mangadl inspect -u https://www.mangakakalot.gg/manga/like-no-other -j`
  reports the installed gallery-dl extractor route, and the corresponding
  `mangadl run config ... -n` accepts and routes the URL to gallery-dl.
- `python -m pip install -e . --no-build-isolation` refreshed the editable
  installation to 1.13.0 and confirmed websocket-client 1.9.0. The initial
  build-isolated install could not reach PyPI in the restricted environment;
  this was an environment/network failure, not a package/test failure.
- Live evidence confirms expiry and unchanged UA are not authoritative; actual
  target challenge output forces a refresh.
- Live `mangadl auth refresh` against
  `https://www.mangakakalot.gg/manga/lets-play-hooky` captured one Chrome
  `cf_clearance` cookie and passed exact-target gallery-dl simulation. A
  one-line input file containing the same URL was then accepted and
  automatically routed to gallery-dl in dry-run mode. No content was
  downloaded and no cookie value was printed or recorded.

## Immediate Next Action

Stage only this plan's files, commit and push the completed feature branch, then
switch to `main` without merging. Integration remains a separate approved
boundary.
