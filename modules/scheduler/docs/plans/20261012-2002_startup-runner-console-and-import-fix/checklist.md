# Checklist

- [x] Reproduce the installed scheduler import traceback with the runtime request directory present.
- [x] Confirm runner actions currently use console-subsystem `python.exe`.
- [x] Inspect the PowerShell profile's prompt and theme configuration without editing external profile files.
- [x] Rename the queue implementation module and update imports.
- [x] Register background runner actions with `pythonw.exe` when available.
- [x] Make the scheduled Winget Update task noninteractive using the flags already present on Winget Upgrade.
- [x] Add import-collision and executable-selection regression coverage.
- [x] Synchronize scheduler package and help registry versions.
- [x] Update module usage docs, validation context, and handoffs.
- [x] Run scheduler validation, CLI import/help, Ruff, JSON parsing, compile, and diff checks; record exact outcomes.
- [x] User manually validates updated Windows runner actions.
