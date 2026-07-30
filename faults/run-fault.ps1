# Fault runner — reads a fault definition JSON and executes inject or recover.
# Usage:
#   .\faults\run-fault.ps1 -Fault db-down -Action inject
#   .\faults\run-fault.ps1 -Fault db-down -Action recover
#   .\faults\run-fault.ps1 -List

param(
    [string]$Fault,
    [ValidateSet("inject","recover")][string]$Action = "inject",
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

Write-Host "[$Action] $($def.name) ($($def.category))" -ForegroundColor Yellow

if ($def.type -eq "infra") {
    # Run the docker command
    $cmd = $step.command
    Write-Host "  > $cmd"
    Invoke-Expression $cmd
}
elseif ($def.type -eq "app") {
    # Call the admin endpoint
    $url = "http://localhost:$($def.target.port)$($step.endpoint)"
    if ($step.body) {
        $body = $step.body | ConvertTo-Json
        Write-Host "  > POST $url  $body"
        Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json" -Body $body
    } else {
        Write-Host "  > POST $url"
        Invoke-RestMethod -Uri $url -Method Post
    }
}