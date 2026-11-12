# Part 2/3 Integration Review Plan

## Scope

Review the pushed Resource Coordinator Part 2 and Part 3 candidate as one source chain, without changing `main` or production state. The review includes journal transactions and rollback compatibility, startup canonicalization, process-identity classification, recovery fencing and failure ordering, request-evidence semantics, miner lifecycle policy, current Mining H3 compatibility, and the previously deselected timing-sensitive simulated test.

## Pinned inputs

- `scripts/main`: `4f4373d2533e4e0c6bd115eda6623ed65fbadc49`
- Part 2: `19255b2e90b7a8904ddf324856687bc40c5e30d4`
- Part 3: `7230d61e97632f6dfce65a2a9323568ceaf5b5b5`
- Mining master: `deea3e019b35615f4d95e6f510450f7f392fb82a` (read-only)
- V3 SHA-256: `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46`

## Acceptance approach

1. Recheck source ancestry, scope, status, V3 identity, and existing validation evidence.
2. Exercise the Part 3 synchronization failure boundary and concurrent automatic-recovery calls with deterministic fake-backed tests.
3. Load a rollback snapshot produced by Part 3 using the actual v0.14.0 parser.
4. Run the isolated timing-sensitive fake-only test repeatedly.
5. Run the unchanged Mining H3 acceptance tests against the exact review candidate using `run_combined_h3.ps1`. This runner changes only the H3 fixture's in-memory expected RC SHA; it does not edit Mining or its pinned H3 evidence.
6. Run targeted RC regression/static checks, document H4 readiness, and publish an integration-review branch. No mainline update or production operation is in scope.

## Safety boundaries

The H3 runner uses only its authenticated loopback test server on an ephemeral port, fake GPU/restoration observers, a fake Coordinator miner, harmless benign child processes, and isolated temporary journals. The production listener, live miner, GPU, LM Studio, WSL, Scheduled Tasks, and credentials are not used.
