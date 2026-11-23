# Scripts Repository Handoff

## Current migration

MangaDL, YTAEDL, and the AEBN downloader are being relocated to the private `pscripts` repository. Their current private source is pinned at `4e10cc3` on `codex/media-modules-private-20261123`.

The public migration branch is `codex/media-modules-public-20261123`. It removes the public source copies and associated personal runtime artifacts while retaining generic modules such as `compresser`, `kavita`, `procparsers`, `url_file_tools`, and `video_dataset_tools`.

Selected historical media plans and test records were preserved in the private archive at `pscripts/docs/archive/public-scripts/`. The public tree keeps only this concise migration handoff in place of the historical working log.

## Integration notes

Scripts PR #22 contains the shared-library distribution migration required by some private package dependencies. Keep that dependency in mind when reviewing setup results and resolving overlap in `scripts_setup/launcher_generator.py`.

The public PR must retain the exact private submodule pin and run the launcher refresh after private package installation so all declared console commands are represented in `scripts_manifest.json` and `bin/`.
