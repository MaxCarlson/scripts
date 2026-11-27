# Repository-Only Root Setup

## Goal

Allow `setup.py` to install packages and generate repository-owned launchers without writing to user profiles, user PATH/PYTHONPATH, skill directories, shell configuration, venv activation files, or system locations.

## Design

- Add `-r/--repository-only` to root setup and propagate its state through `SCRIPTS_REPOSITORY_ONLY=1`. The argument survives venv re-execution and the environment marker is inherited by child setup processes.
- Keep package installation and the managed launcher refresh active. In repository-only mode, install private packages through `pscripts/modules/setup.py`; skip setup wrappers that also write aliases or other user integration files.
- Extend managed launcher discovery to scan `pscripts/pyscripts/*.py`, excluding setup/initializer files and retaining duplicate-command protection.
- Skip `modules/setup.py`'s user PYTHONPATH registration when the repository-only marker is set.
- Keep default setup behavior and allow repeated explicit skill destinations through `-K/--skills-dir`.
- Do not emulate or suppress Windows symlink privilege failures. Repository-only setup uses managed file wrappers; the legacy symlink helper remains an independently testable integration path.

## Scope

Changes are limited to root setup orchestration, the public modules setup guard, skill destination configuration, managed command discovery, tests, and setup documentation. No shared-package source, retirement files, primary checkout, profile, registry, WSL system path, or runtime data is modified.
