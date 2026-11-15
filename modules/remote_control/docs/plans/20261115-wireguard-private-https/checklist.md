# Checklist

- [x] Confirm current primary checkout, branch, ancestry and clean status using the repository submodule-ignore fallback.
- [x] Inspect active Remote Control worktrees and preserve them; prepare a dedicated feature worktree.
- [x] Read-only inspect Windows LAN address, adapter/routes, listeners, firewall defaults/rules, proxy and gateway certificate behavior.
- [x] Review Remote Control Host/Origin, forwarded-header, loopback trust, cookie, CSRF, auth and PWA behavior.
- [x] Add private HTTPS Caddy template with dedicated port, specific bind, fail-closed source matcher, loopback-only upstream, forwarded port and disabled automatic system CA trust installation.
- [x] Add proxy-origin regression coverage and test-only isolation of Telegram, Healthchecks and notifications DB secrets/data.
- [x] Update current deployment notes and rollback/status documentation for WireGuard, Group 3A accepted, Group 3B deferred, Funnel unselected.
- [x] Run focused CLI/API/security/proxy tests and full Remote Control suite with module-local temp root and local socket permissions.
- [ ] Obtain verified router endpoint/peer subnet/source-NAT/AllowedIPs and DHCP reservation facts.
- [ ] Validate Caddyfile syntax/TLS SAN when a Caddy binary and final source/address are available.
- [ ] Present exact service/task, bind, Windows Firewall/gateway ACL, certificate trust and rollback commands for operator approval.
- [ ] After approval, install/configure proxy and perform cellular/Android acceptance.
