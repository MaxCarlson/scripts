"""Static metadata for the structure-first scripts-help browser.

The browser discovers files and modules from the repository at runtime.  This
file deliberately contains only information that cannot be inferred reliably
from the filesystem, existing registry, README files, or pyproject metadata.

Add long-description overrides here when an item's README/docstring is absent
or when a hand-written summary is more useful than the inferred text.
"""

from __future__ import annotations

CATEGORY_SPECS = (
    (
        "modules",
        "Modules",
        "Installable Python modules and larger CLI applications under modules/.",
    ),
    (
        "pyscripts",
        "Python Scripts",
        "Standalone Python utilities under pyscripts/.",
    ),
    (
        "shell",
        "Shell Scripts",
        "Bash/Zsh-compatible scripts from shell-scripts/ and the repository root.",
    ),
    (
        "powershell",
        "PowerShell Scripts",
        "PowerShell utilities under pwsh/ plus root-level .ps1 entry points.",
    ),
    (
        "repo",
        "Repository Tools",
        "Root-level Python helpers used to bootstrap, validate, or maintain this repository.",
    ),
    (
        "pyprjs",
        "Python Projects",
        "Standalone Python projects kept under pyprjs/.",
    ),
)

# path relative to repository root -> paragraph description
#
# Prefer adding an override only when README/docstring inference is inadequate;
# that keeps this file small and avoids duplicating documentation.
LONG_DESCRIPTIONS: dict[str, str] = {
    "modules/scripts_help": (
        "Interactive repository help browser and metadata-maintenance tool. It "
        "discovers the current scripts repository structure, combines that with "
        "the existing scripts-help registry and README metadata, and exposes "
        "searchable menus for program details, live CLI arguments, README "
        "rendering, file browsing, and path-scoped Git history."
    ),
}
