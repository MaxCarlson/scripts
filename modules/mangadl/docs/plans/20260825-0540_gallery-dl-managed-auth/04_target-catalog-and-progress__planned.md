# Stage S4 — Target Catalog and Visible Refresh

## Trigger

User validation showed `mangadl auth refresh -u <url>` could remain silent for
120 seconds and then time out. The follow-up also requires URL-optional default
use, runtime gallery-dl site discovery, saved target URLs, and cookie exports in
the invocation directory.

## Scope

1. Discover supported sites/extractors from the installed gallery-dl registry;
   do not duplicate gallery-dl's full support list in source.
2. Persist one validated target URL per gallery-dl site. A newly supplied valid
   URL replaces the prior saved URL.
3. Seed Manganelo/Mangakakalot with the previously validated actual series URL
   and make it the no-argument refresh default.
4. Add site listing/selection. If the chosen site has no saved actual URL,
   explain why an example/homepage is insufficient and prompt for a URL that
   gallery-dl accepts for that same site.
5. Default generated files to `<domain>-cookies.txt` under `Path.cwd()`;
   `--cookie-file` remains authoritative.
6. Always open/navigate the exact target URL, even when a debug browser already
   has another tab for that domain or the same stale target.
7. Emit immediate and periodic progress, including browser launch/reuse,
   cookie discovery, simulation attempts, remaining timeout, and continuing
   challenge state. Never print values.

## Failure Diagnosis to Address

The observed timeout means the loop remained alive but had no usable refreshed
profile before the deadline. Existing code emitted no progress when it reused
an already-running debugger and could select an already-open exact target
without forcing a fresh navigation. S4 must force a new exact-target navigation
and make each waiting/probe phase visible.

## Completion Gate

- Offline tests cover runtime site discovery, target replacement, invalid-site
  rejection, no-URL default, current-directory naming, forced navigation, and
  periodic progress.
- Full pytest suite passes and version sources are synchronized.
- A user-controlled `mangadl auth refresh` with no `-u` succeeds or produces
  enough phase/remaining-time output to diagnose the exact blocking phase.

## Result

Complete. The no-URL command succeeded with visible browser/probe progress and
created the domain-prefixed cookie file in the invocation folder. The full
suite passes with 143 tests, and the actual `urls20.txt` dry-run routed every
unique URL through gallery-dl.
