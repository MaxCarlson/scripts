# Stage S1 - Guard and Track

## Scope

- Classify gallery-dl extractors whose URL expands a broad collection rather
  than one manga/gallery.
- Reject those URLs by default and expose an explicit short/long opt-in.
- Initialize versioned partial metadata before backend launch.
- Capture gallery-dl's computed archive key after each successful file and
  associate it with the file's partial-relative path.
- Preserve metadata/manifests on interruption or failure and remove them
  before a successful merge.

## Verification

- Focused backend, CLI, and worker tests cover normal URLs, blocked collection
  URLs, explicit opt-in, manifest recording, resume, and successful merge.
