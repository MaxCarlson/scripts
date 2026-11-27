# Canonical LLM Monitor Bundle Integration

## Scope

Qualify the H4 proxy-chain tests against the canonical `llm-monitor` package,
remove the scripts source path from Resource Coordinator's generated launcher,
and stage a pinned canonical package wheel in the portable bundle. Preserve the
mock-backed gateway/lease behavior; no inference or live service operations.

## Starting point

- Branch: `feat/h4-canonical-llm-monitor-20261124`.
- Base: `8d98af2f731f6592668c6eaa5e89db87a91de72a` (canonical Resource Metrics H4 bundle checkpoint).
- H4 base: `ea6ad23fe705bc828f06a99ccf1ab3477e621d49`.
- Canonical Monitor source candidate: Toolkit commit `edd54bd07ec9b1058e9c35e57ca320aaf993b6b2`.
- The dirty Phase-D worktree is out of scope and remains untouched.

## Work state

Implemented a source-pinned canonical wheel and canonical import contract. The
wheel is built from a Git archive of Toolkit commit
`edd54bd07ec9b1058e9c35e57ca320aaf993b6b2`; SHA-256 is
`4357bd80029cad52d1f848db7903427d95c10e447dcce78836bda07a769688d5`.

Validation: the full focused offline H4 selection passed **77 tests**, skipped 1,
and deselected 4 host-dependent Scheduler/ACL/live-inventory cases. Ruff,
compileall, and `git diff --check` passed. No inference or live service mutation
occurred. Physical deletion of `modules/llm_monitor` remains a later Scripts
retirement batch after all consumers and clean-bootstrap installation are
reconciled.

## Scripts successor qualification (2026-11-27)

- Successor branch: `retire/llm-monitor-successor-20261127`, stacked on the
  qualified Metrics successor.
- Canonical source: Toolkit commit
  `e10544f63ceb2f2082bc716edb4d6227087b8e03`.
- Rebuilt wheel from that exact Git archive; SHA-256
  `bc503adab4b02416f56cd1c286ab827116e2ba527afcd49790a79704c4175adb`.
- Scripts `llm_monitor` package, tests, and web assets are removed. README,
  examples, historical docs, and Phase-D evidence remain tracked and unchanged.
- Generated launcher and H4 runner use the canonical wheel. Both historical
  source snapshots omit the Monitor package, and the bundle integrity test
  verifies the archive manifest.
- Synthetic qualification passed: canonical bundle/Runmux contract 2 tests,
  proxy-chain integration 4 tests, H4 compatibility/hardening/Windows harness
  39 tests, and source-retirement/registry checks 25 tests.
- No inference, live service operation, guest deployment, or Phase-D worktree
  modification occurred. Source-ownership CLI passed and the successor branch
  is pushed; H4 owner review and integration remain pending.
