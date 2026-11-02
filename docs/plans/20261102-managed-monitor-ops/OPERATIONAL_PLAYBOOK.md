# LLM Monitor & Agent Benchmark Managed Operations Playbook

**Version:** 1.0.0  
**Target:** Local LLM Monitor & Agent Benchmark Managed Operations  

This playbook provides actionable diagnostic procedures and resolution steps for operators and autonomous agents indexed by stable error codes.

---

## 1. Security Architecture & Threat Model

1. **Same-User Local Trust**:
   - The local control channel assumes trust within the current OS user session.
   - **Windows**: Windows native Named Pipe (`\\.\pipe\llm-monitor-{instance_id}`) configured with an explicit SDDL DACL granting Full Control exclusively to the current user SID and `SYSTEM`. Remote network access is rejected via `PIPE_REJECT_REMOTE_CLIENTS`.
   - **POSIX**: AF_UNIX domain socket created with `0600` permissions inside an owner-only `0700` runtime directory.
2. **Short-Lived Scoped Capabilities**:
   - Capabilities are cryptographically random 256-bit tokens held in-memory only.
   - Lifetime: 120 seconds TTL.
   - Scopes: Read-only inspection (`inference:models:read`, `inference:status:read`, `recording:health:read`, `requests:summary:read`).
   - Mutations strictly forbidden: Any `POST`, `PUT`, `DELETE`, `/auth/*`, or WebSocket requests with capability tokens are rejected with `403 Forbidden`.
3. **Browser Protection**:
   - Strict Origin, Host, browser startup code, and session cookie protections remain untouched.
   - Capability tokens cannot be exchanged for browser cookies.
4. **Secret Scrubbing**:
   - Capability tokens, cookies, and startup codes are scrubbed from serialized descriptors, CLI diagnostics, exception messages, preflight receipts, and subprocess argument vectors.

---

## 2. Stable Error Code Catalog & Resolution Playbook

### `MONITOR_NOT_RUNNING`
- **Cause**: Port is closed and no active descriptor exists.
- **Diagnostic**: `agent-bench suite doctor -f json` reports `status: blocked`, `remedy: START_MANAGED_MONITOR`.
- **Resolution**:
  - For benchmark runs: Authorize automatic single start with `-r/--recover-local`:
    ```powershell
    agent-bench suite plan -c aider-python-10 -a opencode -m openai/qwen38_23GB -L -R content -r
    ```
  - For manual foreground execution:
    ```powershell
    llm-monitor web start -p 8788 --gateway -R content -n
    ```

### `MONITOR_UNMANAGED_LISTENER`
- **Cause**: A service is actively listening on the requested port, but lacks a valid LLM Monitor instance descriptor or fails HMAC challenge.
- **Policy**: **Never terminate or force-kill an unmanaged listener.**
- **Resolution**:
  1. Inspect the occupying process:
     ```powershell
     netstat -ano | findstr :<PORT>
     Get-Process -Id <PID>
     ```
  2. If the listener is an unrelated process, change the target port with `-p/--port` or `-H/--monitor-host-url`.

### `MONITOR_CONFIG_MISMATCH`
- **Cause**: An active LLM Monitor instance is running on the port, but its configuration conflicts with the requested benchmark options (e.g., gateway disabled, or recording mode `off` when `content` requested).
- **Policy**: **Never silently reconfigure or restart an active server.**
- **Resolution**:
  1. Check the active configuration:
     ```powershell
     llm-monitor web status -p <PORT>
     ```
  2. If the active server is idle and owned by you, perform an explicit graceful restart:
     ```powershell
     llm-monitor web restart -p <PORT> --gateway -R content -x
     ```

### `MONITOR_CONTROL_PERMISSION_DENIED` / `DOCKER_PIPE_ACCESS_DENIED`
- **Cause**: The current agent execution context (sandbox, restricted container, or cross-user token) is denied access to local Named Pipes or sockets.
- **Policy**: **Do not repeat the identical denied command.** Context denial is distinct from host service failure.
- **Resolution**:
  1. Execute the command in an approved host PowerShell 7+ console.
  2. Confirm user SID matches the descriptor owner identity:
     ```powershell
     [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
     ```

### `MONITOR_RECORDER_UNHEALTHY`
- **Cause**: The SQLite recorder reports dropped observations (`dropped_count > 0`), write flush errors, or degraded health.
- **Policy**: **Immediately halt benchmark inference to prevent unscored or unrecorded runs.**
- **Resolution**:
  1. Inspect the recorder database:
     ```powershell
     llm-monitor db check -d <DATABASE_PATH>
     ```
  2. Ensure disk volume has sufficient free space and is not locked by external antivirus or file synchronizers.
  3. Restart the monitor with clean database state:
     ```powershell
     llm-monitor web restart -p 8788 --gateway -R content -x
     ```

### `LM_STUDIO_UNREACHABLE` / `MONITOR_ROUTE_INCOMPATIBLE`
- **Cause**: LM Studio is not running, the endpoint refused connection, or the requested model is not loaded in LM Studio.
- **Resolution**:
  1. Verify LM Studio local endpoint:
     ```powershell
     curl http://127.0.0.1:1234/v1/models
     ```
  2. Ensure the model identifier matches the downloaded model in LM Studio.

---

## 3. Approved Host Validation Commands

To perform non-destructive, verified validation from an approved host PowerShell 7+ session:

```powershell
# 1. Non-mutating preflight environment check
agent-bench suite doctor -F -f json

# 2. Inspect active LLM Monitor status
llm-monitor web status -p 8788 -f json

# 3. Dry-run benchmark plan with bounded recovery authorization
agent-bench suite plan -c aider-python-10 -a opencode -m openai/qwen38_23GB -L -R content -r

# 4. Verified test execution across modules
python -m pytest modules/agent_benchmark/tests/suite_doctor_test.py modules/agent_benchmark/tests/suite_recovery_test.py modules/agent_benchmark/tests/adversarial_incident_test.py -q
```
