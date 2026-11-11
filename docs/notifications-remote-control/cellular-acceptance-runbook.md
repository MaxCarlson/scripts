# Android Cellular Acceptance Test Runbook (Phase 08)

**Document Version:** 1.0.0  
**Phase:** Phase 08 — Public HTTPS Readiness, Funnel Lifecycle, and Final Action-Safety Gates  
**Module:** `modules/remote_control`  
**Repository:** `MaxCarlson/scripts`  

---

## 1. Overview & Test Environment Setup

This runbook defines reproducible end-to-end verification procedures for testing the Remote Control Progressive Web Application (PWA) over a live Android cellular data network (LTE / 5G).

### Test Matrix Scope
- **Test ID W01:** Internet exposure & unauthenticated access boundary.
- **Test ID W02:** Internet isolation & subsystem protection.
- **Test ID W03:** Phone cellular PWA installation & authenticated lifecycle.
- **Test ID W04:** Remote device & session revocation from local console.
- **Test ID W05:** External rollback & fail-closed decoupling.

### Handset Pre-Conditions
1. **Cellular Network Only:** The Android device must be connected exclusively via cellular mobile data (LTE/5G).
2. **Wi-Fi Disabled:** Disable Wi-Fi in Android system settings.
3. **VPN Disabled:** Disconnect any active WireGuard, Tailscale, or third-party VPN tunnels on the phone.
4. **Browser:** Google Chrome for Android (standard or Canary).

### Host Pre-Conditions
1. Workstation is logged in and running `scripts-remote-control serve` on `127.0.0.1:8443`.
2. Tailscale Funnel is enabled via `scripts-remote-control external enable -a`.
3. Operator has enrolled credentials and TOTP via `scripts-remote-control bootstrap`.

---

## 2. Test Execution Procedures

### Test Case W01: Internet Exposure & Authentication Boundary

#### Objective
Verify that unauthenticated internet clients and malformed requests cannot access operational data or bypass security controls.

#### Execution Steps
1. On the Android handset, open Chrome in Incognito mode.
2. Navigate directly to the public API endpoint:
   ```text
   https://<node>.<tailnet>.ts.net:8443/api/summary
   ```
3. **Expected Result:**
   - Server returns HTTP 401 Unauthorized with JSON body: `{"detail": "Authentication required"}`.
   - Zero sensitive incident data, system metrics, or configuration paths are returned.
4. Using an HTTP client or curl from an external WAN IP, attempt sending spoofed forwarded headers:
   ```bash
   curl -i -k -H "Host: evil.com" -H "X-Forwarded-Host: evil.com" \
     https://<node>.<tailnet>.ts.net:8443/
   ```
5. **Expected Result:**
   - Server rejects the request with HTTP 400 Bad Request due to host validation failure.

---

### Test Case W02: Internet Isolation & Subsystem Protection

#### Objective
Verify that the public Funnel proxy strictly exposes the Remote Control PWA and provides no path to other workstation services.

#### Execution Steps
1. In Android Chrome, attempt accessing internal routes:
   - Resource Coordinator raw port / path: `https://<node>.<tailnet>.ts.net:8443/coordinator/`
   - Runmux supervisor: `https://<node>.<tailnet>.ts.net:8443/runmux/`
   - Broker administrative endpoints: `https://<node>.<tailnet>.ts.net:8443/api/broker/`
2. **Expected Result:**
   - All attempts return HTTP 404 Not Found.
   - No direct network connection to port 1235, Runmux sockets, or broker IPC is established.
3. Authenticate as operator and attempt invoking an unauthorized or non-acknowledged mutating action via `/api/v1/actions/prepare`:
   ```json
   {
     "action_id": "system.reboot",
     "arguments": {}
   }
   ```
4. **Expected Result:**
   - Server returns HTTP 404 Action Not Registered or HTTP 403 `action_policy_violation`.

---

### Test Case W03: Phone Cellular PWA Installation & Authenticated Lifecycle

#### Objective
Verify that the PWA can be installed on Android, navigates securely over HTTPS, and renders operational status.

#### Execution Steps
1. In Android Chrome, navigate to `https://<node>.<tailnet>.ts.net:8443`.
2. Enter Operator Username and Password, tap **Next**.
3. When prompted, enter the current 6-digit TOTP code from your authenticator app.
4. Verify successful authentication and redirection to the dashboard summary view (`/#/dashboard`).
5. Open Chrome menu (three vertical dots) and tap **Add to Home screen** or **Install app**.
6. Confirm installation of **Scripts Remote Control**.
7. Close Chrome, navigate to the Android home screen, and tap the installed **Remote Control** icon.
8. **Expected Result:**
   - PWA launches in full standalone mode (without browser address bar or navigation buttons).
   - Session persists seamlessly; user is directly on the dashboard overview.
   - Status indicators display active notifications health, observer connection, and recent incident cards.
   - Service Worker caches shell assets (`/static/app.js`, `/static/style.css`, `/static/manifest.json`), while all `/api/*` data is fetched strictly live from the network.

---

### Test Case W04: Remote Device & Session Revocation from Local Console

#### Objective
Verify that revoking a session or device from the Windows workstation immediately terminates public mobile access.

#### Execution Steps
1. On the Windows workstation console, inspect active sessions:
   ```powershell
   scripts-remote-control status
   ```
2. Identify the active session ID for the Android handset.
3. Revoke the session:
   ```powershell
   scripts-remote-control revoke-session --session-id <session_id>
   ```
4. On the Android handset, tap **Refresh** or attempt navigating between dashboard tabs.
5. **Expected Result:**
   - API request immediately returns HTTP 401 Unauthorized.
   - PWA client invalidates local state and redirects to the login screen.
   - Subsequent login attempts require full re-authentication (password + TOTP).

---

### Test Case W05: External Rollback & Fail-Closed Decoupling

#### Objective
Verify that disabling Tailscale Funnel instantly removes public internet reachability without disrupting local notification services.

#### Execution Steps
1. On the Windows workstation console, disable the Funnel:
   ```powershell
   scripts-remote-control external disable -a
   ```
2. On the Android handset (cellular data), tap Refresh in the PWA.
3. **Expected Result:**
   - Browser displays connection failure / server unreachable (`ERR_CONNECTION_REFUSED` or `ERR_TIMED_OUT`).
   - The public HTTPS endpoint is completely closed to the internet.
4. On the Windows workstation, verify local monitoring health:
   ```powershell
   scripts-notify status
   scripts-remote-control status
   ```
5. Trigger a synthetic notification:
   ```powershell
   scripts-notify emit --event-type test.ping --severity info --title "Rollback Test" --message "Local notification delivery check"
   ```
6. **Expected Result:**
   - Windows desktop toast notification is displayed.
   - Telegram bot delivers the notification to the operator channel.
   - Healthchecks.io heartbeats continue reporting healthy host status.
   - Disabling public exposure has zero adverse impact on local and outbound monitoring.
