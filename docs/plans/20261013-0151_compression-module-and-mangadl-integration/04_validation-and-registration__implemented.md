# Stage 4: Repository Registration and Comprehensive Validation

> Historical registration/evidence. S8 in 05_reviewed-plan.md requires fresh
> failure-path/terminal/fidelity acceptance after corrections; existing PASS
> reports prove only their snapshot/tests, not completion of designed guarantees.

## Goal
Register the new `compresser` module in the repository's validation dispatcher and scripts catalog, and execute complete multi-target testing to verify system health across all touched modules.

## Scope of Work

1. **Validation Dispatcher (`validation-targets.json`)**:
   - Add new target `"compresser"`:
     - Description: "Standalone image compression engine, analysis, and perceptual optimization."
     - Working directory: `modules/compresser`.
     - Environment: `PYTHONPATH: {target_root};{repo_root}/modules/termdash;{repo_root}/modules`.
     - Bootstrap:
       - Install editable `termdash`.
       - Install editable `compresser`.
     - Commands:
       - Compile `compresser` package and tests.
       - Lint with `ruff check compresser tests`.
       - Validate CLI help (`python -m compresser --help`).
       - Run pytest suite with isolated `--basetemp`.
   - Update target `"mangadl"`:
     - Add `modules/compresser` to bootstrap installation list so `mangadl compress` has access to the dependency.

2. **Scripts Catalog Registry (`modules/scripts_help/scripts_help/registry/registry.py`)**:
   - Add `compresser (module)` under the `"Media Processing"` category:
     ```python
     {
         "name": "compresser (module)",
         "path": "modules/compresser",
         "desc": "Analyze, compare, and optimize manga/manhwa images using perceptual compression",
         "help_cmd": ["python", "-m", "compresser", "--help"],
         "version": "0.1.0",
     }
     ```

3. **Documentation Updates**:
   - `modules/mangadl/docs/README.md`: Document `mangadl compress` usage, options, and safety rules.
   - `docs/HANDOFF.md`: Update handoff with active branch, status, and completed verification.
   - `docs/plans/HANDOFF.md`: Point to active dated plan.

4. **Execution & Authoritative Evidence**:
   - Run `./Invoke-Tests.ps1 -Target termdash` -> verify report in `docs/test-results/termdash/LATEST.txt`.
   - Run `./Invoke-Tests.ps1 -Target compresser` -> verify report in `docs/test-results/compresser/LATEST.txt`.
   - Run `./Invoke-Tests.ps1 -Target mangadl` -> verify report in `docs/test-results/mangadl/LATEST.txt`.
   - Run focused `scripts_help` test suite to verify registry integrity.
   - Run `git status` to verify staged/unstaged file cleanliness.
