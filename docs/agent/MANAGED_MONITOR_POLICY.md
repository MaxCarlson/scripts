# Managed LLM Monitor & Benchmark Operations Policy

**Scope**: All coding agents (Codex, AGY, Claude Code, and autonomous subagents) interacting with `llm-monitor` and `agent-bench`.

## Core Agent Policy

> Prefer `agent-bench suite doctor -F -f json` and managed `llm-monitor web status` over ad hoc WSL, Docker, port, PID and login troubleshooting. Treat an access failure *in the agent execution context* as distinct from a host service failure. Do not repeat the same denied operation without an observed change in context or permissions. Reuse verified running services, attempt at most the documented bounded local recovery when explicitly authorized, and preserve recordings, processes and run checkpoints. Never bypass browser authentication or expose login codes/cookies, never terminate an unidentified process, and never dispatch benchmark inference without `-x/--execute`.

## Agent Action Guidelines

1. **Preflight First**:
   - Always run `agent-bench suite doctor -f json` (or `llm-monitor web status`) before launching benchmarks or debugging services.
   - Read the structured `monitor-preflight-v1` output and execute the exact recommended action (`START_MANAGED_MONITOR`, `FIX_CONFIGURATION`, `USE_APPROVED_HOST_CONTEXT`, etc.).

2. **Authorization Boundaries**:
   - `agent-bench suite doctor` and `agent-bench suite plan`: strictly read-only diagnostics; **never dispatch inference**.
   - `-r/--recover-local`: explicitly authorizes starting an absent managed LLM Monitor once; does not authorize inference.
   - `-x/--execute`: explicitly authorizes benchmark inference; mandatory for `run` and `resume`.

3. **No Unsafe Mutations**:
   - Never kill or terminate a process without verifying its `instance_id`, `PID`, and `process_create_time` through a verified descriptor.
   - Never silently restart or modify the recording mode (`off`, `metadata`, `content`) of an active server.
   - Never restart Docker Desktop or WSL from an agent context.

4. **Security & Credentials**:
   - Scoped capability tokens are issued in-memory over the local Windows SID Named Pipe or POSIX socket; never log, print, or serialize tokens.
   - Strict browser login codes, cookies, Origin, and Host validation must remain intact.
