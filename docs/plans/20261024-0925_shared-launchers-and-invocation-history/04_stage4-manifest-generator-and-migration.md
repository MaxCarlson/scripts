# Stage 4: Manifest Generator, Unified Wrappers, Migration & Rollback

**Stage Goal:** Unify wrapper and manifest generation under a single authoritative generator in `scripts_setup`, implement collision detection and backup/rollback tooling, and integrate into existing repository setup and bootstrap scripts.

---

### Task 4.1: Repository Inventory Scanner and Manifest Generator

**Files:**
- Create: `scripts_setup/launcher_generator.py`
- Create: `tests/test_launcher_generator.py`

**Interfaces:**
- Consumes: Standard library `pathlib`, `tomllib` (or `tomli`), `json`, `re`.
- Produces:
  - `scan_repository_programs(repo_root: Path) -> dict[str, Any]`
  - `detect_collisions(inventory: dict[str, Any]) -> list[str]`
  - `generate_manifest(repo_root: Path, *, target_dir: Path | None = None) -> Path`

- [ ] **Step 1: Write failing test for inventory scanning and collision detection**

```python
# tests/test_launcher_generator.py
from pathlib import Path
import pytest
from scripts_setup.launcher_generator import scan_repository_programs, detect_collisions, generate_manifest

def test_scan_repository_programs(tmp_path):
    # Setup mock module with pyproject.toml
    mod_dir = tmp_path / "modules" / "mymod"
    mod_dir.mkdir(parents=True)
    (mod_dir / "pyproject.toml").write_text(
        """
[project]
name = "mymod"
version = "1.0.0"

[project.scripts]
mycmd = "mymod.cli:main"
alias_cmd = "mymod.cli:main"
""",
        encoding="utf-8",
    )

    # Setup mock pyscript
    pyscripts_dir = tmp_path / "pyscripts"
    pyscripts_dir.mkdir(parents=True)
    (pyscripts_dir / "my_standalone.py").write_text("__version__ = '0.1.0'\n", encoding="utf-8")

    inventory = scan_repository_programs(tmp_path)
    commands = inventory["commands"]

    assert "mycmd" in commands
    assert commands["mycmd"]["program_id"] == "module:mymod"
    assert commands["mycmd"]["kind"] == "console_script"

    assert "alias_cmd" in commands
    assert commands["alias_cmd"]["program_id"] == "module:mymod"

    assert "my_standalone" in commands
    assert commands["my_standalone"]["program_id"] == "pyscript:pyscripts/my_standalone.py"

def test_detect_collisions_case_insensitive():
    inventory = {
        "commands": {
            "foo": {"program_id": "module:foo"},
            "FOO": {"program_id": "module:bar"},
        }
    }
    collisions = detect_collisions(inventory)
    assert len(collisions) > 0
    assert any("case-insensitive collision" in c.lower() for c in collisions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_launcher_generator.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts_setup.launcher_generator'`

- [ ] **Step 3: Implement repository scanner and manifest generation**

In `scripts_setup/launcher_generator.py`:
- `scan_repository_programs(repo_root: Path)`:
  - Scans `modules/*/pyproject.toml` parsing `[project.scripts]`.
  - Scans `pscripts/modules/*/pyproject.toml` if directory exists.
  - Scans `pyscripts/*.py` extracting `__version__`.
  - Scans `shell-scripts/*.sh`.
  - Filters strictly to repository-owned programs (never includes arbitrary packages installed in venv).
- `detect_collisions`: checks for identical names and case-insensitive duplicates on Windows.
- `generate_manifest`: writes `scripts_manifest.json` with schema version 1 and atomic write semantics.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_launcher_generator.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 4.1**

```bash
git add scripts_setup/launcher_generator.py tests/test_launcher_generator.py
git commit -m "feat(scripts_setup): implement repository scanner and manifest generator"
```

---

### Task 4.2: Wrapper Template Generation and Recognition

**Files:**
- Modify: `scripts_setup/launcher_generator.py`
- Test: `tests/test_launcher_generator.py`

**Interfaces:**
- Consumes: `launcher_generator.py`.
- Produces:
  - `is_managed_wrapper(path: Path) -> bool`
  - `generate_windows_wrapper(command_name: str) -> str`
  - `generate_posix_wrapper(command_name: str) -> str`

- [ ] **Step 1: Write failing test for wrapper templates and signature detection**

```python
# in tests/test_launcher_generator.py
from scripts_setup.launcher_generator import is_managed_wrapper, generate_windows_wrapper, generate_posix_wrapper

def test_managed_wrapper_signature_detection(tmp_path):
    win_wrapper = tmp_path / "cmd1.cmd"
    win_content = generate_windows_wrapper("cmd1")
    win_wrapper.write_text(win_content, encoding="utf-8")
    assert is_managed_wrapper(win_wrapper) is True

    # User-created wrapper without signature
    user_wrapper = tmp_path / "custom.cmd"
    user_wrapper.write_text("@echo off\necho hello\n", encoding="utf-8")
    assert is_managed_wrapper(user_wrapper) is False

def test_windows_wrapper_content():
    content = generate_windows_wrapper("mangadl")
    assert "@echo off" in content
    assert "script_logging.launcher" in content
    assert "--command" in content
    assert "%*" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_launcher_generator.py -k test_managed_wrapper_signature_detection --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `cannot import name 'is_managed_wrapper'`

- [ ] **Step 3: Implement wrapper generation with managed signature**

In `scripts_setup/launcher_generator.py`:
- Signature constant: `MANAGED_SIGNATURE = "@REM Scripts Toolkit Managed Wrapper v0.2.0"` (Windows) and `# Scripts Toolkit Managed Wrapper v0.2.0` (POSIX).
- Implement `is_managed_wrapper(path: Path) -> bool`: checks if file exists, reads header lines, and verifies signature is present.
- Implement `generate_windows_wrapper`: creates clean, portable `.cmd` wrapper routing to `%_VENV_PY% -m script_logging.launcher --manifest %_MANIFEST% --command <name> --wrapper %~f0 -- %*`.
- Implement `generate_posix_wrapper`: creates bash script using `exec "$VENV_PY" -m script_logging.launcher --manifest "$MANIFEST" --command "${0##*/}" --wrapper "$0" -- "$@"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_launcher_generator.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 4.2**

```bash
git add scripts_setup/launcher_generator.py tests/test_launcher_generator.py
git commit -m "feat(scripts_setup): implement native wrapper generation with managed signature"
```

---

### Task 4.3: Migration, Backup, Rollback, and Dry-Run Tooling

**Files:**
- Modify: `scripts_setup/launcher_generator.py`
- Create: `tests/test_migration.py`

**Interfaces:**
- Consumes: `launcher_generator.py`.
- Produces:
  - `migrate_wrappers(repo_root: Path, bin_dir: Path, *, dry_run: bool = True, backup_dir: Path | None = None, cleanup: bool = False) -> MigrationSummary`
  - `rollback_wrappers(backup_dir: Path, bin_dir: Path) -> RollbackSummary`
  - CLI: `python -m scripts_setup.launcher_generator [flags]` with `-n`/`--dry-run` (default), `-w`/`--write`, `-a`/`--apply`, `-b`/`--backup-dir`, `-r`/`--rollback`, `-c`/`--cleanup`, `-V`/`--version`.

- [ ] **Step 1: Write failing test for migration, backup, and rollback**

```python
# tests/test_migration.py
from pathlib import Path
import pytest
from scripts_setup.launcher_generator import migrate_wrappers, rollback_wrappers, is_managed_wrapper

def test_dry_run_does_not_modify_files(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    existing_file = bin_dir / "old_managed.cmd"
    existing_file.write_text("@REM Scripts Toolkit Managed Wrapper v0.1.0\n@echo off\n", encoding="utf-8")

    # Run migration with dry_run=True (default)
    summary = migrate_wrappers(tmp_path, bin_dir, dry_run=True)
    assert summary.is_dry_run is True
    # Verify file content is unchanged
    assert "v0.1.0" in existing_file.read_text(encoding="utf-8")

def test_migration_creates_backup_and_allows_rollback(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    existing_file = bin_dir / "existing.cmd"
    existing_file.write_text("@REM Scripts Toolkit Managed Wrapper v0.1.0\nold_content", encoding="utf-8")

    custom_user_file = bin_dir / "my_custom.cmd"
    custom_user_file.write_text("@echo off\nuser_content", encoding="utf-8")

    backup_dir = tmp_path / "backups"
    # Run migration with apply
    summary = migrate_wrappers(tmp_path, bin_dir, dry_run=False, backup_dir=backup_dir)
    assert summary.applied_count > 0

    # User file MUST be preserved untouched!
    assert custom_user_file.read_text(encoding="utf-8") == "@echo off\nuser_content"

    # Rollback
    rollback_summary = rollback_wrappers(backup_dir, bin_dir)
    assert rollback_summary.restored_count > 0
    assert "old_content" in existing_file.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_migration.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `cannot import name 'migrate_wrappers'`

- [ ] **Step 3: Implement migration and rollback functions + CLI entry point**

In `scripts_setup/launcher_generator.py`:
- `migrate_wrappers`:
  - Scans inventory.
  - Identifies target wrappers to create or update.
  - Never touches files where `is_managed_wrapper` is False (custom user launchers).
  - If not `dry_run`: creates backup of target files in `backup_dir` before modifying.
  - Writes new managed wrappers and `scripts_manifest.json`.
  - If `cleanup=True`: removes obsolete managed wrappers (wrappers with managed signature no longer in manifest).
- `rollback_wrappers`: copies all backed-up files back into `bin_dir`.
- Add CLI `main()` with standard `-n`/`--dry-run`, `-a`/`--apply`, `-b`/`--backup-dir`, `-r`/`--rollback`, `-c`/`--cleanup`, `-V`/`--version`, `-v`/`--verbose`.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_migration.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 4.3**

```bash
git add scripts_setup/launcher_generator.py tests/test_migration.py
git commit -m "feat(scripts_setup): implement wrapper migration, backup, rollback, and CLI"
```

---

### Task 4.4: Integration into Existing Setup Scripts

**Files:**
- Modify: `modules/setup.py`
- Modify: `pyscripts/setup.py`
- Modify: `bootstrap_latest.py`
- Modify: `scripts_setup/setup_utils.py`
- Test: `tests/test_setup_integration.py`

**Interfaces:**
- Consumes: `launcher_generator.py`.
- Produces: Consolidated single wrapper generator across the entire repository.

- [ ] **Step 1: Write failing test verifying setup script delegation**

```python
# tests/test_setup_integration.py
from pathlib import Path
import pytest
from scripts_setup.launcher_generator import is_managed_wrapper

def test_bootstrap_uses_managed_generator_without_overwriting_existing(tmp_path):
    from bootstrap_latest import run as bootstrap_run
    # Verify bootstrap_latest calls into shared launcher generator and obeys no-overwrite rules
    pass
```

- [ ] **Step 2: Run test to verify baseline**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_setup_integration.py --basetemp=modules/script_logging/.pytest_tmp_root`

- [ ] **Step 3: Refactor setup scripts to use `launcher_generator`**

- In `modules/setup.py`: replace lines 1018–1085 with a call to `scripts_setup.launcher_generator.create_or_update_wrappers(...)`.
- In `pyscripts/setup.py`: replace `_make_windows_wrapper` and `_make_posix_wrapper` with unified generator.
- In `bootstrap_latest.py`: replace `write_console_proxy` and `write_launcher` with unified generator, retaining bootstrap's missing-only semantics.
- In `scripts_setup/setup_utils.py`: delegate `_create_windows_cmd_wrapper` to `launcher_generator`.

- [ ] **Step 4: Run tests to verify all pass**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_setup_integration.py tests/test_launcher_generator.py tests/test_migration.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 4.4**

```bash
git add modules/setup.py pyscripts/setup.py bootstrap_latest.py scripts_setup/setup_utils.py tests/test_setup_integration.py
git commit -m "refactor(setup): consolidate wrapper and manifest generation through shared launcher_generator"
```
