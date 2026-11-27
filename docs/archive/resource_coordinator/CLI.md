# Resource Coordinator CLI

Resource Coordinator 1.0.0 provides the compact `rc` command alongside the
existing `resource-coordinator` and `gpu-coordinator` names. The canonical
top-level commands are `status`, `doctor`, `telemetry`, `miner`, `gaming`,
`maintenance`, `recover`, `logs`, `service`, `system`, `config`, and `help`.
The historical `control`, `check`, and root command spellings remain available
as compatibility paths.

## Status and diagnostics

```powershell
rc status
rc status --all
rc status inference -j
rc status maintenance
rc telemetry
rc doctor
```

Global `-j/--json`, `-v/--verbose`, and `-C/--color auto|always|never` can be
placed before or after the command. Automatic color honors `NO_COLOR` and
terminal detection. JSON commands emit one structured document without Rich
formatting.

Inference status describes Coordinator-managed leases and durable request
records. Its `coverage` field is separate from `classification`; `quiescent`
does not prove physical GPU idleness. LM Studio activity is reported as
unavailable unless an injected observer provides fresh evidence for the exact
configured runtime identity. The default observer performs no network or
subprocess probe.

## Recovery and maintenance

`rc recover` and `rc recover -j` are read-only assessments. They never clear a
hold or control a process. `rc recover -a` is explicitly unavailable until
Part 3 supplies verified automatic recovery. `rc recover -f -n "reason"` is
the existing authenticated, audited inference operator override. The legacy
resource/reason flags remain distinct:

```powershell
rc recover -r gpu.inference -n "reviewed"
rc service recover --resource gpu.inference -r "reviewed"
```

Maintenance reconciliation is separate from inference recovery:

```powershell
rc maintenance status
rc maintenance reconcile
rc maintenance reconcile -f -r "operator verified external process termination and GPU restoration"
```

The default maintenance reconciliation is read-only. Forced reconciliation is
an authenticated, reasoned operator override and is refused unless the server
reports `recovery_required`. The CLI checks the current operation/session IDs
and requires the matching audited release disposition before reporting
success. It never clears maintenance through `rc recover` or legacy miner
control endpoints.

Offline recovery output is labeled `offline_diagnostic_only` and `blocked`.
It may summarize local journal and upgrade-receipt state, but that snapshot
cannot authorize recovery.
