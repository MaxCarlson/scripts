# Scratch staging handoff

Branch: `mangadl-ssd-scratch-20260926-1219`, based on `main`.

Stages 1 and 2 implemented locally. Stage 2 adds destination-aware skip checks,
scratch control databases/logs, and fail-closed backend routing after user
feedback. Await final synthetic verification and bounded manual validation on
E: and B:. Do not run an unknown-size live download or delete existing B:
partials for acceptance.

Read-only B:/E: preview found eight existing destination partial owners under
`B:\Hent\hent1imageperpage\_partial`. Scratch mode refuses a real run against
that library until those owners are finished, safely cleaned, or explicitly
migrated. None were modified.

No commit or push approval was given for this feature. Stage 2 is conditional on measured results.
