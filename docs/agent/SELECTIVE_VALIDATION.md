# Selective pytest validation

`Invoke-Tests.ps1 -Selective` runs explicitly selected pytest items for one or
more manifest targets in an already existing interpreter. It does not run a
target's bootstrap or named validation stages. Select a consumer with `-Target`
and at least one `-PytestNodeId`, `-PytestFile`, or `-PytestModule` selector.

```powershell
./Invoke-Tests.ps1 -Selective -Target development-ledger `
  -PytestFile tests/ledger_store_test.py -Workers 12 `
  -PythonExecutable .venv/Scripts/python.exe -TemporaryRoot $env:TEMP
```

`-Workers` accepts 0 through 16 and defaults to 0 (serial); a nonzero value
requires `-Selective`. Parallel execution
requires `pytest-xdist` already installed in the selected interpreter; the
validator does not install it. It uses local `loadfile` scheduling, disables
worker restarts, rejects remote transports, and requires a runtime provenance
receipt from the controller and every requested worker. Worker receipts record
import identities and unique pytest temporary roots. Results include the
requested worker count and are reusable only when the existing evidence rules
match the selection, worker count, interpreter, imports, dependencies and
unchanged source inputs.

Parallelize only reviewed selections whose tests and external resources are
safe to isolate. Tests sharing fixed ports, databases, subprocess lifecycles or
services should remain serial until their contracts demonstrate isolation.
High worker counts start one Python worker process per requested worker and can
cost more time and memory than they save for short selections. The command
remains local to the current checkout and existing interpreter.

On Windows, a two-test synthetic consumer run through the wrapper took 1.703s
serially, 5.656s with 12 workers, and 6.187s with 16. The validator recorded
the controller plus 12 or 16 workers and distinct temp roots for every worker.
This sample confirms the process fan-out and startup cost; the validator does
not sample peak RAM, so it cannot estimate memory for a larger suite. Prefer
serial mode for short selections and use high counts only when host capacity is
available.
