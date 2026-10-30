# Implement the session lifecycle state machine

Implement `transition(state, event)` in `src/session_state.py` using the lifecycle contract below. Return the next state as a string. Raise `ValueError` for an unknown state, unknown event, or disallowed transition.

States: `idle`, `queued`, `running`, `succeeded`, `failed`, `cancelled`.

Allowed transitions:

- `idle` + `submit` → `queued`
- `queued` + `start` → `running`
- `queued` + `cancel` → `cancelled`
- `running` + `succeed` → `succeeded`
- `running` + `fail` → `failed`
- `running` + `cancel` → `cancelled`
- Any terminal state (`succeeded`, `failed`, `cancelled`) + `reset` → `idle`

Do not modify other files.
