# Manga18FX Backend Checklist

- [x] Recognize valid Manga18FX series-root URLs.
- [x] Reject deceptive domains and chapter URLs.
- [x] Parse series titles and chapter links.
- [x] Sort numbered chapters naturally.
- [x] Use stable chapter-number prefixes, including fractional chapters.
- [x] Parse `source`, lazy-source, `srcset`, and image fallbacks.
- [x] Deduplicate repeated chapter and image links.
- [x] Sanitize Windows-incompatible directory names.
- [x] Download through per-job partial directories.
- [x] Merge successful downloads into the destination root.
- [x] Skip image files already present in the partial or final destination.
- [x] Pass the existing cookies-file option to the native backend.
- [x] Add offline parser/routing/worker tests.
- [x] Bump the module minor version.
- [ ] Run the complete mangadl pytest suite locally.
- [ ] Run a single-series live smoke test in a disposable destination.
- [ ] Verify a second smoke run skips existing files and exits successfully.
- [ ] Run the full URL-file batch only after smoke validation.
