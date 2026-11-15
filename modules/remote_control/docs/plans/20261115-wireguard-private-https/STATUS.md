# Private WireGuard Remote Control HTTPS

**Status:** Local implementation and tests complete; awaiting topology facts and operator approval for host changes
**Branch:** `feature/remote-control-wireguard-private-https-20261115`
**Base:** `origin/main` at `0d29b59c722b998dc84ed80caa1c383f04b2cae9`

## Goal

Prepare private HTTPS access through the existing WireGuard VPN, retaining the Remote Control server on loopback. No service, firewall, router, certificate store, or VPN setting is changed in this work.

## Verified observations

- Windows Wi-Fi currently has `192.168.50.100/24`, DHCP enabled, gateway/DHCP server `192.168.50.1`; reservation/stability is not verified.
- Windows exposes a running ProtonVPN WireGuard adapter at `10.2.0.2`. This does not identify the home WireGuard endpoint or Android peer subnet.
- No workstation listener was found on candidate ports `80`, `443`, `8443`, `8444`, or `9443`; no Caddy service was found.
- Windows firewall profiles are enabled and default inbound action is Block; no rule was found for those candidate ports.
- The gateway refuses HTTPS on 443; TCP 8443 is reachable, but its certificate does not match `192.168.50.1`. No TLS verification bypass or router login was attempted.
- VPN endpoint location, client subnet/routes, source NAT, peer restrictions and DHCP reservation therefore remain unknown.

## Proposed, unapplied design

- Caddy binds only `192.168.50.100:8444`, terminates local-CA HTTPS, and proxies only to `http://127.0.0.1:8443`.
- The example uses `192.0.2.1/32` as a TEST-NET source matcher until the actual authorized WireGuard peer source(s) are verified. Replace it only after the source behavior is known.
- Remote Control remains bound to `127.0.0.1:8443`; the app trusts proxy peers only on loopback.
- Host firewall permits TCP 8444 only from confirmed WireGuard peer source(s). If the gateway source-NATs peers, a WireGuard-interface ACL must restrict authorized peer(s) to this workstation and port; Windows then filters the translated gateway source. Do not permit the whole LAN.
- The Caddy global `skip_install_trust` prevents automatic Windows CA trust changes. Android must explicitly trust the Caddy public root certificate; the private CA key must remain on the workstation.
- Before live changes, verify stable/reserved host addressing and VPN source behavior, then present exact commands/config, certificate import steps, and rollback for approval.

## Validation and next stage

- [x] Inspect worktrees, module contracts, PWA origin behavior and host network state.
- [x] Prepare fail-closed Caddy template and operator deployment/rollback documentation.
- [x] Isolate Remote Control test credentials/data and add regression coverage for external HTTPS Origin port handling.
- [x] Run the full Remote Control suite: 174 tests passed.
- [ ] Obtain missing router/peer/NAT/AllowedIPs/DHCP facts.
- [ ] Validate Caddyfile syntax/TLS SAN and stage backend behavior when Caddy and final address/source facts are available.
- [ ] Present exact service/task, bind, firewall/gateway ACL, certificate trust and rollback commands for operator approval.
- [ ] After approval, configure proxy and validate from Android on cellular with WireGuard connected and disconnected.
