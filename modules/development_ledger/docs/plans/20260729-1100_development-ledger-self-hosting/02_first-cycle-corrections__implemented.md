# Stage 1 Correction — First-Cycle Evidence Defects

## Goal

Correct only the defects directly exposed by the first self-host validation cycle.

## Implemented

- Safe validation of schemas that use either top-level `type: object` or top-level `oneOf`.
- Canonical pytest JUnit IDs when pytest 9 omits the `file` attribute.
- Regression coverage for classname-only function and test-class cases.
- Plan revision `2` with routine local validation removed from unresolved environment dependencies.
- Dispatcher transcript evidence replaces the redundant manual acceptance check.
- Package patch version `1.1.1`.

## Preserved

- Public CLI behavior.
- Dispatcher adapter behavior.
- Root target ordering.
- Existing immutable run history and generated projections.
- One-command local validation and automatic evidence projection.

## Verification boundary

The same root target must pass locally and generate a second immutable event before broader integration begins.
