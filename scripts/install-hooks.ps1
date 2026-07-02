<#
.SYNOPSIS
    Install TokenConsumption statusLine + Stop/SessionEnd hooks into ~/.claude/settings.json.

.DESCRIPTION
    Safe by default: runs in PREVIEW mode and only shows the planned changes.
    Pass -Apply to actually write (a timestamped backup is made first).

.EXAMPLE
    powershell -File scripts\install-hooks.ps1            # preview only
    powershell -File scripts\install-hooks.ps1 -Apply     # back up + write
#>
param(
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

# Resolve paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $ScriptDir
$Launcher  = Join-Path $Root "scripts\tc-launcher.py"
$OnStop    = Join-Path $Root "src\token_consumption\hooks\on_stop.py"
$OnEnd     = Join-Path $Root "src\token_consumption\hooks\on_session_end.py"
$Settings  = Join-Path $env:USERPROFILE ".claude\settings.json"

function Cmd([string]$target, [string]$extra) {
    # Build a python command string with quoted path
    if ($extra) { return "python `"$target`" $extra" }
    return "python `"$target`""
}

# Load existing settings (or empty object)
if (Test-Path $Settings) {
    $json = Get-Content $Settings -Raw
    $obj  = $json | ConvertFrom-Json
} else {
    $obj = [PSCustomObject]@{}
}

# Convert to hashtable for easy mutation
$settingsHash = @{}
foreach ($p in $obj.PSObject.Properties) { $settingsHash[$p.Name] = $p.Value }

# --- statusLine ---
$settingsHash["statusLine"] = @{
    type    = "command"
    command = (Cmd $Launcher "status --line")
}

# --- hooks ---
$hooks = @{}
if ($settingsHash.ContainsKey("hooks")) {
    foreach ($p in $settingsHash["hooks"].PSObject.Properties) { $hooks[$p.Name] = $p.Value }
}
$hooks["Stop"]       = @( @{ hooks = @( @{ type = "command"; command = (Cmd $OnStop) } ) } )
$hooks["SessionEnd"] = @( @{ hooks = @( @{ type = "command"; command = (Cmd $OnEnd) } ) } )
$settingsHash["hooks"] = $hooks

$newJson = $settingsHash | ConvertTo-Json -Depth 10

Write-Host "=== Planned ~/.claude/settings.json ===" -ForegroundColor Cyan
Write-Host $newJson
Write-Host "=======================================" -ForegroundColor Cyan

if (-not $Apply) {
    Write-Host ""
    Write-Host "PREVIEW ONLY. No changes written." -ForegroundColor Yellow
    Write-Host "Re-run with -Apply to back up and write:" -ForegroundColor Yellow
    Write-Host "    powershell -File scripts\install-hooks.ps1 -Apply"
    exit 0
}

# Backup then write
if (Test-Path $Settings) {
    $stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$Settings.bak.$stamp"
    Copy-Item $Settings $backup
    Write-Host "Backup created: $backup" -ForegroundColor Green
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $Settings) | Out-Null
}

# Write UTF-8 WITHOUT BOM (PowerShell 5.1 -Encoding utf8 adds a BOM that breaks strict JSON parsers).
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($Settings, $newJson, $utf8NoBom)
Write-Host "Wrote $Settings" -ForegroundColor Green
Write-Host "Restart Claude Code for the statusLine and hooks to take effect." -ForegroundColor Green
