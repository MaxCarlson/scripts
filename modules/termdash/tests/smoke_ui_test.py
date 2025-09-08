#!/usr/bin/env python3
"""
Smoke test so this repo's suite doesn't depend on external projects.
All substantive termdash tests live in:
  - tests/align_test.py
  - tests/components_test.py
  - tests/dashboard_test.py
"""
def test_termdash_smoke_import_test():
    import termdash  # noqa: F401
