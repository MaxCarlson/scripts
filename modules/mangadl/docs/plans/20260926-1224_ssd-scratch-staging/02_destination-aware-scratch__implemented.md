# Stage 2 — Destination-aware scratch and control staging

User feedback required `mangadl run -S/--scratch` and avoidance of duplicate network downloads when the destination already holds files.

Implemented before manual acceptance:

- `-S/--scratch` in normal run; no option leaves legacy behavior intact.
- Gallery-dl-only subprocess adapter checks the final library filename before network download. It does not modify ordinary gallery-dl commands. Manga18FX receives the true existing-library root.
- Active archive, state, and run logs live on scratch; archive/state/log history syncs to their canonical paths at run end. A failed run with scratch partials defers archive sync to prevent false completed-file skips without scratch.
- Archive-aware partial cleanup updates both archive copies and the scratch conflict baseline so an interrupted run remains resumable.
- Cover matching uses only folders promoted by the job rather than a library-wide B: scan.
- Existing destination partials and unverified scratch backends/layouts are rejected before downloads.
- Synthetic tests cover mapped duplicate checks, control sync/resume/conflict, archive-aware cleanup, CLI routing, and promotion failure. No production download was started.

Remaining gate: bounded user validation on known-small gallery-dl and Manga18FX inputs, with measured B: activity. In particular, minimum destination metadata checks and the final B: copy are expected; a zero-I/O B: run is impossible while preserving duplicate and archive safety.
