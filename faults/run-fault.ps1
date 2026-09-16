# Fault runner — reads a fault definition JSON and executes inject or recover.
# Usage:
#   .\faults\run-fault.ps1 -Fault db-down -Action inject
#   .\faults\run-fault.ps1 -Fault db-down -Action recover
#   .\faults\run-fault.ps1 -List

param(
    [string]$Fault,
    [ValidateSet("inject","recover")][string]$Action = "inject",
    # Severity picks an entry from the fault definition's severities block.
    # Omitted, the definition's own inject body is used, so existing invocations
    # keep behaving exactly as before.
    [ValidateSet("subtle","moderate","severe")][string]$Severity,
    [switch]$List
)

$defDir = Join-Path $PSScriptRoot "definitions"

function Get-AllDefs {
    Get-ChildItem -Path $defDir -Recurse -Filter *.json
}

if ($List) {
    Write-Host "Available faults:" -ForegroundColor Cyan
    Get-AllDefs | ForEach-Object {
        $d = Get-Content $_.FullName -Raw | ConvertFrom-Json
        Write-Host ("  {0,-16} [{1}] {2}" -f $d.name, $d.category, $d.description)
    }
    return
}

if (-not $Fault) { Write-Host "Specify -Fault <name> or -List" -ForegroundColor Red; return }

# Find the matching definition
$file = Get-AllDefs | Where-Object {
    (Get-Content $_.FullName -Raw | ConvertFrom-Json).name -eq $Fault
} | Select-Object -First 1

if (-not $file) { Write-Host "Fault '$Fault' not found. Use -List." -ForegroundColor Red; return }

$def = Get-Content $file.FullName -Raw | ConvertFrom-Json
$step = if ($Action -eq "inject") { $def.inject } else { $def.recover }

# Resolve the severity actually in force, for both the action and the label.
# Faults with no severities block are binary by nature - a stopped container is
# a total outage - so they record as severe rather than as missing data.
if ($def.severities) {
    $appliedSeverity = if ($Severity) { $Severity } else { "severe" }
    if ($Action -eq "inject") {
        $levelBody = $def.severities.$appliedSeverity
        if ($levelBody) {
            $step = [pscustomobject]@{
                endpoint = $def.inject.endpoint
                command  = $def.inject.command
                body     = $levelBody
            }
        } else {
            Write-Host "  no '$appliedSeverity' level defined; using the default body" -ForegroundColor DarkYellow
            $appliedSeverity = "severe"
        }
    }
} else {
    $appliedSeverity = "severe"
    if ($Severity -and $Severity -ne "severe") {
        Write-Host "  $($def.name) is binary; -Severity $Severity ignored" -ForegroundColor DarkYellow
    }
}

Write-Host "[$Action] $($def.name)/$appliedSeverity ($($def.category))" -ForegroundColor Yellow

# Ground-truth label. Written BEFORE the action so the recorded timestamp is
# never later than the effect it describes — a label that lags the fault would
# silently shift every detection-latency measurement.
$eventsFile = Join-Path $PSScriptRoot "../ai-engine/data/fault_events.jsonl"
$eventsDir  = Split-Path $eventsFile -Parent
if (-not (Test-Path $eventsDir)) { New-Item -ItemType Directory -Path $eventsDir -Force | Out-Null }

$event = [ordered]@{
    ts               = (Get-Date).ToUniversalTime().ToString("o")
    fault            = $def.name
    action           = $Action
    category         = $def.category
    type             = $def.type
    target_service   = $def.target.service      # the root-cause label
    target_container = $def.target.container
    severity         = $appliedSeverity
    params           = $step.body
}
($event | ConvertTo-Json -Compress -Depth 5) | Add-Content -Path $eventsFile -Encoding utf8
Write-Host "  logged -> $eventsFile" -ForegroundColor DarkGray

if ($def.type -eq "infra") {
    # Run the docker command. Its stdout is just the container name echoed back,
    # which adds nothing and breaks up the narrative during a live demo.
    $cmd = $step.command
    Write-Host "  > $cmd"
    Invoke-Expression $cmd 2>&1 | Out-Null
}
elseif ($def.type -eq "app") {
    # Call the admin endpoint
    $url = "http://localhost:$($def.target.port)$($step.endpoint)"
    if ($step.body) {
        $body = $step.body | ConvertTo-Json -Compress
        Write-Host "  > POST $url  $body"
        Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json" -Body $body | Out-Null
    } else {
        Write-Host "  > POST $url"
        Invoke-RestMethod -Uri $url -Method Post | Out-Null
    }
}