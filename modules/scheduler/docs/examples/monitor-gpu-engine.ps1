param(
    [Parameter(Mandatory = $true)]
    [string]$ExcludeProcessName
)

$ErrorActionPreference = 'Stop'

# Reports GPU engine use by other processes. The scheduler parses stdout as JSON.
$processNames = @{}
Get-Process -ErrorAction Stop | ForEach-Object {
    $processNames[[int]$_.Id] = $_.ProcessName
}

$totals = @{}
$validCounterCount = 0
$counterError = $null
try {
    $samples = Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction Stop
    foreach ($sample in $samples.CounterSamples) {
        if ($sample.Path -notmatch 'pid_(?<pid>\d+).*engtype_(?<engine>[^_\\)]+)') {
            continue
        }
        $validCounterCount++
        $processId = [int]$Matches.pid
        $engine = $Matches.engine.ToLowerInvariant()
        if ($processNames.ContainsKey($processId) -and $processNames[$processId] -ieq $ExcludeProcessName) {
            continue
        }
        $field = "other_gpu_${engine}_pct"
        if (-not $totals.ContainsKey($field)) { $totals[$field] = 0.0 }
        $totals[$field] += [double]$sample.CookedValue
    }
}
catch {
    # Keep stdout valid JSON while reporting unavailable telemetry. The rule's
    # counter-count condition prevents missing data from being treated as idle.
    $counterError = $_.Exception.Message
}

$result = [ordered]@{}
$engineValues = @()
foreach ($engine in @('3d', 'compute', 'copy', 'videoencode', 'videodecode')) {
    $field = "other_gpu_${engine}_pct"
    $value = [math]::Round([math]::Min(100.0, [math]::Max(0.0, [double]$totals[$field])), 1)
    $result[$field] = $value
    $engineValues += $value
}
$result['other_gpu_max_pct'] = ($engineValues | Measure-Object -Maximum).Maximum
$result['gpu_engine_counter_count'] = $validCounterCount
if ($counterError) { $result['monitor_error'] = $counterError }
$result | ConvertTo-Json -Compress
