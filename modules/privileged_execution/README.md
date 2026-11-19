# PrivExec (`privileged_execution`)

Version: 0.1.0

Least-privilege local Windows 11 session broker (`PrivExecBroker`, C# / .NET 10) and non-elevated client CLI (`privexec`, Python) for narrowly authorized administrative operations, with Resource Coordinator H4 reference integration.

See [docs/README.md](docs/README.md), [docs/HANDOFF.md](docs/HANDOFF.md), and [docs/WINDOWS_VALIDATION.md](docs/WINDOWS_VALIDATION.md).

## Quickstart

```powershell
# Build C# broker & unit tests
pwsh -NoProfile -File .\scripts\Build-PrivExecBroker.ps1 -IncludeTests

# Run C# and Python tests
dotnet .\broker\bin\PrivExecBroker.Tests.dll
python -m pytest -v

# Preview installation (dry-run by default)
pwsh -NoProfile -File .\scripts\Install-PrivExec.ps1 -Json
```
