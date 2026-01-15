# xinstall + HWiNFO Overlay/Logging - Implementation Plan (LLM-CLI Ready)

This document is written to be pasted into your repo and executed/implemented by an LLM CLI that has contextual access to your codebase and local machine(s). It is intentionally explicit, file- and task-oriented, with acceptance criteria.

---

## Goals

1. **New Python module**: `xinstall`
   - Cross-platform: Windows 11 (PowerShell 7), WSL2 Ubuntu, Termux
   - Very short global CLI command: `xi`
   - Quickly answers:
     - "Is tool X installed? From where? How to upgrade?"
     - "What installers exist on this machine?"
   - Safely installs tools:
     - chooses **best installer** per OS + tool
     - if it fails, **falls back** to 2nd/3rd best
     - prevents "shadow installs" (warn + Y/N prompt) when a tool is already managed by a package manager
   - Maintains per-machine notebook:
     - **Versioned**: "best known installers for tools" (manifest, docs)
     - **Local only**: actual machine state logs/receipts (gitignored by default)

2. **Curated PC telemetry overlay** (less noise than raw HWiNFO)
   - Easy toggle on/off
   - Two curated profiles: "Gaming" + "Desktop/Stability"
   - Graphs preferred; not 30 per-core metrics

3. **24/7 logging** of *all* HWiNFO sensor stats
   - Boot  shutdown continuous logging
   - File rotation strategy
   - "Data lake ready" for ML later

---

## High-level architecture

### A) `xinstall` module responsibilities
- Detect platform and environment:
  - windows / linux / termux
- Detect available installers:
  - Windows: winget, scoop, choco
  - Linux/WSL: apt, dnf, pacman, brew
  - Termux: pkg
  - Python tool managers: pipx, uv
  - Language tool managers (optional now, extend later): cargo, go, asdf
- Tool "status":
  - detect path, version, and best-effort "owner"
  - recommend upgrade commands
- Tool "install":
  - use a manifest to pick primary/fallback installers
  - install missing installers when allowed (with `--apply`)
  - verify tool is on PATH after install
- Notebook state:
  - local receipts + installed record per host
  - markdown summary per host

### B) HWiNFO overlay + logging responsibilities
- Overlay:
  - either HWiNFO built-in OSD (quick) OR HWiNFO  RTSS/Afterburner overlay (more flexible)
  - curated metrics list with two profiles, toggleable
- Logging:
  - HWiNFO Pro supports command-line auto-logging; use Task Scheduler at boot
  - output path per host, per boot session
  - rotate/compress + optional convert to Parquet nightly

---

## Repo layout for the new module

Create a new top-level package repo folder (or subfolder inside your mono-repo-LLM CLI should adapt paths accordingly).

### Target folder hierarchy
```text
xinstall/
ÃÄÄ pyproject.toml
ÃÄÄ README.md
ÃÄÄ CHANGELOG.md
ÃÄÄ .gitignore
ÃÄÄ src/
³   ÀÄÄ xinstall/
³       ÃÄÄ __init__.py
³       ÃÄÄ __main__.py
³       ÃÄÄ cli.py
³       ÃÄÄ platform.py
³       ÃÄÄ runners/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ exec.py
³       ³   ÀÄÄ which.py
³       ÃÄÄ installers/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ base.py
³       ³   ÃÄÄ registry.py
³       ³   ÃÄÄ planner.py
³       ³   ÃÄÄ windows/
³       ³   ³   ÃÄÄ __init__.py
³       ³   ³   ÃÄÄ winget.py
³       ³   ³   ÃÄÄ scoop.py
³       ³   ³   ÀÄÄ choco.py
³       ³   ÃÄÄ linux/
³       ³   ³   ÃÄÄ __init__.py
³       ³   ³   ÃÄÄ apt.py
³       ³   ³   ÃÄÄ dnf.py
³       ³   ³   ÃÄÄ pacman.py
³       ³   ³   ÀÄÄ brew.py
³       ³   ÃÄÄ termux/
³       ³   ³   ÃÄÄ __init__.py
³       ³   ³   ÀÄÄ pkg.py
³       ³   ÀÄÄ python_tools/
³       ³       ÃÄÄ __init__.py
³       ³       ÃÄÄ pipx.py
³       ³       ÃÄÄ uv.py
³       ³       ÀÄÄ pip_user.py
³       ÃÄÄ manifest/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ model.py
³       ³   ÃÄÄ load.py
³       ³   ÀÄÄ defaults.py
³       ÃÄÄ inventory/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ state_store.py
³       ³   ÃÄÄ receipts.py
³       ³   ÀÄÄ notebook.py
³       ÀÄÄ util/
³           ÃÄÄ __init__.py
³           ÃÄÄ prompts.py
³           ÀÄÄ text.py
ÃÄÄ docs/
³   ÃÄÄ manifest/
³   ³   ÃÄÄ tools.yaml
³   ³   ÀÄÄ README.md
³   ÃÄÄ guide/
³   ³   ÃÄÄ INSTALL.md
³   ³   ÃÄÄ USAGE.md
³   ³   ÃÄÄ MANIFEST.md
³   ³   ÀÄÄ TROUBLESHOOTING.md
³   ÀÄÄ state/
³       ÃÄÄ README.md
³       ÃÄÄ installed/
³       ³   ÀÄÄ .gitkeep
³       ÀÄÄ receipts/
³           ÀÄÄ .gitkeep
ÃÄÄ scripts/
³   ÃÄÄ bootstrap_install.ps1
³   ÀÄÄ bootstrap_install.sh
ÀÄÄ tests/
    ÃÄÄ test_cli_basic.py
    ÃÄÄ test_manifest.py
    ÃÄÄ test_planner_fallback.py
    ÀÄÄ test_state_store.py
```

---

## `pyproject.toml` requirements (must-haves)

- Use `src/` layout.
- Installable package name: `xinstall`
- Console script: `xi`
- Dependencies:
  - Keep minimal; prefer stdlib.
  - If using YAML, decide:
    - Option A: vendor a tiny YAML parser (not recommended)
    - Option B: depend on `PyYAML` (recommended for practicality)
- Python version: choose whatever your ecosystem uses (>=3.10 recommended).
- Add `pytest` for tests.

---

## CLI spec (must implement exactly)

### Global command
- `xi`

### Commands
1. `xi doctor`
   - prints OS detection + available installers and versions
   - prints primary Python location + PATH notes
   - output should be readable and concise

2. `xi installers list`
   - show detected installers
   - include versions when possible

3. `xi tool status <tool>`
   - show:
     - resolved executable path(s)
     - version (best effort)
     - detected "owner" manager candidates
     - recommended upgrade command(s)
   - must handle:
     - command != package name (e.g., `rg` command, `ripgrep` package)

4. `xi tool install <tool>`
   - if installed: print recommended upgrade method and exit 0 (unless `--reinstall`)
   - if missing:
     - choose best installer for this OS/tool from manifest
     - if installer missing: propose installing installer (or do so with `--apply`)
     - execute install only with `--apply`
     - on failure: fallback to next installer in chain automatically (with clear logging)
   - after install: verify tool is on PATH
   - record receipt + update notebook state

5. `xi tool ensure`
   - reads manifest "default toolset" (optional section)
   - installs missing tools using same fallback logic

### Global flags
- `-a, --apply`  actually execute; otherwise plan-only
- `-y, --yes`  assume yes for prompts
- `-v, --verbose`
- `-r, --root_dir <path>`  override notebook location (default is local docs/state + per-host)

---

## Manifest format: `docs/manifest/tools.yaml`

This is the core "best known installer map" that is **versioned**.

### Requirements
- Each tool entry must include:
  - `command`: the executable name (e.g., `rg`)
  - `tool`: canonical tool name (e.g., `ripgrep`)
  - per-platform installer chains:
    - `windows`: [`winget`, `choco`, `scoop`, `cargo`, `pipx`, `uv`, `manual`]
    - `linux`: [`apt`, `brew`, `pipx`, `uv`, `cargo`, `manual`]
    - `termux`: [`pkg`, `cargo`, `pipx`, `uv`, `manual`]
  - per-installer package identifiers:
    - winget id (optional): `BurntSushi.ripgrep`
    - apt name (optional): `ripgrep`
    - pkg name (optional): `ripgrep`
    - brew formula name, etc.

### Notes for the LLM CLI
- Start with a curated list of the tools you actually care about (20-50). Expand later.
- Include fallback chain for each tool.
- Include "notes" field explaining exceptions (ex: Ubuntu `fd` package is `fd-find`).

---

## Notebook / State tracking (local-only by default)

### Purpose
- Track what **this machine** installed and via which manager.
- Track receipts for each action (install/upgrade/reinstall).
- Keep a readable markdown summary.

### Local directory
Default should be inside the module folder:

- `xinstall/docs/state/installed/<os>__<hostname>.json`
- `xinstall/docs/state/installed/<os>__<hostname>.md`
- `xinstall/docs/state/receipts/<timestamp>__<tool>__<action>.json`

### Git behavior
- `docs/manifest/**` should be tracked.
- `docs/state/installed/*` and `docs/state/receipts/*` should be gitignored by default.

---

## Fallback install strategy (must implement)

### General algorithm
Given a tool `T`:

1. Resolve `command` and `package ids` from manifest.
2. Detect if installed:
   - `which` / `Get-Command`
   - detect version
   - detect likely manager(s)
3. If installed:
   - show upgrade commands and exit 0 (unless `--reinstall`)
4. If missing:
   - iterate installers in priority order (manifest chain)
   - for each installer:
     - ensure installer exists; if missing:
       - generate plan to install it
       - if `--apply`, do it (prompt unless `--yes`)
     - attempt install
     - verify tool now resolves on PATH
     - if success:
       - record receipt + update installed notebook
       - exit 0
     - if failure:
       - record failure receipt and continue to next fallback
5. If all fail: exit nonzero with a clear error summary and next steps.

### "Optimal" ordering guidelines (baseline)
- Windows:
  1) winget (first, if tool exists there)
  2) scoop
  3) choco
  4) uv tool install (for python CLIs)
  5) pipx (for python CLIs)
  6) cargo (for rust CLIs)
  7) manual (only with warning)
- WSL2 Ubuntu:
  1) apt
  2) brew (linuxbrew)
  3) uv
  4) pipx
  5) cargo
  6) manual
- Termux:
  1) pkg
  2) cargo
  3) uv
  4) pipx
  5) manual

---

## Shadow-install guardrails (must implement)

### Problem
User tries to "manual install" a tool that is already managed by winget/brew/apt/pipx/etc, causing duplicates and PATH conflicts.

### Required behavior
- Before installing via a method `M`:
  - run `xi tool status <tool>`
  - if it's already installed and managed by a different manager with high confidence:
    - warn loudly
    - require Y/N prompt (unless `--yes`)
- "High confidence" detection examples:
  - Windows winget shim path: `%LOCALAPPDATA%\Microsoft\WinGet\Links\...`
  - Termux prefix: `/data/data/com.termux/files/usr/bin/...`
  - apt ownership: `dpkg -S <path>`
  - pacman ownership: `pacman -Qo <path>`
  - brew: `brew which <cmd>`

---

## Packaging + installation of `xi` itself

### Bootstrap scripts (for each machine)
Create:
- `scripts/bootstrap_install.ps1` (Windows PowerShell 7)
- `scripts/bootstrap_install.sh` (WSL2 Ubuntu + Termux)

Required behavior:
1. Detect best method to install `xinstall` itself:
   - pipx if available (or install pipx in user scope)
   - else uv (or install uv in user scope)
   - else pip --user
2. Install `xinstall` (editable dev mode if from local repo, or normal install if packaged)
3. Ensure `xi` is on PATH:
   - pipx ensurepath / uv tool path considerations
   - print "restart shell needed" message if required

**Links**
- pipx: https://pypa.github.io/pipx/
- uv: https://docs.astral.sh/uv/

---

## Tests (must implement)

Use `pytest`.

Minimum tests:
1. `test_manifest.py`
   - loads `docs/manifest/tools.yaml`
   - validates required fields
   - checks that fallback chain is non-empty

2. `test_planner_fallback.py`
   - mocks installer failures and confirms fallback order continues
   - verifies "first success stops chain"

3. `test_state_store.py`
   - writes receipt + installed record to temp dir
   - ensures markdown notebook generated

4. `test_cli_basic.py`
   - `xi doctor` returns 0
   - `xi tool status rg` handles command/package mismatch via manifest

---

## Implementation steps (LLM CLI task list)

### Phase 1 - Scaffold + CLI
- [ ] Create folder hierarchy above
- [ ] Add `pyproject.toml` with `xi` console script
- [ ] Implement `xi doctor`, `xi installers list`
- [ ] Implement platform detection (windows/linux/termux)

Acceptance criteria:
- `python -m xinstall doctor` works
- `xi doctor` works after install
- `xi installers list` lists at least: winget/apt/pkg/pipx/uv if present

### Phase 2 - Manifest + tool status
- [ ] Add `docs/manifest/tools.yaml` with a starter set (include `rg/ripgrep`)
- [ ] Implement manifest loader
- [ ] Implement `xi tool status <tool>`:
  - which/path
  - version
  - ownership candidates
  - recommended upgrade command(s)

Acceptance criteria:
- `xi tool status rg` prints winget candidate if the executable path is in WinGet Links
- `xi tool status ripgrep` should suggest `rg` if manifest uses that mapping (optional nice-to-have)

### Phase 3 - Install planner + fallbacks
- [ ] Implement installer registry (each installer provides: detect, install_tool, upgrade_tool, uninstall_tool)
- [ ] Implement `xi tool install <tool>` with:
  - plan-only by default
  - `--apply` executes
  - fallbacks on failure
- [ ] Add receipts and installed notebook updates

Acceptance criteria:
- If primary installer is missing, `xi tool install` prints a plan to install it (or uses fallback)
- Failures do not stop the whole process unless:
  - user declines prompt
  - a non-recoverable error occurs

### Phase 4 - Guardrails
- [ ] Implement `xi tool guard <tool> --method manual|...`
- [ ] Integrate guardrail into install flow automatically

Acceptance criteria:
- Attempting manual install of a winget-managed tool triggers warning + prompt

### Phase 5 - Documentation
- [ ] docs/guide/INSTALL.md (bootstrap steps)
- [ ] docs/guide/USAGE.md (common workflows)
- [ ] docs/guide/MANIFEST.md (how to add tools + fallbacks)

Acceptance criteria:
- A new machine can be bootstrapped using only these docs + scripts

---

# HWiNFO Overlay + 24/7 Logging Plan (Windows 11)

This is separate from `xinstall` but should be documented so an LLM can set it up.

## A) Curated overlay options

### Option 1: HWiNFO built-in OSD (quickest)
- Use HWiNFO's built-in OSD/overlay to show a small curated set.
- Keep two profiles by saving settings/config if supported; otherwise use RTSS for profiles.

HWiNFO: https://www.hwinfo.com/

### Option 2 (recommended): HWiNFO  RTSS / MSI Afterburner overlay
- Install:
  - MSI Afterburner (bundles RTSS)
  - Configure RTSS overlay editor
  - Use HWiNFO sensors  RTSS overlay output
- Toggle overlay with hotkeys in RTSS/Afterburner.
- Create two profiles:
  1) "Gaming"
  2) "Desktop/Stability"

MSI Afterburner: https://www.msi.com/Landing/afterburner
RTSS info: https://www.guru3d.com/files-details/rtss-rivatuner-statistics-server-download.html

## B) Curated metric sets

### Gaming overlay (8-10 items)
- FPS + Frametime (ms)
- GPU Utilization (%)
- GPU Temperature (or Hotspot)
- GPU Power (W)
- VRAM Used (GB)
- CPU Package Temp
- CPU Package Power (W)
- RAM Used (GB)
- Optional:
  - GPU Fan %
  - SSD temp (if your NVMe runs hot)

### Desktop/Stability overlay (6-8 items)
- CPU package temp + power
- GPU temp + power
- RAM used
- SSD temp
- Optional:
  - Fan speeds
  - Network up/down

Implementation note:
- Don't graph per-core clocks in overlay.
- If you need per-core for analysis, log it-don't display it.

---

## C) 24/7 "log everything" setup (boot  shutdown)

### Requirements
- Prefer HWiNFO Pro if you want unattended CLI-based start of logging at boot.
- Create folder:
  - `C:\HWiNFOLogs\<COMPUTERNAME>\`
- Log file naming:
  - `HWiNFO__<COMPUTERNAME>__<YYYYMMDD-HHMMSS>__boot.csv`

### Task Scheduler (Windows)
Create a scheduled task:
- Trigger: At startup
- Run with highest privileges
- Action:
  - Start HWiNFO sensors with command-line flags:
    - start sensors automatically
    - start logging automatically to the desired file path
    - poll rate (e.g., 1000-2000ms)
- Ensure the task runs even if no user is logged in (optional; depends on your needs)

Rotation strategy:
- Simple: one file per boot session
- Advanced (later):
  - daily rollovers
  - compress old CSV
  - convert to Parquet nightly for ML

---

## D) Data engineering plan for ML later

### 1) Storage layout
- Raw CSV logs:
  - `C:\HWiNFOLogs\<HOST>\raw\HWiNFO__<HOST>__<timestamp>.csv`
- Processed:
  - `C:\HWiNFOLogs\<HOST>\parquet\date=YYYY-MM-DD\...`

### 2) Conversion pipeline (nightly job)
- Read CSV
- Normalize headers
- Add columns:
  - host
  - session_id (boot timestamp)
  - timestamp parsed
- Write Parquet (partition by date)

### 3) Modeling ideas
- workload classification (idle / gaming / encode / compile)
- anomaly detection (thermals, fan failures, sudden power spikes)
- forecasting and correlation:
  - GPU power vs FPS
  - CPU package power vs CPU temps vs throttling

---

## E) Optional: Grafana dashboards (best graphs)
If you want real dashboards, consider:
- Prometheus + Grafana
- Adapter that exposes HWiNFO sensor data to Prometheus
- Then build curated dashboards

Grafana: https://grafana.com/
Prometheus: https://prometheus.io/

---

# "Done when" checklist

## xinstall / xi
- [ ] `xi doctor` prints OS and installer list
- [ ] `xi tool status rg` shows correct path and upgrade recommendation
- [ ] `xi tool install <tool>` plans by default, installs with `--apply`
- [ ] Fallback works automatically when primary fails
- [ ] Per-host notebook written to `docs/state/installed/*` and gitignored
- [ ] Tests pass via `pytest`

## HWiNFO
- [ ] Overlay can be toggled on/off with hotkey
- [ ] "Gaming" and "Desktop/Stability" profiles exist
- [ ] Boot-to-shutdown logging produces per-boot files
- [ ] Logs are organized per-host and ready for later ETL

---

# Notes for the LLM CLI implementing this

- Keep the first implementation minimal and robust:
  - winget + apt + pkg + pipx + uv are enough to cover most use-cases.
  - scoop/choco/brew/cargo can be added incrementally.
- Avoid interactive installers unless user passes `--apply --yes`.
- Always record receipts (success and failure).
- Treat "installers missing" as non-fatal; use fallback chain.
- Ensure all CLI args have both short + long forms.

End of document.
