<!-- version: 0.1.0 -->
# run_tests.py

Interactive pytest runner with menus for verbosity and scope.

## Usage

```
python pyscripts/run_tests.py [options]
```

With no arguments, presents two menus: verbosity level and test scope. All
menus can be bypassed with CLI flags for scripted use.

## Verbosity levels

| # | Label   | pytest flags              |
|---|---------|---------------------------|
| 1 | Minimal | `--tb=no -q`              |
| 2 | Short   | `--tb=short -q`           |
| 3 | Normal  | `--tb=short`              |
| 4 | Verbose | `--tb=short -v`           |
| 5 | Full    | `--tb=long -v -s`         |

## Scope options

| Option      | Runs                                          |
|-------------|-----------------------------------------------|
| All         | `modules/` + `pyscripts/`                    |
| Modules     | `modules/` only                               |
| Pyscripts   | `pyscripts/` only                             |
| Specific    | Pick from a numbered list of discovered targets |

## Options

```
-V, --verbosity 1-5     Pre-select verbosity (skips menu)
-s, --scope             Pre-select scope: all|modules|pyscripts|specific
-m, --module NAME       Target a module by name (repeatable)
-p, --pyscript NAME     Target a pyscript by name (repeatable)
-n, --dry-run           Print the command without running pytest
-q, --quiet             Suppress the command echo
```

## Examples

```bash
# Fully interactive
run_tests

# Scope pre-selected, verbosity from menu
run_tests -s modules

# Fully non-interactive
run_tests -V 2 -s all
run_tests -V 4 -m filter_prune -m scripts_help
run_tests -V 1 -p zip_for_llms
```
