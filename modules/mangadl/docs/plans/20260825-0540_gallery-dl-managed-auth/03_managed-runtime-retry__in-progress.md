# Stage S3 — Managed Runtime Retry

## Scope

1. Resolve stored credentials per gallery-dl job/domain at dispatch time.
2. Preserve explicit cookie, browser-cookie, gallery config, and UA precedence.
3. Classify only recognized auth/challenge output as refreshable.
4. Let the manager perform one domain refresh and retry each affected job once.
5. Ensure concurrent failures share the same completed domain refresh.
6. Document and run offline/full verification, then prepare a live
   simulation-only manual validation using an actual series URL.

## Negative Boundaries

- Do not refresh on 404, rate limiting, parser failure, or filesystem failure.
- Do not resolve Mangakakalot search pages or add a site-specific backend.
- Do not treat a future cookie expiry or unchanged UA as proof that a challenged
  profile is still valid.
- Do not make gallery-dl browser emulation mandatory; it is a deferred optional
  fallback.

## Completion Gate

- The full module test suite passes.
- README and handoff files describe Chrome-default and Edge/Firefox options.
- Manual validation instructions use the exact problematic target URL.
- Versions are synchronized and integration evidence is recorded.
