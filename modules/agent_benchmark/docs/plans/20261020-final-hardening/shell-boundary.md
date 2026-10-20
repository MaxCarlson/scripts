# Shell boundary decision and acceptance gate

Status: design only; `sandboxed-shell-v1` is unavailable. Requests fail before workspace allocation,
session creation or model transitions. Existing `shell-v1` and `cli-shell-v1` remain lower assurance.
No host fallback is permitted. A read-only Docker image inventory probe failed because the
`dockerDesktopLinuxEngine` named pipe was absent. No daemon was started, image downloaded, model
loaded, or inference submitted.

## Selected boundary to demonstrate

Use a dedicated Linux container/VM for the entire OpenCode worker server, its tools and descendants;
placing only task files in a container does not contain a host OpenCode process. Use a separate
network-disabled verifier container for submitted code. The platform implementation remains deferred
until this real boundary is available and authorized; neither mocks nor this design establish isolation.

- Mount trusted task/protected inputs read-only. Expose only declared deliverables and the versioned
  `.agent-bench-scratch` as writable task locations; bound private temporary/cache locations explicitly.
- Keep hidden verifier assets and authoritative evidence outside the worker. The verifier sees a frozen
  export read-only and only its private outputs writable; worker content cannot replace verifier inputs.
- Expose no host repositories, credentials, Docker socket, OpenCode control sockets or unrelated services.
  Inference must use a narrowly mediated LM Studio endpoint; broad host-network access is prohibited.
  Treat model-server response data as untrusted. Disable other worker egress and all verifier networking.
- Enforce memory/CPU/process/disk limits, nonprivileged identities and capability restrictions. Record
  image/runtime identity, effective mounts, network policy and limits in comparison conditions/evidence.
- Keep evidence collection outside the worker. Verify every owned descendant is quiescent at termination;
  uncertain teardown retains a persistent dispatch hold. Export artifacts only after quiescence and retain
  ignored files, prohibited bytecode and scratch. Never infer compliance from clean Git status.

## Required real tests before enabling

Prove tool/subprocess placement, subprocess environment inheritance (including Python -I/-E/-B), denied
protected and external create/modify/restore attempts, host path/socket/credential/network canaries,
resource limits, deadline/cancellation, export validation and teardown. Deliberate writes remain
observable; cache variables and bytecode suppression are hygiene, not enforcement. Verify submitted
code cannot access/forge authoritative verifier receipts. Demonstrate a compliant strict pass and a
prohibited-write failure or uncertainty using the actual worker AND verifier boundary.

No sandboxed strict-assurance claim is enabled by this delivery.
