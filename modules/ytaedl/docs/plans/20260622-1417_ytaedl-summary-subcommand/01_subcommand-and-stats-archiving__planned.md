# Stage 01: Subcommand and Stats Archiving

## Objective
Implement background stats writing inside the manager run loop, stats archiving on shutdown, archive pruning on manager boot, the `ytaedl summary` command dispatch, TUI output rendering, and unit tests.

## Checklist
* [ ] Background writing loop in `manager.py`.
* [ ] Archiving logic on clean/unclean shutdown.
* [ ] Boot pruning logic capping stats files count at 50.
* [ ] Subcommand register and handler logic in `cli.py`.
* [ ] Format layout printout with ANSI color codes and column alignment.
* [ ] Unit tests covering all conditions.
