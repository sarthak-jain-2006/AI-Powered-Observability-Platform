# demo.ps1 - end-to-end demonstration.
#
# Shows the full loop in one command: healthy system -> fault injected ->
# anomaly detected -> root cause localised -> remediation decided -> guardrails
# applied. Everything is scored against the ground truth the fault runner
# writes, so nothing shown here is hand-checked.
#
# Usage:
#   .\demo.ps1                              # db-down, z-score detector
#   .\demo.ps1 -Fault payment-failure
#   .\demo.ps1 -Model iforest               # use the trained Isolation Forest
#   .\demo.ps1 -Fault db-delay -Severity subtle

param(
    [string]$Fault            = "db-down",
    [ValidateSet("subtle","moderate","severe")][string]$Severity = "severe",
    [ValidateSet("zscore","iforest")][string]$Model = "zscore",
    [int]   $BaselineSeconds  = 150,
    [int]   $FaultSeconds     = 150,
    [int]   $RecoverySeconds  = 90,
    [int]   $Vus              = 6,
    [switch]$KeepLoad
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Banner($text) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor DarkCyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor DarkCyan
}
function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Yellow }
function Note($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }

function Countdown($seconds, $label) {
    $end = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $end) {
        $left = [int]($end - (Get-Date)).TotalSeconds
        Write-Host -NoNewline ("`r    {0}: {1,4}s " -f $label, $left)
        Start-Sleep -Seconds 5
    }
    Write-Host ("`r    {0}: done      " -f $label)
}

Banner "Microservice Anomaly Detection - Live Demo"
Note "fault    : $Fault / $Severity"
Note "detector : $Model"

# --- Preflight -------------------------------------------------------------
Step "Checking the stack"
$running = (docker compose ps --status running --format "{{.Name}}") -split "`n" | Where-Object { $_ }
if ($running.Count -lt 10) {
    Write-Host "Only $($running.Count) containers running. Run: docker compose up -d" -ForegroundColor Red
    exit 1
}
Note "$($running.Count) containers healthy"

if ($Model -eq "iforest" -and -not (Test-Path (Join-Path $root "ai-engine/models"))) {
    Write-Host "No trained models. Run: docker exec ai-engine python train.py" -ForegroundColor Red
    exit 1
}

# Mark where this demo starts so the report covers only this run rather than
# every fault ever injected into the dataset.
$since = (Get-Date).ToUniversalTime().AddSeconds(-30).ToString("o")

# --- Load ------------------------------------------------------------------
# Flat load throughout: a ramp partway through would itself look anomalous and
# muddy which part of the signal the fault actually caused.
$total = $BaselineSeconds + $FaultSeconds + $RecoverySeconds + 60
$existingK6 = docker ps --filter "name=k6" --format "{{.Names}}" | Select-Object -First 1
$startedLoad = $false

if ($existingK6) {
    Step "Load already running ($existingK6) - reusing it"
} else {
    Step "Starting load ($Vus VUs)"
    docker compose run -d --rm k6 run --vus $Vus --duration "${total}s" --quiet /scripts/checkout.js 2>&1 | Out-Null
    $startedLoad = $true
    Start-Sleep -Seconds 5
    Note "load generator up"
}

try {
    Step "Phase 1/3  Establishing a healthy baseline"
    Countdown $BaselineSeconds "baseline"

    Step "Phase 2/3  Injecting fault: $Fault / $Severity"
    & (Join-Path $root "faults/run-fault.ps1") -Fault $Fault -Action inject -Severity $Severity
    $injectedAt = Get-Date
    Countdown $FaultSeconds "fault active"

    Step "Phase 3/3  Recovering"
    & (Join-Path $root "faults/run-fault.ps1") -Fault $Fault -Action recover -Severity $Severity
    Countdown $RecoverySeconds "settling"
}
finally {
    # docker writes progress to stderr, which PowerShell treats as terminating
    # while ErrorActionPreference is Stop. Unguarded, cleanup aborts the run and
    # the report - the only part that matters - never prints.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($startedLoad -and -not $KeepLoad) {
        Step "Stopping load"
        try { docker compose rm -f -s k6 2>&1 | Out-Null } catch {}
    }
    $ErrorActionPreference = $prev
}

# --- Results ---------------------------------------------------------------
# Run the analysis inside the container: numpy/scikit-learn/joblib live there,
# not on the host, and both the data and models directories are bind-mounted so
# it sees exactly the same files.
Banner "1. DETECTION AND ROOT CAUSE"
docker exec ai-engine python detect.py --model $Model --since $since

Banner "2. REMEDIATION DECISION"
docker exec ai-engine python remediate.py --model $Model --since $since --allow-destructive

Banner "Demo complete"
Note "Nothing was executed - remediation ran in dry-run throughout."
