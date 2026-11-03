#requires -Version 7.0
<#! Non-inferencing, read-only host probes. Output contains no raw service responses. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$HarborPython,
    [string]$CoordinatorPython = 'python',
    [string]$MonitorHostUrl = 'http://127.0.0.1:8788',
    [string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$moduleRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$coreRoot = Join-Path (Split-Path $moduleRoot) 'benchmark_core'
$oldPythonPath = $env:PYTHONPATH
$oldHarborPython = $env:HARBOR_025_PYTHON
$oldCostMap = $env:LITELLM_LOCAL_MODEL_COST_MAP
$env:PYTHONPATH = @($moduleRoot, $coreRoot, $oldPythonPath) -ne '' -join [IO.Path]::PathSeparator
$env:HARBOR_025_PYTHON = $HarborPython
$env:LITELLM_LOCAL_MODEL_COST_MAP = 'True'

function Invoke-Bounded([string]$Exe, [string[]]$Arguments, [int]$TimeoutMs = 8000) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Exe
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($arg in $Arguments) { [void]$start.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    $start.WorkingDirectory = $moduleRoot
    try {
        if (-not $process.Start()) { return @{ exit_code = $null; timed_out = $false; output = $null } }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutMs)) {
            $process.Kill()
            $process.WaitForExit()
            return @{ exit_code = $null; timed_out = $true; output = $null }
        }
        $null = $stderr.GetAwaiter().GetResult()
        return @{ exit_code = $process.ExitCode; timed_out = $false; output = $stdout.GetAwaiter().GetResult() }
    } catch { return @{ exit_code = $null; timed_out = $false; output = $null } }
    finally { $process.Dispose() }
}

try {
    $checks = [ordered]@{}
    $script = @'
import json
from agent_benchmark.study_task_integrity import EXPECTED, verify_study_task_trees
names=list(EXPECTED)
rows=[dict(task_id=n, git_url='https://github.com/laude-institute/harbor-datasets.git', git_commit_id='f30b14415dd733c83627204bad0af69a89ceb46f', git_path='datasets/aider_polyglot/'+n) for n in names]
try:
    print(json.dumps({'status':'PASS','tasks':verify_study_task_trees({'tasks':names,'provenance':{'registry_resolution':{'tasks':rows}}})}))
except Exception as error:
    print(json.dumps({'status':'FAIL','error_type':type(error).__name__}))
    raise SystemExit(1)
'@
    $probe = Invoke-Bounded $CoordinatorPython @('-B', '-c', $script) 30000
    if ($probe.exit_code -eq 0) {
        try { $checks.task_identity = $probe.output | ConvertFrom-Json -AsHashtable } catch { $checks.task_identity = @{ status='FAIL' } }
    } else { $checks.task_identity = @{ status='FAIL'; exit_code=$probe.exit_code; timed_out=$probe.timed_out } }
    $checks.task_identity.exit_code = $probe.exit_code
    $checks.task_identity.timed_out = $probe.timed_out
    $contract = Invoke-Bounded $CoordinatorPython @('-B','-m','pytest','tests/harbor_prompt_runtime_test.py','tests/spec_verification_policy_test.py','tests/study_task_integrity_test.py','-q','-p','no:cacheprovider') 60000
    $checks.synthetic_contract = @{ status=$(if ($contract.exit_code -eq 0) { 'PASS' } else { 'FAIL' }); exit_code=$contract.exit_code; timed_out=$contract.timed_out; scope='synthetic, no inference' }
    $docker = Invoke-Bounded 'docker' @('info','--format','{{.ServerVersion}}')
    $checks.docker = @{ status = $(if ($docker.exit_code -eq 0 -and $docker.output.Trim()) { 'PASS' } else { 'UNKNOWN' }); exit_code=$docker.exit_code; timed_out=$docker.timed_out }
    $opencode = Invoke-Bounded 'pwsh' @('-NoProfile','-Command','opencode --version')
    $checks.host_opencode = @{ status=$(if ($opencode.exit_code -eq 0 -and $opencode.output.Trim() -eq '1.19.5') { 'PASS' } else { 'UNKNOWN' }); exit_code=$opencode.exit_code; timed_out=$opencode.timed_out; scope='host binary only; Harbor container installation remains unverified' }
    $lms = Invoke-Bounded 'lms' @('ps','--json')
    $checks.loaded_model = @{ status='UNKNOWN'; exit_code=$lms.exit_code; timed_out=$lms.timed_out; reason='Inspect loaded identity, model file and settings separately; raw model output omitted.' }
    if ($lms.exit_code -eq 0) {
        try {
            $models = @($lms.output | ConvertFrom-Json)
            $safeModels = @($models | Where-Object { $_ -and $_.identifier } | ForEach-Object {
                [ordered]@{ identifier=$_.identifier; model_key=$_.modelKey; status=$_.status; context_length=$_.contextLength; size_bytes=$_.sizeBytes }
            })
            $checks.loaded_model.models = $safeModels
            if (@($safeModels | Where-Object { $_.identifier -eq 'qwen38_23GB' }).Count -eq 1) {
                $checks.loaded_model.status = 'PASS'
                $checks.loaded_model.reason = 'Alias observed; file digest, quantization and full effective settings remain unknown.'
            }
        } catch { $checks.loaded_model.reason = 'Loaded model JSON could not be interpreted safely.' }
    }
    $monitorScript = @'
import json, sys
try:
    from agent_benchmark.suite_monitor import validate_monitor
    r=validate_monitor(agent='opencode',model='openai/qwen38_23GB',monitor_host_url=sys.argv[1],recording='content',api_format='openai_chat_completions')
    print(json.dumps({'status':'PASS','recording_mode':r.get('recording_mode'),'recording_healthy':r.get('recording_healthy'),'dropped_observations':r.get('dropped_observations')}))
except Exception as error:
    print(json.dumps({'status':'UNKNOWN','error_type':type(error).__name__}))
    raise SystemExit(1)
'@
    $monitor = Invoke-Bounded $CoordinatorPython @('-B','-c',$monitorScript,$MonitorHostUrl) 15000
    try { $checks.monitor = $monitor.output | ConvertFrom-Json -AsHashtable } catch { $checks.monitor = @{ status='UNKNOWN' } }
    if (-not $checks.monitor) { $checks.monitor = @{ status='UNKNOWN' } }
    $checks.monitor.exit_code = $monitor.exit_code
    $checks.monitor.timed_out = $monitor.timed_out
    $checks.effective_settings = @{ status='UNKNOWN'; reason='Capture model-file identity and effective context, sampling, output and reasoning settings without inference.' }
    $checks.web_network = @{ status='UNKNOWN'; reason='Verify native web-tool denial and separately establish shell/network restrictions.' }
    $checks.execution_tree_binding = @{ status='UNKNOWN'; reason='Repeat task identity check immediately before dispatch; no live trial was run.' }
    $evidence = [ordered]@{ schema='spec-verification-host-preflight-v1'; created_utc=[DateTime]::UtcNow.ToString('o'); inference_dispatched=$false; checks=$checks }
    $json = $evidence | ConvertTo-Json -Depth 12
    if ($OutputPath) {
        $target = [IO.Path]::GetFullPath($OutputPath)
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json + [Environment]::NewLine)
        $file = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $file.Write($bytes, 0, $bytes.Length) } finally { $file.Dispose() }
    }
    Write-Output $json
    if ($checks.task_identity.status -eq 'FAIL' -or $checks.synthetic_contract.status -eq 'FAIL') { exit 1 }
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:HARBOR_025_PYTHON = $oldHarborPython
    $env:LITELLM_LOCAL_MODEL_COST_MAP = $oldCostMap
}
