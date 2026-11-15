# H4 VM Staging Snapshot (`XERES`)

This directory is a tracked repository snapshot of the **scripts, checksum manifests, and non-binary evidence** staged on host **`XERES`** at `C:\H4-VM-Staging\`.

> **Purpose:** Allow handoff-authoring and reviewing agents to inspect the exact staged PowerShell scripts, bundle/wheel checksum manifests, and live qualification evidence in-repo without requiring direct filesystem access to `C:\H4-VM-Staging\`.
>
> **Canonical source vs. staged snapshot:** The canonical, tested source files live in `modules/resource_coordinator/tools/h4_qualification/`. Whenever a script is updated and restaged to `C:\H4-VM-Staging\`, this snapshot can be refreshed to match.

---

## Snapshot Contents & Live `XERES` Paths

### 1. Staged PowerShell Scripts (`scripts/`)

| Snapshot Path | Live Path on `XERES` | Canonical Source in Repo | Role |
| :--- | :--- | :--- | :--- |
| `scripts/Invoke-H4GuestQualification.ps1` | `C:\H4-VM-Staging\Invoke-H4GuestQualification.ps1` | `modules/resource_coordinator/tools/h4_qualification/Invoke-H4GuestQualification.ps1` | Host-side Hyper-V / PowerShell Direct orchestrator (`Preflight`, `Setup`, `Checkpoint`, `Acceptance`) |
| `scripts/Bootstrap-H4GuestBundle.ps1` | `C:\H4-VM-Staging\Bootstrap-H4GuestBundle.ps1` | `modules/resource_coordinator/tools/h4_qualification/Bootstrap-H4GuestBundle.ps1` | Standalone trusted bundle verifier & extractor |
| `scripts/Provision-H4TestVM.ps1` | `C:\H4-VM-Staging\Provision-H4TestVM.ps1` | `modules/resource_coordinator/tools/h4_qualification/Provision-H4TestVM.ps1` | Disposable Windows 11 Hyper-V VM provisioning script (`RC-H4-Windows-Acceptance`) |

### 2. Checksum Manifests & Build Receipts (`manifests/`)

| Snapshot Path | Live Path on `XERES` | Role |
| :--- | :--- | :--- |
| `manifests/wheels-sha256.txt` | `C:\H4-VM-Staging\guest-deps\wheels-sha256.txt` | SHA-256 manifest for all offline Python wheels in `C:\H4-VM-Staging\guest-deps\wheels\` |
| `manifests/bundle-rc1-v3.build-receipt.json` | `C:\H4-VM-Staging\bundle-rc1-v3\build-receipt.json` | Build receipt for the pinned v3 H4 acceptance archive |
| `manifests/bundle-rc1-v3.h4-windows-acceptance.zip.sha256` | `C:\H4-VM-Staging\bundle-rc1-v3\h4-windows-acceptance.zip.sha256` | Recorded SHA-256 digest file for `h4-windows-acceptance.zip` |

### 3. Live Qualification Evidence (`evidence/`)

| Snapshot Path | Live Path on `XERES` | Contents |
| :--- | :--- | :--- |
| `evidence/20261115-143723-e58eb8ae/final-summary.json` | `C:\H4-VM-Staging\evidence\20261115-143723-e58eb8ae\final-summary.json` | Summary of the first live `-Stage All` run (`Preflight: PASS`, `Setup: PASS`, failed entering `Checkpoint` on `Stop-VM -Id` before the `-VM` fix) |
| `evidence/20261115-143723-e58eb8ae/guest-identity.json` | `C:\H4-VM-Staging\evidence\20261115-143723-e58eb8ae\guest-identity.json` | Verified guest identity (`DESKTOP-1ITSJV0`, Windows 11 Pro Build 26300, Hyper-V VM, clean RC baseline) |
| `evidence/20261115-143723-e58eb8ae/guest-preflight-raw.json` | `C:\H4-VM-Staging\evidence\20261115-143723-e58eb8ae\guest-preflight-raw.json` | Raw guest preflight JSON output |
| `evidence/20261115-143723-e58eb8ae/guest-setup.json` | `C:\H4-VM-Staging\evidence\20261115-143723-e58eb8ae\guest-setup.json` | Offline Python/pwsh verification, wheelhouse install log, and guest setup receipt path (`C:\H4-Guest-Work\receipts\setup-20261115-143723-e58eb8ae.json`) |

---

## Large Binary / VM Directories on `XERES` (Not Committed)

These assets remain only on `XERES` due to binary size and machine-local VM state:

- `C:\H4-VM-Staging\bundle-rc1-v3\h4-windows-acceptance.zip` — Pinned v3 H4 acceptance archive (`SHA-256: DAAF9A7B7BD5534A17541F49660360C060A2BA3DF946DBDDCA46E6B63797E7FE`)
- `C:\H4-VM-Staging\guest-deps\installers\python-3.12.10-amd64.exe` — Offline Python 3.12.10 installer (`SHA-256: 67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB`)
- `C:\H4-VM-Staging\guest-deps\installers\PowerShell-7.6.10-win-x64.msi` — Offline PowerShell 7.6.10 MSI (`SHA-256: 7D8DAEA48B450D4D62FCD1AC4D6FAA7AC2DB5E11ABA5061EE81B7496ADCA8C07`)
- `C:\H4-VM-Staging\guest-deps\wheels\` — Offline Python wheelhouse verified by `wheels-sha256.txt`
- `C:\H4-VM-Staging\RC-H4-Windows-Acceptance\` — Hyper-V VM configuration and VHDX storage for `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`)
- `C:\H4-VM-Staging\bundle\`, `C:\H4-VM-Staging\bundle-rc1-task-fix\`, `*.bak-*` — Earlier superseded staging directories and backup files
