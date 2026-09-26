# Missing-only bootstrap

## Objective

Add explicit PowerShell and Bash entry points that install only absent local Python distributions and create only absent script launchers. Existing installations, versions, wrappers, profiles, PATH settings, and aliases remain untouched.

## Approach

- Keep the existing `--skip-reinstall` contract intact; it still performs normal setup and may refresh changed versions or wiring.
- Share discovery and installation logic in an import-safe Python helper called by both shell entry points.
- Preserve core-first and dependency-aware module ordering, with the canonical aebndl source taking precedence.
- Provide a dry-run inventory and focused tests. A fresh venv is created only for an apply run; never recreate an existing venv.
- Document the feature and limits in the root README.

## Acceptance

- Installed distributions are not reinstalled even if their source version differs.
- Missing distributions are installed once, in a safe order.
- Missing script and console launchers are created; existing paths are not replaced.
- A dry-run makes no changes and reports proposed work.
- Focused tests pass on Windows; Bash syntax is checked where Bash is available.
