# Authenticated Read-Only Remote Dashboard & Mobile PWA

## Overview & Architecture

The `remote_control` module provides a mobile-first, authenticated web dashboard and Progressive Web Application (PWA) for monitoring notifications, incidents, delivery provider readiness, and host heartbeat status across the `scripts` repository.

In Phase 06, this interface is **strictly read-only with respect to managed systems and applications**. It does not execute arbitrary shell commands, start/kill external processes, or mutate the state of the Resource Coordinator or notification broker. All queries against the durable notifications database utilize strict SQLite read-only URI connections (`mode=ro`).

```
                +-------------------------------------------+
                |          Mobile Browser / PWA Shell       |
                |  (Standalone Home Screen / DOM-Safe App)  |
                +-------------------------------------------+
                                      |
                     HTTPS (via Loopback / Tailscale)
                   Cookie: __Host-rc_session (HttpOnly)
                   Header: X-CSRF-Token (Mutations only)
                                      v
                +-------------------------------------------+
                |            FastAPI Remote Control         |
                |             (127.0.0.1:8443)              |
                +-------------------------------------------+
                   |                 |                   |
         Argon2id + TOTP      mode=ro SQLite       Read-Only OS
                   v                 v                   v
            +------------+   +---------------+   +---------------+
            |  auth.db   |   | notifications |   | Heartbeat     |
            | (WAL Mode) |   | .db (Broker)  |   | & Task Sched  |
            +------------+   +---------------+   +---------------+
```

---

## Authentication & Session Security Model

The service implements a hardened authentication boundary designed from inception for secure public internet exposure (e.g., via Tailscale Funnel):

1. **Single Operator Policy:**
   - The system permits exactly one human operator identity.
   - Bootstrapping is restricted to local console access via `scripts-remote-control bootstrap`. Remote registration endpoints are rejected.
2. **Password Hardening:**
   - Passwords are validated and hashed using **Argon2id** (OWASP-recommended profile: `time_cost=3`, `memory_cost=64MB`, `parallelism=4`, `hash_len=32`).
3. **Multi-Factor Authentication (RFC 6238 TOTP):**
   - Mandatory two-factor authentication on every login using a cryptographically random base32 seed.
   - Compatible with Google Authenticator, Aegis, Bitwarden, 1Password, etc.
   - Enforces +/- 1 step (30s) drift tolerance with **strict replay prevention**: consumed timesteps (`timestamp // 30`) are persisted in SQLite, preventing reuse of the same 6-digit code within its validity window.
4. **Brute-Force & Rate-Limit Defense:**
   - 5 failed login attempts within a 15-minute window immediately trigger a lockout (`HTTP 429 Too Many Requests`).
   - Constant-time string comparisons (`hmac.compare_digest`) prevent side-channel timing attacks on credentials and tokens.
5. **Session Architecture:**
   - Session identifiers are generated using 32 bytes of cryptographically secure random entropy (`secrets.token_urlsafe(32)`).
   - Only the SHA-256 digest of the token is stored in the database; theft of `auth.db` does not compromise active sessions.
   - Sessions feature sliding-window idle timeouts (default: 4 hours) and absolute maximum lifetimes (default: 7 days).
   - Session rotation: authenticating from a device invalidates prior sessions for that device.
6. **Device Enrollment & Revocation:**
   - Personal devices are recorded with a unique device identifier, device name, and activity timestamps.
   - Operators can permanently revoke any device via the web interface or CLI (`scripts-remote-control revoke-device`), immediately terminating all active sessions for that device.
7. **Audit Logging:**
   - Every bootstrap, login attempt (success/denial), session revocation, and device lifecycle event is recorded in an append-only audit ledger in `auth.db`.

---

## HTTP Security & CSRF Defense

- **Cookie Flags:**
  - `HttpOnly`: Session cookies cannot be accessed by client JavaScript.
  - `SameSite=Strict` (configurable to `Lax`): Enforces browser origin boundaries.
  - `Secure`: Required in production/HTTPS (`__Host-` cookie prefix applied).
  - `Path=/`: Restricts scope to application root.
- **CSRF Token Enforcement:**
  - All state-changing operations (`POST`, `PUT`, `DELETE`, `PATCH`) require a valid `X-CSRF-Token` header matching the authenticated session.
- **Content Security Policy (CSP):**
  - `default-src 'self'`: Disallows loading foreign resources.
  - No `unsafe-eval` or inline scripts.
  - `object-src 'none'`, `frame-ancestors 'none'` (`X-Frame-Options: DENY`).
  - `X-Content-Type-Options: nosniff`.
- **Cache-Control:**
  - All `/api/*` endpoints enforce `Cache-Control: no-store, no-cache, must-revalidate` to prevent caching of incident data or evidence.
- **Host & Origin Validation:**
  - Incoming `Host` headers are validated against an allowed whitelist.
  - Foreign `Origin` headers on state-changing requests are strictly rejected (`HTTP 403 Forbidden`).

---

## Mobile Progressive Web App (PWA)

The frontend is implemented as a lightweight, zero-dependency, DOM-safe Progressive Web Application:

- **Mobile First Responsive Design:**
  - Viewport-optimized layout (`viewport-fit=cover`, touch-callout disabled).
  - Minimum 48px touch targets for high-reliability mobile usage.
  - Supports automatic light/dark system themes with CSS custom properties.
- **Home Screen Installation:**
  - `manifest.json` provides metadata for standalone mobile launch (hides browser chrome).
  - Maskable SVG icon (`/static/icon.svg`).
- **Service Worker (`sw.js`):**
  - Caches only static shell assets (`index.html`, `style.css`, `app.js`, `manifest.json`, `icon.svg`).
  - **Strict Security Rule:** The service worker explicitly passes through all `/api/*` requests directly to the network; sensitive incident data is never cached in client service worker storage.
- **DOM-Safe Rendering:**
  - All dynamic data is inserted using `document.createTextNode` and programmatic DOM creation (`h()` helper).
  - No `innerHTML` usage; prevents stored XSS from malicious incident payloads or alert summaries.
- **Offline Awareness:**
  - Real-time online/offline connection monitoring surfaces an immediate visual offline banner when network connectivity drops.

---

## CLI Management Reference

The CLI entrypoint `scripts-remote-control` manages the service lifecycle:

```powershell
# 1. Bootstrap operator identity (interactive prompts for password)
scripts-remote-control bootstrap -u sysop

# 2. Inspect operator and session status
scripts-remote-control status

# 3. Launch local server bound strictly to loopback
scripts-remote-control serve --host 127.0.0.1 --port 8443

# 4. Reset operator password (invalidates all sessions)
scripts-remote-control reset-password -u sysop

# 5. Regenerate TOTP seed
scripts-remote-control reset-totp

# 6. Revoke a compromised device
scripts-remote-control revoke-device --device-id dev_12345678

# 7. Invalidate a specific session
scripts-remote-control revoke-session --session-id sess_abcdef1234
```

---

## Forward Compatibility (Phases 05 & 07)

The API is architected for seamless forward integration with planned phases:

1. **Phase 05 (Resource Coordinator):**
   - The `/api/coordinator` endpoint currently returns a typed read-only placeholder contract:
     ```json
     {
       "ok": true,
       "status": "unconnected",
       "available": false,
       "message": "Resource Coordinator adapter available in Phase 05.",
       "inhibition_active": false,
       "miner_state": "unknown"
     }
     ```
   - When Phase 05 is implemented, this adapter will connect to the Coordinator's state machine without altering the dashboard interface.
2. **Phase 07 (Guarded Remote Actions):**
   - State-changing actions will require explicit confirmation, CSRF verification, and step-up re-authentication or TOTP challenge.

---

## Future Tailscale Funnel / Public Ingress Deployment Guide

When deploying this dashboard for secure remote access over the public internet:

1. **Host Interface Binding:**
   - The Python server should **always** bind strictly to `127.0.0.1:8443`.
   - Never bind directly to `0.0.0.0` or public network adapters.
2. **Tailscale Funnel Setup:**
   ```powershell
   # Expose local port 8443 securely via Tailscale Funnel with automatic TLS
   tailscale funnel 8443 on
   ```
3. **Configuration Settings:**
   - Set `REMOTE_CONTROL_COOKIE_SECURE=true` in environment or configuration.
   - Set `REMOTE_CONTROL_ALLOWED_HOSTS=["your-tailnet-node.ts.net"]`.
   - Reverse proxies must pass `X-Forwarded-For` and `X-Forwarded-Proto: https`.
