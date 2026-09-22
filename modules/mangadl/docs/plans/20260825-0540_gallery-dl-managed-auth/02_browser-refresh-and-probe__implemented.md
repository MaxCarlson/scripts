# Stage S2 — Browser Refresh and Probe

## Scope

1. Launch or reuse Chrome/Edge CDP sessions and open the exact target URL.
2. Capture all cookies relevant to the target domain and the browser UA.
3. Support Firefox cookie export through gallery-dl, with an optional explicit
   UA override.
4. Write HttpOnly-compatible Netscape cookies atomically.
5. Validate the exact target URL through gallery-dl simulation before saving.

## Validity Rules

- Expiry is status metadata, not proof of validity.
- An unchanged UA does not make an old cookie valid.
- `403`, `ChallengeError`, and Cloudflare challenge output on the actual target
  are authoritative stale-profile signals.
- No cookie value or raw CDP payload may enter output or logs.

## Evidence

- Implemented in `mangadl/gallery_auth.py` and `mangadl auth refresh`.
- Focused profile/browser/probe tests pass.
- Live Cloudflare validation remains a user-controlled S3 manual check.
