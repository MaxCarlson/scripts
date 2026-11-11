# Stage 3: Abundantly Clear Completion UX & Final Verification

## Objectives
1. Add a prominent completion status banner in `cli_tui` when process completes (success or failure).
2. Append a clear completion box with instructions to press `[Enter]` to conclude and return to the form screen.
3. Highlight `[Enter] Return` in the bottom hotkey footer upon completion.
4. Add clear terminal completion notice to `mangadl run` summary.
5. Run full test suites for both `cli_tui` and `mangadl`.

## Target Files
- `modules/cli_tui/cli_tui/app.py`
- `modules/mangadl/mangadl/manager.py`
- `modules/cli_tui/tests/test_app.py`
- `modules/mangadl/tests/ui_test.py`

## Verification
- `pytest modules/cli_tui/tests`
- `pytest modules/mangadl/tests`
