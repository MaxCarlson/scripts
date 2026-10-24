# Unified UI Read-Only Web Implementation Plan

## Goal

Provide reusable local ASGI/static browser infrastructure and a secure, read-only runmux process and output dashboard.

## Architecture

`web_ui_tools` owns a small FastAPI/Starlette service, static asset hosting, explicit router mounting, and single-user local authentication. Runmux owns its adapter, reads its existing registry through SQLite read-only mode, and uses only status IPC plus bounded log reads. The frontend is an application-specific plain JavaScript view with a safe text-only output renderer.

## Constraints

- No web dependency on ordinary runmux CLI invocation.
- No registry initialization, migrations, pruning, process termination, input attachment, or lifecycle calls from browser GETs or web shutdown.
- Full immutable run IDs only; response metadata is an allowlist.
- Loopback bind only; terminal-issued login code exchanged for opaque HttpOnly session cookie; exact trusted host/origin checks.
- Runmux output chunks are bounded; incremental UTF-8 decoding preserves split code points; terminal escape/control sequences are removed before safe text rendering.
- Test only temporary registries and disposable processes.

## Tasks

1. [x] Implemented and tested the independent `web_ui_tools` app factory, static delivery, explicit route mounting, local auth, host/origin checks, Uvicorn shutdown, and executable non-runmux sample.
2. [x] Implemented and tested runmux read-only registry access, transient status projection, metadata allowlist, exact IDs, bounded output cursors, rotation detection, and terminal/UTF-8 safety.
3. [x] Implemented and tested the optional `runmux web` CLI path and application-owned dashboard with process list, inspector, incremental output, and empty/error/disconnected states.
4. [x] Ran focused tests and lint, syntax-checked frontend JS, visually smoke-tested the local dashboard, and recorded clean-main baseline failures and remaining packaging/manual validation in `STATUS.md`.
