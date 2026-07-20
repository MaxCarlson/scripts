# HDPornComics Backend Handoff

## Request

Add `hdporncomics.com` support to the existing `mangadl` Python project. This
must work automatically for both direct `mangadl run <url>` use and the
existing URL-file mode; it must not be a separate, HDPornComics-only command
or option.

The required package/executable dependency is `hdporncomics`, and it must be
included in this module's `pyproject.toml` in the project-appropriate way.

## Non-negotiable URL behavior

- Parse URLs properly (for example with `urllib.parse.urlparse`); never route
  by hostname substring.
- Accept **only** the normalized hosts `hdporncomics.com` and
  `www.hdporncomics.com`.
- Only paths beginning with `/manhwa/` use this backend.
- Reject deceptive hosts such as `hdporncomics.com.example`,
  `not-hdporncomics.com`, and hosts merely containing the target name.
- Inspect output must identify a qualifying URL as backend `hdporncomics` and
  classification `manhwa`.

## Backend design required

Implement HDPornComics as a normal registry/backend entry rather than adding
special hostname checks throughout CLI, URL-file, job, retry, or status code.
The backend abstraction should make future external tools follow the same
shape:

1. URL matching/classification.
2. Command construction.
3. Executable discovery.
4. Subprocess execution.
5. Output validation.

Inspect the existing project before choosing names. Reuse its existing URL
routing, persisted jobs, retries, status reporting, destination logic, and
concurrency controls wherever possible. Preserve existing nhentai and all
other downloader behavior.

## Invocation contract

For an accepted manhwa URL, run exactly one process with an argument list
(never `shell=True`):

```text
hdporncomics --directory <output-root> --threads <threads> --force --manhwa <url>
```

Important details:

- `<output-root>` is the existing job destination/output root. The executable
  creates its own title directory below it and chapter directories below the
  title directory. Do not pre-create/title-append another same-named directory
  (`Title/Title/` must not happen).
- Keep `mangadl` job-level concurrency independent from the executable's
  `--threads` value.
- Default to eight internal threads conservatively, unless an existing
  appropriate internal-thread setting should be reused.
- Always include `--force`, allowing resumption of incomplete metadata-only
  directories.
- A nonzero exit code is a failed job. Do not substitute another downloader.
- Retrying must preserve the original job destination and must not delete
  existing chapters or images.

## Executable discovery order

Resolve the executable in precisely this order:

1. Explicit configured or CLI-provided value, if the project already provides
   one (add an ergonomic option/config only if needed by the existing design).
2. `HDPORNCOMICS_EXECUTABLE`.
3. `shutil.which("hdporncomics")`.
4. On Windows, `shutil.which("hdporncomics.exe")`.

If unavailable, report an actionable installation instruction:

```text
python -m pip install --upgrade hdporncomics
```

Target platforms are Windows 11, WSL2/Linux, and Termux.

## URL-file and job behavior

The existing `mangadl run` URL-file input must accept files that contain only
manhwa URLs and files mixed with existing supported sites. Existing blank-line,
comment, duplicate, malformed-line, and direct-command-line-URL semantics must
remain intact.

For **each accepted line**:

1. Persist a separate job.
2. Route it independently.
3. Launch one downloader process for that URL.
4. Let the existing job-level concurrency scheduler control parallel jobs.
5. Let the executable make one separate title directory per manhwa under the
   shared output root.
6. Continue other jobs after one fails.

Failed HDPornComics jobs must enter the same retry path as other jobs.

## Output validation

After a successful exit, validate that expected title/chapter output contains
chapter images (use the project’s existing image/metadata conventions if any).
If a successful command leaves only metadata such as `info.json` and no images,
warn/report that condition rather than presenting it as a complete download.
Never delete existing data as part of validation or retry.

## Tests required

Use pytest and mock subprocesses; normal tests must make no live network
requests. Add focused tests for:

- Accepted hosts and `/manhwa/` routing/classification.
- Rejected deceptive hostnames and non-manhwa paths.
- Exact command arguments, including `--force`, `--threads`, and paths with
  spaces.
- URL file with multiple manhwa URLs.
- Mixed-backend URL file.
- One persisted job and one subprocess invocation per accepted URL.
- Separate title output directories (and no duplicate title nesting).
- Missing executable discovery/error text.
- Nonzero-process-exit failure.
- Retry preserving destination and using the same backend.
- Successful chapter-image output.
- Successful exit with `info.json` only produces a warning/incomplete status.
- Regression coverage for existing downloaders.

Run the existing test suite before changing expectations, then run old and new
tests together. Include the exact commands and output in the final handoff.

## Repository context observed on 2026-07-19

- Project path: `C:\\Users\\mcarls\\src\\scripts\\modules\\mangadl`.
- It has `mangadl/`, `tests/`, `pyproject.toml`, `README.md`, and `docs/`.
- Current project docs declare an active initial-implementation plan at
  `docs/plans/20260712-1540_mangadl-initial-implementation/`; read its
  `HANDOFF.md`, `STATUS.md`, `checklist.md`, and numbered stage documents
  before changing source.
- `docs/HANDOFF.md` records continuous implementation as already user-approved,
  but still requires testing, documentation, and final manual production
  approval. It explicitly says no commits/merges are authorized without a
  further user request.
- The parent `scripts` worktree has unrelated modified files in sibling modules
  and an unrelated untracked `MANGADL_IMPLEMENTATION_PLAN.md`; do not alter or
  absorb them. The target `mangadl` directory itself did not appear in the
  short status output at the time this note was written.

## Recommended first steps for the next Codex instance

1. Read applicable `AGENTS.md` and the active-plan documents listed above.
2. Run `git status --short` from the actual mangadl project context and retain
   all existing user changes.
3. Inspect `pyproject.toml`, package layout, CLI entrypoint, routing/inspection,
   persisted job model/store, run scheduler, retry implementation, and current
   tests.
4. Map the existing downloader interface/registry. Extend it minimally with
   the HDPornComics backend and add tests alongside the closest downloader
   tests.
5. Update the active plan/checklist/status/handoff as required by the project
   instructions, then report exact verification evidence. Do not commit unless
   explicitly asked.
