# URL File Tools Implementation Plan

## Goal

Create a cross-platform, dry-run-first Python CLI that supersedes the supplied
PowerShell URL-list cleanup workflow and adds safe merge, domain-split, and
downloader-archive matching modes. The same behavior is exposed as an importable
library for future mangadl and ytaedl CLI integration.

## Invariants

- No input or output file is changed without `--apply`.
- Duplicate removal is explicitly prompted or selected by policy.
- File-list selections cannot escape the target folder.
- Domain splitting uses registered domains, not a naive last-two-label rule.
- Only an exact leading `m.` hostname label is removed.
- Output and report paths are excluded from future source discovery.
- Source locations and summary statistics make every planned data loss visible.
- Archive adapters are read-only and distinguish direct URL evidence from
  gallery-dl's per-media keys.

## Stage 1

Implement package metadata, normalization, merge, and archive-match engines,
CLI, tests, documentation, help-registry integration, and repository dispatcher
validation.

## Stage 2

After Stage 1 manual validation, add thin `mangadl urls match` and
`ytaedl urls match` integrations that import the stable library API. Version,
test, and document both downstream CLIs without duplicating matcher logic.

## Acceptance

- Numbered prefixes and optional duplicates are handled with preserved text encoding.
- Folder, explicit file names, and manifest selection work.
- Single-file and registered-domain split output work.
- Dry-run reports sources, URLs, duplicates, domains, mobile rewrites, invalid rows, and outputs.
- Apply mode prompts for duplicate removal by default and supports automation policies.
- Focused tests, compile, lint, help, and dispatcher validation pass.
- ytaedl text archives and mangadl URL-level state databases classify downloaded
  and not-downloaded URLs without writing to archive storage.
