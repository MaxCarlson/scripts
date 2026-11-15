# Remote Control — Authenticated Mobile Dashboard & PWA (Phase 06)
<!-- version: 0.1.0 -->

## Overview
`remote_control` is a dedicated, secure web application providing a responsive mobile PWA dashboard for the `scripts` repository.

It allows operators to monitor notifications, incident lifecycles, provider health, and workstation heartbeat status from a standard mobile browser (Android Chrome), with strong single-operator authentication (Argon2id + TOTP) and zero dependencies on paid cloud services.

## Key Properties
- **Strict Read-Only Boundary:** The dashboard inspects state but exposes NO arbitrary shell commands, CLI execution, process launching, or Resource Coordinator mutations.
- **Fail-Closed Authentication:** Strong Argon2id password hashing, RFC 6238 TOTP two-factor authentication, secure session cookies, server-side session revocation, and brute-force rate-limiting.
- **Mobile PWA:** Installable web application shell with standalone manifest and offline detection. Static assets are cached; authenticated incident data is never stored in service worker caches.
- **Decoupled Architecture:** Operates with complete independence from `modules/resource_coordinator/`. If Resource Coordinator is absent, the dashboard remains 100% functional and reports clean degraded status.
- **Private Reverse-Proxy Boundary:** The application remains loopback-bound by default (`127.0.0.1:8443`). For the selected deployment, existing WireGuard reaches a private HTTPS reverse proxy that connects only to this loopback upstream; the proxy peer remains loopback-trusted and application Host/Origin, authentication, CSRF and session protections stay enabled. Public Tailscale Funnel is not selected.
