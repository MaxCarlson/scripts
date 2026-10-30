# Runtime resource policy checklist

- [x] Remove implicit host-RAM percentages and fixed memory floors.
- [x] Keep explicit user-configured limits effective through dispatch and model transitions.
- [x] Check LM Studio estimates against measured available host and GPU capacity.
- [x] Preserve model identity, busy-state, context, command, termination and no-retry safeguards.
- [x] Record resource observations without force-killing shared processes.
- [x] Add regression coverage for defaults, opt-in thresholds, estimate capacity and missing telemetry.
- [x] Document the current policy and supersede historical threshold guidance.
- [x] Integrate sanitized Qwen findings and reusable fixtures; exclude generated session evidence.
- [ ] Complete final integration review, validation and merge.
