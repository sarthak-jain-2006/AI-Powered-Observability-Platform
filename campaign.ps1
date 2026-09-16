# campaign.ps1 - unattended fault campaign.
#
# Generates the fault half of the dataset: cycles every fault at every severity,
# repeated, under steady load, with a recovery gap between episodes. Each
# inject/recover is labelled by run-fault.ps1, so the output is ground truth
# without any manual bookkeeping.
#
# Intended to be started and left alone for hours.
#
# Usage:
#   .\campaign.ps1                                  # show the plan, ask to confirm
#   .\campaign.ps1 -Force                           # start immediately
#   .\campaign.ps1 -Repetitions 5 -Force
#   .\campaign.ps1 -Faults payment-failure,db-delay -Force
#   .\campaign.ps1 -WhatIf                          # print the plan and exit

param(
    [int]      $Repetitions     = 3,
    [int]      $FaultSeconds    = 180,
    [int]      $RecoverySeconds = 180,
    [int]      $Vus             = 6,
    [string[]] $Faults,
    [string[]] $Severities,
    [switch]   $NoShuffle,
    [switch]   $WhatIf,
    [switch]   $Force
)

$root    = $PSScriptRoot
$defDir  = Join-Path $root "faults/definitions"
$runner  = Join-Path $root "faults/run-fault.ps1"
$manifest = Join-Path $root "ai-engine/data/campaign_manifest.json"

function Step($msg)  { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Note($msg)  { Write-Host "    $msg" -ForegroundColor DarkGray }

# --- Build the episode list ------------------------------------------------
$defs = Get-ChildItem -Path $defDir -Recurse -Filter *.json | ForEach-Object {
    Get-Content $_.FullName -Raw | ConvertFrom-Json
}
if ($Faults) { $defs = $defs | Where-Object { $Faults -contains $_.name } }
if (-not $defs) { Write-Host "No matching faults." -ForegroundColor Red; exit 1 }

$episodes = @()
foreach ($d in $defs) {
    # Binary faults have no severities block; they contribute a single episode.
    $levels = if ($d.severities) {
        $d.severities.PSObject.Properties.Name
    } else {
        @("severe")
    }
    if ($Severities) { $levels = $levels | Where-Object { $Severities -contains $_ } }
    # A fault may declare its own hold time. memory-leak needs a much longer
    # episode than the rest: a three-minute leak barely moves a thirty-minute
    # slope, so the drift it exists to produce would never show up.
    $hold = if ($d.holdSeconds) { [int]$d.holdSeconds } else { $FaultSeconds }
    foreach ($lvl in $levels) {
        for ($r = 1; $r -le $Repetitions; $r++) {
            $episodes += [pscustomobject]@{
                Fault = $d.name; Severity = $lvl; Rep = $r; Hold = $hold
            }
        }
    }
}

# Shuffle by default. Running every repetition of a fault back to back lets slow
# effects (a leak that has not fully been reclaimed, a warm cache) line up with
# one particular fault and look like part of its signature.
if (-not $NoShuffle) { $episodes = $episodes | Sort-Object { Get-Random } }

$totalSecs   = ($episodes | Measure-Object -Property Hold -Sum).Sum +
               ($episodes.Count * $RecoverySeconds)
$totalHours  = [math]::Round($totalSecs / 3600, 1)

Step "Campaign plan"
Note "$($episodes.Count) episodes  =  ~$totalHours hours"
Note "hold      : ${FaultSeconds}s, except memory-leak at $(($episodes | Where-Object Fault -eq 'memory-leak' | Select-Object -First 1).Hold)s"
Note "faults    : $(($defs.name | Sort-Object) -join ', ')"
Note "severities: $((($episodes.Severity | Sort-Object -Unique)) -join ', ')"
Note "load      : $Vus VUs throughout"
Note "order     : $(if ($NoShuffle) { 'sequential' } else { 'shuffled' })"

if ($WhatIf) {
    Write-Host ""
    $episodes | Format-Table -AutoSize
    exit 0
}

if (-not $Force) {
    $answer = Read-Host "`nStart? (y/N)"
    if ($answer -ne "y") { Write-Host "Aborted."; exit 0 }
}

# --- Preflight -------------------------------------------------------------
Step "Checking the stack"
$running = (docker compose ps --status running --format "{{.Name}}") -split "`n" | Where-Object { $_ }
if ($running.Count -lt 10) {
    Write-Host "Only $($running.Count) containers running. Start the stack first." -ForegroundColor Red
    exit 1
}
Note "$($running.Count) containers running"

# Every app-type fault is injected over http://localhost:<port>. Docker Desktop's
# port proxy has been observed to quietly stop forwarding for long-running
# containers while the container itself stays perfectly healthy, which makes
# every one of those injections fail. Check before committing to a multi-hour
# run rather than discovering it an hour in.
$ports = $defs | Where-Object { $_.type -eq "app" } |
         ForEach-Object { $_.target.port } | Sort-Object -Unique
$unreachable = @()
foreach ($port in $ports) {
    try { $null = Invoke-RestMethod "http://localhost:$port/health" -TimeoutSec 5 }
    catch { $unreachable += $port }
}
if ($unreachable.Count -gt 0) {
    Write-Host "Unreachable from the host: $($unreachable -join ', ')" -ForegroundColor Red
    Write-Host "Restarting those containers usually re-establishes forwarding:" -ForegroundColor Yellow
    Write-Host "  docker compose restart product-service user-service cart-service payment-service order-service"
    exit 1
}
Note "all $($ports.Count) fault endpoints reachable"

@{
    started_at  = (Get-Date).ToUniversalTime().ToString("o")
    episodes    = $episodes
    fault_secs  = $FaultSeconds
    recover_secs= $RecoverySeconds
    vus         = $Vus
} | ConvertTo-Json -Depth 5 | Set-Content -Path $manifest -Encoding utf8
Note "manifest -> $manifest"

# --- Load ------------------------------------------------------------------
function Start-Load($seconds) {
    docker compose run -d --rm k6 run --vus $Vus --duration "${seconds}s" --quiet /scripts/checkout.js 2>&1 | Out-Null
    Start-Sleep -Seconds 3
    return (docker ps --filter "name=k6" --format "{{.Names}}" | Select-Object -First 1)
}

function Test-LoadAlive {
    $c = docker ps --filter "name=k6" --format "{{.Names}}" | Select-Object -First 1
    return [bool]$c
}

Step "Starting load for the full campaign"
$k6name = Start-Load ($totalSecs + 300)
Note "k6 container: $k6name"

# --- Run -------------------------------------------------------------------
function Invoke-Step($runner, $ep, $action) {
    # Run the fault runner without letting its errors terminate the campaign.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $runner -Fault $ep.Fault -Action $action -Severity $ep.Severity 2>&1 | Out-Null
        return $true
    } catch {
        Write-Host "    $action error: $($_.Exception.Message)" -ForegroundColor DarkYellow
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

$active = $null
$done = 0
$failed = @()
$campaignStart = Get-Date

try {
    foreach ($ep in $episodes) {
        $done++
        $elapsed = ((Get-Date) - $campaignStart).TotalSeconds
        $remaining = [math]::Round(((($episodes | Select-Object -Skip ($done - 1) |
                      Measure-Object -Property Hold -Sum).Sum) +
                      (($episodes.Count - $done + 1) * $RecoverySeconds)) / 60)

        Step "[$done/$($episodes.Count)] $($ep.Fault)/$($ep.Severity)  (rep $($ep.Rep))  ~${remaining}min left"

        # An overnight run outlives the occasional Docker hiccup; if the load
        # generator died, the rest of the campaign would silently record faults
        # against an idle system.
        if (-not (Test-LoadAlive)) {
            Note "load generator gone - restarting it"
            $k6name = Start-Load ([int]($totalSecs - $elapsed + 300))
        }

        # A single failed injection must not end the campaign. Previously an
        # unreachable endpoint threw, propagated out of the loop under
        # ErrorActionPreference=Stop, hit the finally block, and the run exited
        # reporting "finished" after two of sixteen episodes.
        $ok = Invoke-Step $runner $ep "inject"
        if (-not $ok) {
            $failed += $ep
            Note "injection failed - skipping this episode"
            Start-Sleep -Seconds 10
            continue
        }

        $active = $ep
        Start-Sleep -Seconds $ep.Hold

        if (-not (Invoke-Step $runner $ep "recover")) {
            # Recovery failing matters far more than injection failing: the
            # fault stays live and contaminates every later episode.
            Write-Host "    RECOVERY FAILED for $($ep.Fault) - retrying once" -ForegroundColor Red
            Start-Sleep -Seconds 5
            if (-not (Invoke-Step $runner $ep "recover")) {
                Write-Host "    recovery still failing - stopping the campaign" -ForegroundColor Red
                break
            }
        }
        $active = $null
        Start-Sleep -Seconds $RecoverySeconds
    }
}
finally {
    # Leaving a fault injected would poison every later collection, and an infra
    # fault leaves a container stopped, so recovery has to happen even on Ctrl+C.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($active) {
        Step "Interrupted mid-episode - recovering $($active.Fault)"
        try { & $runner -Fault $active.Fault -Action recover -Severity $active.Severity | Out-Null } catch {}
    }
    Step "Stopping load"
    try { docker compose rm -f -s k6 2>&1 | Out-Null } catch {}
    $ErrorActionPreference = $prevEap
}

$completed = $done - $failed.Count
Step "Campaign finished: $completed/$($episodes.Count) episodes completed"
if ($failed.Count -gt 0) {
    Note "$($failed.Count) episode(s) failed to inject:"
    $failed | ForEach-Object { Note "  $($_.Fault)/$($_.Severity)" }
}
Note "labels  -> ai-engine/data/fault_events.jsonl"
Note "next    -> docker exec ai-engine python train.py"
