# P15a acceptance and P15b offline interface handoff

Review date: 2026-11-02. Repository `main` was `5480ea698c8b9769f244b42f61e4be6883ac855c`; P15a branch was `5c58cd6a0c286c0f04c8e6d1730759d59a51a135`. This is a proposal, not a frozen schema, adapter, configuration mapping, or permission to activate anything.

## P15a acceptance: BLOCKED

The P15a worktree was clean excluding submodule status. Only its own local ref contained the completion SHA; no other local branch or remote-tracking ref contained it. No separate P15 integration worktree was found in `git worktree list`; agents outside the visible local refs/worktrees cannot be ruled out. Do not merge as an accepted fail-closed preflight yet.

Independent adversarial check: using the existing `shaped_fixture` and a complete synthetic MTP-only inventory with local fallbacks, change the `blk.2.nextn.hnorm.weight` descriptor offset from 1696 to 0, overlapping `blk.2.attn_norm.weight`. The public `inspect_gguf` returned `present`. `validate_payloads` checks each range independently but does not detect overlapping ranges. It therefore does not establish that independently named MTP tensors occupy independent payload ranges; downstream code must not treat `present` as sufficient file validation. Before acceptance, determine permitted GGUF aliases against the pinned format/loader contract, reject or classify unverified overlaps conservatively, and add public-entry regression cases for overlap within one shard and across permissible shard boundaries. Do not assume distinct files' relative offsets collide.

The result includes a basename and size but no content digest or stable full-file identity. A future adapter must bind evidence to the selected exact file(s) and quantization with an appropriately obtained immutable identity; a name/size match alone is insufficient. The review does not claim the installed files overlap or that their payload values are corrupt. No entire trunk, tensor values, runtime support, or cross-file pairing was validated.

Read-only reinspection: community Q4_K_M size 16810714336 and Q6_K size 22430999776 bytes both returned `present`/`bundled`; paths and tensor dimensions are in the P15a report at `modules/local_agent_bridge/docs/P15A_MTP_INSPECTION.md` on its feature branch. No full-file hashes were computed. Focused inspector suite: 45 passed; offline `model_limits_test.py`: 26 passed with the editable finder bypassed and package paths verified against the P15a worktree. Ruff passed. The initial report's conclusion that this alone is P15b-preflight-ready is superseded by the overlap finding.

## Dependency inventory

Statuses describe evidence found in local branches and worktrees, not a global claim about other agents.

| Phase | Status and evidence | Contract / ownership question |
| --- | --- | --- |
| P02 | Unknown: no sealed P02 manifest or completed P02 phase branch found in the inspected local inventory. Historical benchmark artifacts are not proof of this baseline. | Baseline owner must identify immutable untouched manifest and artifacts before live gates. |
| P03 | Partial existing infrastructure: `benchmark_core/conditions.py` has `comparison-conditions-v1`, canonical fingerprints, task/verifier identity, and strict unknown rejection; last main change `1ac9f1e30818ae86efbd834a78869ae19c4cd1e3`. | No P03-specific frozen preregistration/experiment identity contract was located. Confirm owner and freeze. |
| P04 | Partial existing metadata/model verification and comparison provenance; no frozen P04 speculation evidence interface found. | Evidence owner must freeze requested/configured/forwarded/effective/backend/statistics provenance, including unknown semantics. |
| P05 | Missing required contract: `agent_benchmark/inference_profile.py` is strict `opencode-inference-profile-v1`, allowing only context, output and reasoning, last main change `e03bfc529ed8eaf306c983aeb1d6265770b56bb0`. No separate frozen feature registry or adapter API found. | P05 owner must publish schema version, registration, lifecycle, ownership, and freeze. Do not add speculation keys to v1. |
| P06 | Partial existing mechanism: `local_agent_bridge/setup/planner.py` and `installer.py` plan setup resources and provide receipt/journal rollback; last planner main change `0f1f3f1bcd7a6b6fcb0845dd8257263bca0a8403`. | This is not evidence of a frozen inference feature compiler or load/request adapter. P06 owner must publish deterministic no-write plan and operation interface. |
| P07 | Unknown/not demonstrated: no P07 no-op parity sign-off or integrated source digest was located. | Gate owner must establish offline parity/recovery and, when authorized, matched baseline before activation. |

The local refs/worktree inventory showed no P02–P07 phase branches or worktrees. This does not prove that no unobserved agent owns related files. The npm package metadata reports OpenCode `opencode-ai` 1.19.5; the wrapper was not executed, effective config was not inspected, and forwarding support remains unknown. LM Studio backend identity and speculation controls remain unknown.

## P15b proposed interface and compatibility matrix

After P05/P06 freeze, adapt the following semantics to their actual interfaces; names here do not define public keys. Preserve `opencode-inference-profile-v1` exactly. All plans are deterministic, read-only, and expose capability rejections rather than silently dropping options.

| Requested mode | Offline prerequisites and result | Runtime / activation |
| --- | --- | --- |
| `off` | Empty effective operation set, no config mutation; preserve existing profile hashes and behavior. | No claim about a pre-existing runtime's effective setting without evidence. |
| `mtp` | Accepted P15a structural evidence bound to exact target files and quantization; exact backend/version and verified supported MTP control; supported requested parameters and explicit reload/resource decision. Any missing/unknown/unsupported item rejects. | Unknown for installed backend. `present` alone never means supported, forwarded, effective, or active. |
| `draft-model` | Explicit immutable target and draft identities, independently verified pairing and a verified backend control/mapping; reject missing draft, changed identities, incompatible/unknown pair or unsupported options. | Unknown for installed backend; SDK draft-model documentation does not establish bundled MTP support. |

The contract should carry independent fields and evidence provenance for structural result, target and draft identities, exact backend/version, control mechanism and supported parameters, target/draft pairing, forwarding, effective activation, statistics availability, load-versus-request scope, reload requirement, and resource estimates. Represent absent, unknown, unsupported, requested, verified, and effective distinctly. Do not fill unknown evidence from a requested value. A deterministic plan includes sorted operations, explicit no-op/rejection reasons, relevant identity fingerprints, reload scope, resource uncertainty, and no write or service operation.

No llama.cpp flag may be mapped to LM Studio REST or OpenCode without a verified exact-version mechanism. Published JavaScript `draftModel` and historical `draft_model` API documentation concern separate draft models and do not verify installed bundled-MTP support. Missing speculative statistics remain explicit and block any acceptance-statistics-dependent measurement; report unknown reload or resource needs rather than inventing values.

## Offline acceptance tests after contracts freeze

Use worktree-local temporary fixtures and stubbed backend evidence, no live service: off/no mutation and legacy v1 hash compatibility; all four P15a statuses and overlapping payloads; target file/quantization mismatch and changed identity; unknown/old backend, unsupported mechanism and parameters; draft missing/mismatched/unknown pairing; unknown forwarding or effective activation; missing stats; load/request/reload/resource distinctions; deterministic repeated plan; no writes, service calls or false effective flags. Add separate synthetic multipart, malformed and sidecar cases as appropriate. Independently review exact changed paths and run the targeted P05/P06/P15b suites.

## Required integration order

1. Resolve P15a overlapping-range evidence and independently accept its scoped checks; coordinate an authorized integration of its exact reviewed commit, without merging here.
2. Establish P03 identity and P04 evidence contracts, freeze P05 feature-profile/adapter schema and P06 load/request compiler interface, and identify their actual owners and integrated commits.
3. Base a separate P15b worktree on the appropriate integrated checkpoint; implement only the offline adapter through those frozen interfaces and run the matrix above.
4. Preserve/seal P02 untouched baseline and complete P07 parity/recovery gate. Only separately authorized work may check the actual backend, enable a feature or run controlled benchmarks.

No runtime service, production configuration, model loading, inference, or GPU benchmark was touched during this review.
