# Manga18FX Backend Implementation Plan

## Objective

Add a native `manga18fx.com` series backend to `mangadl` so a URL file containing series-root URLs can be downloaded with the existing `mangadl run` workflow.

## Scope

- Recognize `https://manga18fx.com/manga/<slug>` and `www` equivalents.
- Parse the series title and complete chapter list.
- Parse chapter image sources, including lazy-loaded and `srcset` forms.
- Write one sanitized manga folder containing naturally ordered chapter folders and ordered image files.
- Reuse mangadl worker retries, partial directories, progress accounting, state, logs, and final merge behavior.
- Support an optional Netscape/Mozilla cookies file through the existing `-C/--cookies` option.
- Keep live-site calls out of default pytest runs.

## Stages

1. Add the native parser/downloader module.
2. Add backend routing and worker integration.
3. Add offline tests for parsing, URL validation, naming, and worker command construction.
4. Bump the module minor version and update documentation.
5. Run local module validation and a controlled single-series smoke test before using the full URL file.

## Validation

```powershell
python -m pip install -e .\modules\mangadl
pytest .\modules\mangadl\tests -v
mangadl inspect -u 'https://manga18fx.com/manga/an-invisible-kiss-uncensored/'
mangadl run -u 'https://manga18fx.com/manga/an-invisible-kiss-uncensored/' -d .\manga18fx-smoke -a .\manga18fx-smoke-archive.sqlite3 -s .\manga18fx-smoke-state.sqlite3 -w 1
```

The smoke destination, state database, and archive are intentionally separate from production data.
