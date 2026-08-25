# Managed Gallery-DL Auth Handoff

## Branch and Stage

- Branch: `agent/mangadl-gallery-auth`
- Base: `agent/unified` at `78f07e6`
- Current stage: S4 complete; review/commit pending

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
- S4 user validation ran `mangadl auth refresh` with no URL from
  `B:\Hent\tmphent3`. It opened Chrome, printed browser/probe progress, passed
  exact-target validation, and wrote
  `B:\Hent\tmphent3\mangakakalot.gg-cookies.txt`.
- `mangadl run config -i .\urls20.txt ... -n` accepted and automatically routed
  all 25 unique URLs to gallery-dl, with one duplicate and no unsupported URLs.
- Version 1.14.0 is installed editable and `python -m pytest` passes with
  `143 passed`.

## Immediate Next Action

Review the S4 diff, then stage/commit/push it when approved. Do not merge before
the separate integration approval boundary.
