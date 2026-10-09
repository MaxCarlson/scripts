# URL-File Audit and Repair Handoff

Plan: [00 implementation plan](00_implementation-plan.md)

Branch: `codex/kavita-module-mangadl-collections-20261009-0349`.

The audit now checks numbered page coverage and image decoding for matched
folders, and uses nhentai metadata to detect missing leading/trailing pages.
It remains read-only. The existing repair command only organizes loose
nhentai images. The next stage adds explicit repair planning and execution
using MangaDL's current archive, state, partial, and scratch safety rules.

Current stage: Stages 1–3 implemented; Stage 4 repair is next. User approved
implementation with `impl` and supplied a real missed-gallery case, now covered
by regression tests. Live download acceptance, commit, push, and merge remain
separate approval gates.

Next action: implement safe repair preview/apply boundaries. Keep this audit
fix read-only and stop before live repair acceptance.
