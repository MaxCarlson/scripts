# agent_memory Performance and Repository Ergonomics — Revised Implementation Plan

> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the Markdown note store and SQLite index usable as the corpus grows toward 1K to 50K notes across WSL2 Ubuntu, Windows 11, and Termux Android.

**Architecture:** Document performance expectations, benchmark methodology, Git/filesystem caveats, and threshold-driven path-layout decisions. Do not automatically change Git configuration. Do not implement path sharding unless benchmarks or real corpus behavior justify it.

**Prerequisites:** PLAN-5 through PLAN-11 complete. PLAN-8 should already include the first benchmark helper/baseline; this plan finalizes documentation and optional scaling ergonomics.

**Working directory:** `/home/mcarls/scripts/modules/agent_memory/`

---

## File Map

| File | Responsibility |
|---|---|
| `docs/performance.md` | Git/filesystem/search/scaling guidance |
| `agent_memory/bench.py` | Benchmark helper refinement if created in PLAN-8 |
| `agent_memory/store.py` | Optional sharded path support only if justified |
| `agent_memory/frontmatter.py` | Path layout helpers if sharding is implemented |
| `tests/store_test.py` | Path compatibility tests if sharding is implemented |
| `tests/index_test.py` | Rebuild/search behavior tests across layouts if sharding is implemented |
| `tests/bench_test.py` | Benchmark helper smoke tests |
| `docs/PROJECT_STATUS.md` | Status update |
| `pyproject.toml` | Version bump |
| `agent_memory/__init__.py` | Version bump |

---

## Design Rules

### No automatic Git config changes

The module may document suggested Git settings but must not run `git config` automatically.

Suggested settings can include:

```text
core.untrackedCache
core.fsmonitor
index.version
```

Document these as user-managed repository settings, not module behavior.

### Cross-platform caveats are first-class

Document and test with awareness that:

- WSL2 Linux filesystem is usually faster than `/mnt/c` for Git-heavy workloads.
- Windows path semantics differ from Linux/Termux path semantics.
- Termux may not support all filesystem features expected on desktop Linux.
- Hardlinks/symlinks should not be assumed for note storage behavior.
- SQLite WAL behavior can be affected by filesystem/sync providers.

### Sharding is threshold-driven

Do not implement sharding purely because it sounds scalable. Current project/kind layout may be enough for 1K-50K notes when notes are distributed.

Only implement path sharding if one of these is true:

```text
- benchmarked directory scans/listing become a real bottleneck,
- a single directory is expected to exceed several thousand files,
- Git status/log/diff behavior becomes unacceptable in real usage,
- path layout is needed to keep human navigation sane.
```

If sharding is implemented, index rebuild and verify must discover both old and new layouts.

---

## Task 1: Finalize performance documentation

**Files:**
- Create: `docs/performance.md`

- [ ] Document expected scale targets: 1K, 10K, and 50K notes.
- [ ] Document expected bottlenecks: working-tree scans, index rebuilds, large directory listings, FTS rebuilds, and Git status.
- [ ] Document SQLite index as a rebuildable derived cache.
- [ ] Document that Markdown files are canonical and safe to version-control.
- [ ] Document suggested Git settings without applying them.
- [ ] Document WSL2/Windows/Termux caveats.
- [ ] Document when to run benchmark helper and how to interpret results.

---

## Task 2: Refine benchmark helper if needed

**Files:**
- Modify if created in PLAN-8: `agent_memory/bench.py`
- Modify if created in PLAN-8: `tests/bench_test.py`

- [ ] Ensure the benchmark uses `tempfile.TemporaryDirectory()` by default.
- [ ] Ensure all user-facing flags have short and long forms.
- [ ] Recommended flags: `-n/--notes`, `-r/--root`, `-p/--project-count`, `-s/--seed`, `-j/--json`, `-v/--verbose`.
- [ ] Ensure benchmark data generation includes realistic code identifiers, paths, tags, and note kinds.
- [ ] Ensure output is machine-readable enough for future comparison.
- [ ] Keep normal pytest benchmarks small and non-timing-sensitive.

Manual examples:

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m agent_memory.bench -n 1000
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m agent_memory.bench -n 1000 -r /tmp/agent-memory-bench
```

---

## Task 3: Evaluate current layout before sharding

**Files:**
- Modify only if needed: `agent_memory/store.py`
- Modify only if needed: `tests/store_test.py`
- Modify only if needed: `tests/index_test.py`

- [ ] Run or document benchmark results for current layout.
- [ ] Decide whether current `global/<kind>` and `projects/<project>/<kind>` directories are sufficient.
- [ ] If no sharding is implemented, explicitly document the threshold for revisiting.
- [ ] If sharding is implemented, prefer a backward-compatible project/kind/date layout.
- [ ] Ensure index rebuild discovers old and new layouts.
- [ ] Ensure `verify()` uses the layout resolver from PLAN-6.
- [ ] Add tests for both path styles if implemented.

Candidate sharded layout if needed later:

```text
notes/projects/<project>/<kind>/YYYY/MM/<filename>.md
notes/global/<kind>/YYYY/MM/<filename>.md
```

Avoid hash-prefix sharding unless human navigation becomes less important than extreme file-count distribution.

---

## Task 4: Add optional small performance smoke tests

**Files:**
- Modify: `tests/index_test.py`
- Maybe modify: `tests/store_test.py`
- Maybe modify: `tests/bench_test.py`

- [ ] Verify benchmark helper can generate a small corpus.
- [ ] Verify index rebuild works over generated corpus.
- [ ] Verify search returns expected results over generated corpus.
- [ ] Avoid strict timing assertions in normal tests.
- [ ] Keep generated note count small in pytest, such as 20-100 notes.

---

## Task 5: Update docs and version

**Files:**
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `pyproject.toml`
- Modify: `agent_memory/__init__.py`

- [ ] Document performance guidance completion.
- [ ] Document whether sharding was implemented or intentionally deferred.
- [ ] Bump PATCH for docs/benchmark-only changes.
- [ ] Bump MINOR if public CLI/API/path behavior changes.

---

## Tests to Add

- [ ] Benchmark helper creates a small corpus under `tmp_path` or `TemporaryDirectory`.
- [ ] Benchmark helper supports short and long flags if exposed through CLI/module execution.
- [ ] Index rebuild works over benchmark-generated notes.
- [ ] Search works over benchmark-generated code-heavy notes.
- [ ] If sharding is implemented, old and new layouts both verify and rebuild.
- [ ] If sharding is not implemented, no existing layout behavior changes.

---

## Validation

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m pytest tests/ -v --tb=short
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff check agent_memory tests
```

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m ruff format --check agent_memory tests
```

Run a small benchmark manually:

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m agent_memory.bench -n 1000
```

If testing an explicit root, use:

```bash
cd /home/mcarls/scripts/modules/agent_memory && /home/mcarls/scripts/.venv/bin/python -m agent_memory.bench -n 1000 -r /tmp/agent-memory-bench
```

---

## Definition of Done

- [ ] Performance guidance is documented.
- [ ] Synthetic benchmark helper exists, if not already completed in PLAN-8, and is documented.
- [ ] Large-corpus strategy is explicit.
- [ ] Sharding is either justified and implemented or explicitly deferred with thresholds.
- [ ] No automatic Git config changes are made.
- [ ] Cross-platform filesystem caveats are documented.

---

## Risks, Edge Cases, and Compatibility Notes

- Git behavior differs substantially across WSL2 Linux filesystems, `/mnt/c`, native Windows, and Termux.
- Avoid path layout changes that break human editability or V1 note discovery.
- Do not rely on hardlinks, symlinks, or platform-specific filesystem features.
- SQLite WAL on sync-backed folders can behave differently; document rather than hide this.
- Avoid strict performance timing assertions in tests; use manual benchmark output for real comparisons.
