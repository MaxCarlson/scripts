What goes in docs/manifest/tools.yaml
A versioned, human-editable mapping like:


tool name


how to detect it (--version, where/which, etc.)


best installer per platform


fallback installers (2nd/3rd choice)


optional post-install steps


Example concept (not the full file, just the idea):


ripgrep


Windows: winget -> choco -> scoop


Ubuntu: apt -> brew


Termux: pkg -> cargo





.gitignore behavior (recommended)


Ignore per-machine state:


docs/state/installed/*


docs/state/receipts/*




Keep the folders present via .gitkeep and docs/state/README.md


Keep docs/manifest/** tracked



Next deliverable (if you want me to proceed)
I can generate the full initial module (all files) with:


pyproject.toml (console_script entry for xi)


xi CLI with check/install/ensure/doctor/list


manifest loader + schema validation


package-manager detection + fallback planning engine


state store that writes:


docs/state/installed/<host>.json


docs/state/receipts/<timestamp>_<tool>.json




bootstrap install scripts:


scripts/bootstrap_install.ps1 (Windows)


scripts/bootstrap_install.sh (WSL2/Ubuntu/Termux)




If you tell me your preferred command name (xi vs something else), I'll lock that in and output the complete repo scaffold.
