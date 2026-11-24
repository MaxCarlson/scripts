# Checklist

- [x] Gitlink validator tests failed against the missing implementation, then passed after implementation: 4 passed.
- [x] Workflow compares checked-out pscripts and nested AEBN SHAs to parent-tree Gitlinks.
- [x] Workflow verifies procparsers distribution/import and migrated `mangadl`, `ytaedl`, `aebndl` launcher help from outside the checkout with `PYTHONPATH` unset.
- [x] Static and focused checks pass locally: Ruff, Python AST, PyYAML parse, and `git diff --check`.
- [x] Windows root-setup safety finding documented without profile/system mutation; source changes recommended before isolated root-setup qualification.
- [x] Hosted Linux workflow `45302927058` passed; private-bootstrap fail-closed report was skipped because authenticated submodule checkout succeeded.
- [x] Feature branch pushed and scoped draft PR #33 opened; PRs #31/#32 unchanged.
