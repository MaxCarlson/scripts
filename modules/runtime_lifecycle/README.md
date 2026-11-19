# runtime-lifecycle

`runtime_lifecycle` provides shared, ownership-aware management of Windows
Scheduled Tasks for user-session runtimes. It generates and parses canonical
Task Scheduler XML, reports semantic drift, and offers safe task lifecycle
operations. The package has no runtime dependencies beyond Python 3.10+.

Tasks default to the current user's interactive token with least privilege.
This lets hotkeys and desktop processes run in the logged-in session; it does
not create a Session 0 Windows service. Other principals and trigger types are
modeled for future consumers, with privileged operations gated by the backend.

Tasks are namespaced under `\\Scripts` and marked with an owner, name, schema,
and deterministic spec hash. Existing tasks without a matching ownership marker
are treated as conflicts. `force` may only authorize replacement during apply;
removal always requires verified ownership.

## CLI

Create a UTF-8 JSON file describing a task, then preview it before applying:

```json
{
  "owner": "example",
  "name": "worker",
  "executable": "C:/Python/pythonw.exe",
  "args": ["-m", "example.worker"],
  "working_dir": "C:/Users/user",
  "triggers": [{"type": "logon", "delay": "PT5S"}]
}
```

```powershell
runtime-lifecycle preview --input-file .\task.json --json
runtime-lifecycle apply --input-file .\task.json --apply
runtime-lifecycle status --owner example --name worker --json
runtime-lifecycle disable --owner example --name worker --apply
runtime-lifecycle remove --owner example --name worker --apply
```

Mutating CLI operations preview by default. `--force` is available only for
`apply`; `remove` always refuses a task whose owner marker or principal does not
match.
