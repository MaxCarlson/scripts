# Reliable AEBN Scene-ID Resolution

**Goal:** Make ordinary AEBN scene URLs download only the scene named by `#scene-<id>`, and fail closed whenever that ID cannot be resolved.

**Architecture:** `aebndl` will parse scene IDs from the authoritative movie HTML while preserving document order, then resolve an explicit `--scene-id` to the existing 1-based ordinal scene selector. `ytaedl` will strictly parse scene fragments and pass the ID as an explicit `-I` argument; invalid or unresolved scene selection must stop before subprocess launch.

**Tech Stack:** Python 3.9+, argparse, lxml, requests via `CustomSession`, pytest fixtures/mocks.

**Spec:** User-provided Implementation Handoff: Reliable AEBN Scene-ID Resolution (2026-11-06).

## Global Constraints

- Preserve existing `-s/--scene` behavior; reject simultaneous explicit `-s` and `--scene-id`.
- Never derive an ordinal arithmetically from a scene ID or fall back to a full-movie command.
- Preserve the source URL and fragment throughout ytaedl manager/worker assignment and command generation.
- Keep automated tests offline and use mocked responses; do not download media.
- Bump each changed package version for the backward-compatible CLI feature.
- Do not sync upstream subtree, commit, push, merge, or run live media downloads.

## Review Focus

- Malformed scene fragments and lookup failures must stop before `Popen`; test invalid fragments and mocked HTTP/network failure.
- Duplicate, malformed, or missing scene metadata must not resolve ambiguously; test fixture ID validation.
- Fragment must survive manager/domain-index/worker handoff and reach `aebndl -I`; test URL preservation and generated dry-run command.
- Legacy ordinal selection and explicit option conflict behavior must remain clear; test `-s` and mutual exclusion.
- Scene section order must stay aligned with timeline boundaries; test ID-to-ordinal fixtures with non-sequential IDs and order mismatch.

## Files

- `modules/aebndl_module/aebn_dl/models.py`: optional `Scene.scene_id` field.
- `modules/aebndl_module/aebn_dl/movie_scraper.py`: ordered HTML ID capture, scene/timeline consistency, and strict ID resolution.
- `modules/aebndl_module/aebn_dl/cli.py`, `downloader.py`: `-I/--scene-id`, resolution, structured selection event, and failure propagation.
- `modules/aebndl_module/tests/`: mocked movie/timeline fixtures and scene-ID/CLI regression tests.
- `modules/aebndl_module/pyproject.toml`: minor version bump.
- `modules/ytaedl/ytaedl/downloader.py`: strict fragment parsing, explicit `-I`, and removal of best-effort metadata ordinal lookup.
- `modules/ytaedl/tests/`: strict parsing, command generation, dry-run, subprocess prevention, and fragment preservation tests.
- `modules/ytaedl/pyproject.toml`: minor version bump.

## Tasks

1. Add `Scene.scene_id: str | None = None`, parse and validate IDs in movie HTML, verify the mobile timeline scene count before indexing, and add fixture-backed ID-to-ordinal cases for all user-provided IDs (including the four IDs for movie 270491 and scene 3 for movie 276944).
2. Add mutually exclusive `-I/--scene-id` alongside legacy `-s/--scene`; resolve the ID to the existing ordinal path, emit `scene_selected` JSON with ID and ordinal, and propagate unknown/invalid metadata as nonzero CLI failure.
3. Replace ytaedl's swallowing resolver with strict `#scene-<digits>` parsing and `_build_aebndl_cmd(..., scene_id=...)`; validate selection before subprocess launch and test dry-run plus invalid cases.
4. Test URL-fragment preservation through manager/domain-index/worker paths, update both package minor versions, run module-focused pytest suites and static diff/status checks.

## Execution Notes

- User explicitly supplied the implementation approach and authorized implementation, tests, and metadata-only checks. Execute inline in this worktree.
- AEBN live HTML and media access are not required for fixture tests. If live metadata-only verification is unavailable, report that separately from fixture-based results.
