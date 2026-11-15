# Private WireGuard HTTPS access for Remote Control

**Status:** Prepared, not deployed. Existing WireGuard is the selected transport. Public Tailscale Funnel is not selected for this deployment. Healthchecks Group 3B is operator-deferred and is not a release blocker.

## Design

`Android Chrome → existing WireGuard tunnel → workstation HTTPS :8444 → 127.0.0.1:8443 Remote Control`

Remote Control stays on its default loopback listener. Caddy binds only the workstation's stable private LAN address on TCP 8444 and proxies only to `127.0.0.1:8443`. There is no router WAN port forward, public DNS dependency, or all-interface listener. The Caddy example is at [Caddyfile.wireguard.example](../../modules/remote_control/deployment/Caddyfile.wireguard.example); its source matcher is deliberately set to TEST-NET-1 `192.0.2.1/32`, which should match no real client, until the authorized WireGuard source and stable host address are confirmed.

## Topology facts still required

Observed on this workstation: Wi-Fi `192.168.50.100/24`, DHCP gateway/server `192.168.50.1`; the address reservation is unknown. The running Windows `ProtonVPN` WireGuard adapter (`10.2.0.2`) is not evidence of the home WireGuard endpoint or Android peer subnet. The gateway's TCP 8443 responds, but the certificate presented for `192.168.50.1` does not match the IP. Its configuration was not accessed and TLS verification was not bypassed.

Before deployment, the operator/router must establish:

1. Where the existing WireGuard server runs and the Android peer address(es)/AllowedIPs.
2. That the Android route includes this workstation's private LAN address.
3. Whether packets arrive at Windows with peer source IPs or are source-NATed.
4. A DHCP reservation or other stable assignment for the workstation address.
5. If source-NAT is used, a gateway policy allowing only the authorized peer(s) to workstation TCP 8444 over WireGuard; Windows firewall must then allow only the verified translated source. No whole-LAN allow rule is acceptable.

## Host/origin and session configuration

After selecting a stable address and origin, set these values in the existing Remote Control service environment (do not change the CLI defaults):

```powershell
$env:REMOTE_CONTROL_HOST = '127.0.0.1'
$env:REMOTE_CONTROL_PORT = '8443'
$env:REMOTE_CONTROL_ALLOWED_HOSTS = '<PRIVATE_HTTPS_HOST_OR_IP>'
$env:REMOTE_CONTROL_ALLOWED_ORIGINS = 'https://<PRIVATE_HTTPS_HOST_OR_IP>:8444'
$env:REMOTE_CONTROL_COOKIE_SECURE = '1'
```

Keep `REMOTE_CONTROL_TRUSTED_PROXIES` and `REMOTE_CONTROL_TRUSTED_PROXY_PEERS` at their loopback-only defaults. The reverse proxy is the sole peer allowed to set forwarded headers. Caddy sets `X-Forwarded-Port: 8444` explicitly in the example because its defaults set `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host`, but not the external port. Validate the effective HTTPS port and exact Origin in a staged local test. Never enable Tailscale `external enable` for this design. Existing exact Host/Origin/Referer checks, Argon2id, TOTP/replay defense, Secure `__Host-` session cookies, CSRF checks, revocation and read-only dashboard boundaries stay enabled.

The PWA uses root-relative assets and its service worker does not cache `/api/` or non-GET requests. Verify login, dashboard assets and API behavior at the HTTPS origin before listener activation.

## TLS trust

The proposed Caddy `tls internal` configuration issues a private certificate for the selected IP/hostname. The Caddyfile sets `skip_install_trust` so starting Caddy does not silently add its CA to Windows trust stores. For a SYSTEM task, retrieve only the public root certificate from that service account's Caddy data directory (Windows default `%AppData%\Caddy\pki\authorities\local\root.crt`); never export `root.key`. Trust only that root on Android after approval. Verify the certificate subject alternative name, chain and browser trust on Android Chrome before acceptance. Do not use a certificate warning bypass. Because the Caddy local root may not be trusted by other Android applications, trust/install it only for the intended browser use and record the Android OS trust-store behavior during acceptance.

## Staged checks and deployment gate

Offline/staged validation must confirm Caddy syntax, TLS SAN/chain, backend availability through loopback, exact Host/Origin allowlisting, forwarded HTTPS/effective port, Secure `__Host-` cookies, authentication/TOTP, CSRF rejection, revocation and PWA install/launch. Malicious Host/Origin and attempts to proxy other local service ports must fail. Do not launch a live listener during these checks.

Before live changes, obtain operator approval against a concrete proposal containing the confirmed bind address/port, Windows firewall source(s), any required WireGuard gateway ACL, Android CA trust steps, service/task configuration and exact rollback commands. No network or certificate-store changes have been made as part of preparation.

## Proposed live host changes (not executed)

The current candidate is the observed workstation address `192.168.50.100`, TCP `8444`, Wi-Fi interface, and the existing Remote Control loopback backend `127.0.0.1:8443`. The address is DHCP-assigned and must first be reserved or replaced with a confirmed stable address. Replace the Caddy TEST-NET matcher only with the observed WireGuard client source; set Remote Control host allowlisting to that private host/IP and the one exact origin `https://<private-host-or-ip>:8444`, set `REMOTE_CONTROL_COOKIE_SECURE=1`, and explicitly keep external exposure disabled and proxy peers loopback-only. Remove stale Funnel `REMOTE_CONTROL_PUBLIC_ORIGIN` values from the service's launch environment.

After the source is confirmed and approved, the Windows firewall rule will be narrowly equivalent to:

```powershell
New-NetFirewallRule -DisplayName 'Scripts Remote Control HTTPS (WireGuard)' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress '192.168.50.100' -LocalPort 8444 -RemoteAddress '<confirmed WireGuard source IP or CIDR>' -InterfaceAlias 'Wi-Fi' -Profile Private
```

If WireGuard source NAT is present, `<confirmed WireGuard source IP or CIDR>` becomes the exact translated gateway source, and the router must first restrict that VPN-to-host flow to the authorized peer(s) and TCP 8444. The model-specific router rule cannot be specified until the gateway is identified and its verified configuration is available. Do not apply a rule that permits the full LAN.

The candidate Remote Control process environment is:

```powershell
$env:REMOTE_CONTROL_HOST = '127.0.0.1'
$env:REMOTE_CONTROL_PORT = '8443'
$env:REMOTE_CONTROL_EXTERNAL_EXPOSURE = '0'
Remove-Item Env:REMOTE_CONTROL_PUBLIC_ORIGIN -ErrorAction SilentlyContinue
$env:REMOTE_CONTROL_ALLOWED_HOSTS = '192.168.50.100'
$env:REMOTE_CONTROL_ALLOWED_ORIGINS = 'https://192.168.50.100:8444'
$env:REMOTE_CONTROL_TRUSTED_PROXIES = '127.0.0.1,::1'
$env:REMOTE_CONTROL_TRUSTED_PROXY_PEERS = '127.0.0.1,::1'
$env:REMOTE_CONTROL_COOKIE_SECURE = '1'
scripts-remote-control serve --host 127.0.0.1 --port 8443
```

Substitute the confirmed stable address/origin before use. The existing Remote Control server is currently stopped; starting that loopback-only process for acceptance is a separate, explicit step. No existing Scheduled Task is to be replaced.

The proposed Caddy Scheduled Task name is `ScriptsRemoteControlPrivateHttpsProxy`, running the approved `C:\Program Files\Caddy\caddy.exe` against `C:\ProgramData\ScriptsRemoteControl\Caddyfile` as SYSTEM at startup. After replacing the TEST-NET matcher and installing Caddy only after approval, the proposed task registration is:

```powershell
$caddy = 'C:\Program Files\Caddy\caddy.exe'
$configDir = 'C:\ProgramData\ScriptsRemoteControl'
$config = Join-Path $configDir 'Caddyfile'
& $caddy validate --config $config --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddy configuration validation failed.' }
$action = New-ScheduledTaskAction -Execute $caddy -Argument ('run --config "{0}" --adapter caddyfile' -f $config) -WorkingDirectory $configDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'ScriptsRemoteControlPrivateHttpsProxy' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Private WireGuard HTTPS proxy for Remote Control'
```

This command intentionally omits `-Force`; it fails rather than replacing an existing task. Caddy's SYSTEM-profile CA storage must be persistent and protected. The Caddyfile's `skip_install_trust` prevents silent Windows trust-store changes.

The planned host rollback commands, after installing only the named task and firewall rule, are:

```powershell
Stop-ScheduledTask -TaskName 'ScriptsRemoteControlPrivateHttpsProxy' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'ScriptsRemoteControlPrivateHttpsProxy' -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName 'Scripts Remote Control HTTPS (WireGuard)' -ErrorAction SilentlyContinue
```

Also remove only the newly added peer restriction from the WireGuard gateway and remove the Caddy public root from Android's user certificate store if no longer needed. Restore the prior Remote Control launch environment, then verify `127.0.0.1:8443` remains the only backend listener. These commands are documentation only; they have not been run.

## Rollback

After deployment approval, rollback is: stop/disable only the approved Caddy service/task; remove only its TCP 8444 Windows Firewall rule; remove the corresponding WireGuard gateway ACL if one was added; remove the Android-installed public CA certificate if access is no longer needed; restore the previous Remote Control service environment; verify Remote Control still listens only on `127.0.0.1:8443`. Do not alter the WireGuard tunnel itself, Telegram notification tasks, Resource Coordinator, or Mining.
