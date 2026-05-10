---
plan_index: 0002
origin: user
status: partial
source_file: versioning_and_scripts_cohesion_plan.md
---

Can we change it so that scripts/modules get a major version number bump if they need to have a new bin/module.cmd file created for them? If having a .cmd file need recreation is more dramatic a change then requiring a reinstall, and if reinstalls are actually ever required with editable installs, we can make that the second number in the versioning X.YY.ZZZ (where X is major version and indicates needing a recreation of a bin/module.cmd file, Y is second level of changes and indicates a reinstall is required - if reinstalls are ever required like mentioned above, if not ignore this and set Y equal to whatever you think makes sense) or whatever the standard is for major/minor/whatever versioning). Basically, I want the versioning setup for modules such that ./bootsrap.ps1/sh and the setup process can check the installed version of modules and uninstall them/reinstall them/create new bin/module/cmd files for them if their major version has changed, etc. And recognize that if it hasn't they don't need to replace the existing bin/module.cmd or reinstall, etc.

Can we create a set of guidelines for LLMs to use for our scripts modules, or a least create a single file, then point claude/codex/gemini/copilot/ CLIs toward this scripts preferences file - such as the new versioning syntax and how it relates to cmd/reinstall/etc requirements, the preference for all modules to use the subcommand setup we're cuurrently using in ytaedl if the arguments number over 7 and it makes sense to use subcommands, the prefence for all args to have a --full-length and -f abbreviated version, etc.

Also, my existing _partial/ dirs do have .version files..:
```
    Directory: B:\stars\vixen\_partial

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a---            5/9/2026  1:36 PM             71 .version

    Directory: B:\stars\waka_misono\_partial

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a---            5/9/2026  1:42 PM             70 .version

    Directory: B:\stars\yuki_rino\_partial

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a---            5/9/2026  1:30 PM             71 .version

╭─ pwsh     stars   147ms                                                                                                    docker-desktop     9,14:24 
╰─ cat .\*\_partial\*.version
{
  "partial_version": "2.0.0",
  "created_at": 1778357735.0756476
}
{
  "partial_version": "2.0.0",
  "created_at": 1778361532.988847
}
{
  "partial_version": "2.0.0",
  "created_at": 1778359646.18689
```
