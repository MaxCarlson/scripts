# Stage S6 — Destination-Root Series Layout

## Trigger

Live validation confirmed extractor-native Mangakakalot naming prevents page
collisions, but gallery-dl's default directory format adds its category as an
extra wrapper:

```text
<destination>/mangakakalot/<series>/<chapter>/<image>
```

The required library contract is that the series folders themselves are
direct children of any user-selected destination:

```text
<destination>/<series>/<chapter>/<image>
```

## Scope

1. Continue using native gallery-dl formats in each isolated partial directory.
2. Resolve the selected extractor's category without network requests.
3. On successful generic gallery-dl completion, merge the contents of that
   category directory into the destination rather than merging the category
   wrapper itself.
4. Fall back to the existing merge root when the expected category structure
   is absent or when the legacy nhentai-compatible naming override is active.
5. Preserve concurrent nested merges and partial directories on failure.
6. Namespace partial job folders by a stable canonical-URL hash so unrelated
   jobs cannot collide and the same URL can resume its partial data across
   later runs/state databases.
7. Keep the single automatic authentication-refresh attempt independent from
   the configured transient retry budget.
8. Add focused layout/fallback/nhentai tests and repeat live Mangakakalot
   validation against an isolated destination.
9. Default archive, state, and logs to `<destination>/.mangadl/` so ordinary
   use requires no shell variables or manually constructed control paths.
10. Render dry-run as a concise human preflight by default, retaining an
    explicit JSON mode for scripts.
11. Move runtime browser refresh off the manager/TUI loop. Route progress into
    dashboard state, keep keyboard input responsive, and suppress direct
    refresh writes over the active TUI.
12. Coordinate a successful per-domain refresh across every affected
    gallery-dl attempt: hold each attempt that reports a challenge and restart
    it with the replacement cookie/UA bundle without charging the normal retry
    budget.
13. Stop a gallery-dl attempt promptly when its streamed output contains an
    authoritative Cloudflare/auth challenge. The process has already loaded
    its cookie jar and cannot adopt a replacement in place; continuing its
    internal chapter retry walk only delays the shared manager refresh.

## Failed Acceptance Evidence — 2026-08-25

A 25-URL, four-worker Mangakakalot run proved downloads and stable partials
were active, but failed the UX/runtime acceptance boundary:

- the manager synchronously spent about two minutes inside browser refresh;
- keyboard selection and dashboard rendering stopped during that call;
- refresh progress wrote directly to stderr and escaped the dashboard;
- worker 1 triggered the refresh and stopped at `FINISH_RETRY`, while workers
  2-4 continued writing activity and raw logs with their startup credentials;
- the four workers received repeated real 403/Cloudflare challenge responses,
  so replacing the cookie file alone could not update already-running
  gallery-dl processes.

This evidence supersedes the earlier small four-chapter conclusion that no
same-domain coordination beyond single-flight refresh was necessary.

## Completion Gate

- `-d TARGET` produces `TARGET/Like No Other/c000/...` with no
  `TARGET/mangakakalot` directory.
- All images remain uniquely named and the archive behavior is unchanged.
- The full mangadl test suite passes and version sources are synchronized.
- Existing partial folders from unrelated URLs are never reused, while the
  same canonical URL resumes its stable partial folder across runs.
- A refreshable auth challenge followed by a transient CDN failure still gets
  the configured bounded transient retry.
- `mangadl run -i urls.txt -d TARGET` supplies safe destination-local control
  paths without PowerShell variables; explicit overrides still win.
- `--dry-run` is readable at a terminal and `--json` preserves structured
  automation output.
- Authentication refresh leaves the TUI responsive and intact, opens only one
  browser flow per domain, and restarts every same-domain attempt that reports
  a challenge with the successful replacement profile.
