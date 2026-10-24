# Checklist

- [x] Preserve argparse compatibility, lazy imports, and parser-only import boundary from Branch A.
- [x] Consolidate atomic layout storage with strict JSON validation and visible corruption recovery.
- [x] Keep Branch A layout API/data compatibility and restored static output without process restart.
- [x] Use a bounded asynchronous output writer with snapshot ordering, overflow failure, error reporting, and bounded cleanup.
- [x] Keep console capture subscribed across later commands and release completed process subscriptions.
- [x] Run cli_tui tests (103), MangaDL TUI/CLI tests (51), Runmux TUI/adapter tests (23), Ruff, and diff checks.
- [ ] Complete manual Windows TUI acceptance for layout save/restore, quitting, output capture, and existing application behavior.
