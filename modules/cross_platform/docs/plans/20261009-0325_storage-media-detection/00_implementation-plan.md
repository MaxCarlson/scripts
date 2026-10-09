# Storage media detection

## Objective

Provide a reusable classifier for the storage backing a path so callers can
distinguish solid-state, rotational, and unknown media without destructive
probing or elevation.

## Stage 1

- Add a typed public result and a `storage_media_for_path` function.
- On Windows, query the volume's seek-penalty property through the storage API.
- On Linux, resolve the mounted block device and inspect its rotational flag.
- Return unknown for unsupported, virtual, network, inaccessible, or ambiguous
  storage instead of guessing.
- Add mocked platform tests and live read-only validation where available.
- Export and document the API; bump the package minor version.

## Invariants

- Detection is read-only and does not benchmark the device.
- Detection does not require administrator/root privileges.
- Failures return unknown with a useful reason.
- Callers remain responsible for conservative policy when media is unknown.
