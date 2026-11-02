# Specification verification study status

Branch `agent/spec-verification-policy-20261102`; implementation checkpoint `3626ed71` and follow-up changes in this worktree. No inference or scored trials were run.

The suite has a repository-owned OpenCode v1 route, frozen SV0/SV1 policy provenance, policy digest checking, persisted template verification, requested native web-tool denial, repetition and seed metadata, and an offline test-activity review helper. Benchmark Core has an explicit prompt intervention comparison gate. These changes need the current branch commit and runtime qualification.

The exploratory 18-trial order and limitations are in `../../spec-verification-study.md`. Dataset revision is pinned, but content and verifier hashes, effective settings, model-file identity, native web-tool enforcement and network isolation are not established. Harbor's own renderer and adapter have not been exercised in the active Python environment. Monitor recording readiness and baseline/no-op gates remain to be verified without inference. Do not dispatch the study until those gates and separate live authorization are satisfied.

The detached-worker fixture was observed failing: one run logged Windows `os.replace` access denied; a repeat reported interrupted while its checkpoint subsequently reached finished. Focused runs excluding that fixture passed. Preserve these results and investigate if they recur in the intended execution environment.

Offline checks: Agent Benchmark focused tests passed 58 with one detached-worker test deselected; the full Benchmark Core suite passed with one skip. Ruff passed on changed Python modules and tests. A read-only monitored plan returned `MONITOR_NOT_RUNNING` for `127.0.0.1:8788`; no recovery was requested. A local planning comparison showed only `prompt_policy` and `manifest_sha256` differed, but its task content fingerprints were all unknown and Docker readiness was denied. The active Python environment could not import Harbor; Jinja 3.1.6 rendered the policy fixtures.
