# Tailscale Funnel Public HTTPS Setup Guide (Phase 08)

**Document Version:** 1.0.0  
**Phase:** Phase 08 — Public HTTPS Readiness, Funnel Lifecycle, and Final Action-Safety Gates  
**Module:** `modules/remote_control`  
**Repository:** `MaxCarlson/scripts`  

---

## 1. Architectural Overview & Boundaries

Phase 08 enables securely controlled, public internet HTTPS access to the authenticated Remote Control Progressive Web Application (PWA) over a free Tailscale Funnel. This allows the operator to access the mobile dashboard from an Android smartphone on a cellular data network without requiring active WireGuard VPN tunnels or running Tailscale on the mobile device.

### Non-Negotiable Isolation Boundaries
1. **Host-Bound Loopback Interface:** The FastAPI server binds strictly to `127.0.0.1:8443` on the Windows workstation. It never binds to `0.0.0.0` or open LAN interfaces.
2. **Narrow Reverse-Proxy Scope:** Tailscale Funnel terminates public HTTPS and proxies requests *exclusively* to `127.0.0.1:8443`.
3. **Strict Subsystem Isolation:**
   - Resource Coordinator raw listener (port 1235) is **never** proxied.
   - Runmux terminal supervisors and process managers are **never** proxied.
   - Notifications broker IPC and administrative endpoints are **never** proxied.
   - Windows credentials and system administration APIs are **never** exposed.
4. **Zero Live Resource Coordinator Mutation:** Production recovery remains server-side disabled (`capability_disabled`). `modules/resource_coordinator/` source code is 100% read-only.
5. **Zero Cloud Spending:** Built entirely on Tailscale's free Personal plan; requires no custom domains, paid proxy services, or cloud VMs.

---

## 2. Prerequisites & Tailnet Policy

Before enabling Tailscale Funnel, ensure the following requirements are met:

### A. Tailscale Account & Node
- A free Tailscale Personal account.
- Tailscale installed and logged in on the Windows workstation.
- MagicDNS and Tailscale HTTPS certificates enabled in the Tailscale Admin Console.

### B. Tailnet Access Control Policy (ACL)
Ensure that Funnel access is restricted to **only** the designated workstation node, preventing inadvertent Funnel activation across other tailnet devices:

```json
{
  "nodeAttrs": [
    {
      "target": ["node:workstation"],
      "attr": ["funnel"]
    }
  ]
}
```

---

## 3. Reverse Proxy & Host Security Architecture

### A. Trusted Proxy Header Defense
Untrusted external clients can inject arbitrary `X-Forwarded-For`, `X-Forwarded-Proto`, or `X-Forwarded-Host` headers to spoof host identity or bypass security controls.

To prevent this:
- Forwarded headers are accepted **only** when the immediate peer connection originates from a configured trusted proxy peer (`127.0.0.1`, `::1`).
- `allowed_hosts` and `allowed_public_hosts` strictly validate the effective HTTP `Host` header against the expected Tailnet public hostname (`<node>.<tailnet>.ts.net`).
- Direct requests with unrecognized or mismatched host headers are rejected with HTTP 400 Bad Request.

### B. Cookie Security & Session Hardening
- Session and device cookies use the `__Host-` prefix in production and external exposure mode.
- `Secure=True` ensures cookies are transmitted solely over HTTPS connections.
- `HttpOnly=True` prevents cookie access from client-side JavaScript.
- `SameSite=Strict` defends against Cross-Site Request Forgery (CSRF).
- HTTP Strict Transport Security (`Strict-Transport-Security: max-age=31536000; includeSubDomains`) is enforced on all external responses.
- API endpoints enforce `Cache-Control: no-store, no-cache, must-revalidate, private` to prevent mobile browser proxy caching of operational data.

### C. Conservative Public Action Policy
When accessed via public external exposure, the application enforces a fail-closed action policy:
- Read-only queries (`operator.read`) are permitted.
- Incident acknowledgement (`notifications.acknowledge_incident`) is permitted with mandatory two-phase confirmation challenge and step-up TOTP verification.
- All other mutating actions are rejected with HTTP 403 `action_policy_violation`.

---

## 4. Operator Setup & Lifecycle Commands

All external lifecycle operations are managed via the `scripts-remote-control` CLI.

### Step 1: Bootstrap Operator Identity & Two-Factor
If not already enrolled, bootstrap the single operator identity and enroll TOTP:
```powershell
scripts-remote-control bootstrap
```
Scan the generated TOTP provisioning URI or enter the Base32 secret into your authenticator app (Google Authenticator, Aegis, Bitwarden, or 1Password).

### Step 2: Run Read-Only Preflight Health Checks
Run the diagnostic doctor to verify Tailscale installation, login status, Funnel availability, and port readiness:
```powershell
scripts-remote-control external doctor
```
> **Invariant (Mandatory Amendment 2):** `external doctor` is strictly 100% read-only. It inspects configuration and active barriers without mutating state or clearing barriers.

### Step 3: Inspect Configuration Plan (Dry-Run)
Inspect the proposed Funnel and Serve commands and network topology:
```powershell
scripts-remote-control external plan --port 8443 --public-port 8443
```

### Step 4: Operator-Approved Funnel Activation
Activate the Funnel reverse proxy with explicit approval (`-a / --apply`):
```powershell
scripts-remote-control external enable -a --port 8443 --public-port 8443
```
Upon successful execution, the CLI prints the assigned public HTTPS URL (e.g., `https://workstation.tailnet-dev.ts.net:8443`).

### Step 5: Verify Active Status
Inspect current exposure and reachability:
```powershell
scripts-remote-control external status
```

### Step 6: Rollback & Deactivation
To immediately stop public Funnel reachability:
```powershell
scripts-remote-control external disable -a
```
This terminates Funnel ingress while keeping the local loopback server, Telegram bot, and Healthchecks.io monitoring fully operational.
