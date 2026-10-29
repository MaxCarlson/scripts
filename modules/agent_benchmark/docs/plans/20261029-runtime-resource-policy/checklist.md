# Runtime resource policy checklist

- [x] Remove implicit 90% host RAM rejection/cancellation.
- [x] Remove fixed 4 GiB available-RAM floor from default dispatch checks.
- [x] Review and replace arbitrary GPU/combined reserves and model-size multiplier.
- [x] Keep explicit user-configured percentage limits effective end to end.
- [x] Add tests for default behavior, explicit thresholds, estimate capacity, missing telemetry,
      allocation failure, and no blind retry.
- [x] Update docs and version.
- [x] Run focused tests and lint.
- [ ] Commit/push the coherent RAM-policy milestone on the investigation branch.
