# Scratch staging checklist

## Stage 1

- [x] Identify B: and E: storage roles without mutating either drive.
- [x] Add explicit scratch directory and dry-run path preview.
- [x] Route supported backend payloads to isolated scratch partials; refuse unsafe routes.
- [x] Guard and serialize cross-volume promotion; preserve scratch on failure.
- [x] Allow partial cleanup to target the scratch root explicitly.
- [x] Add focused normal, conflict, interrupted-copy, routing, and dry-run tests.
- [x] Record complete automated verification.
- [ ] Obtain bounded manual B:/E: validation from user.

## Stage 2

- [x] Expose `mangadl run -S/--scratch` while preserving no-option behavior.
- [x] Make gallery-dl and Manga18FX check library files before network download.
- [x] Stage active archive, state, and logs on scratch and sync safely.
- [x] Defer canonical archive updates while scratch partials remain.
- [x] Restrict automatic cover matching to promoted folders.
- [x] Add normal, failure, resume, cleanup, and control-sync regression tests.
- [ ] Obtain bounded manual B:/E: validation and measure residual disk load.
