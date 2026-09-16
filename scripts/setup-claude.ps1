<#
.SYNOPSIS
    Configure your user-level Claude Code settings so Claude-generated commits and
    PRs carry no Claude co-author / attribution lines.

.DESCRIPTION
    Merges  { "attribution": { "commit": "", "pr": "" } }  into ~/.claude/settings.json.
    - Creates the file if it does not exist.
    - Preserves every other setting untouched.
    - Removes the deprecated "includeCoAuthoredBy" flag if present (superseded by "attribution").
    - Makes a timestamped backup before modifying an existing file.
    - Writes UTF-8 without BOM and validates the result.
    - Idempotent: if nothing needs to change, the file is not rewritten.

    This edits YOUR settings only; ~/.claude/settings.json is not part of the repository.

.EXAMPLE
    .\scripts\setup-claude.ps1            # apply (backs up first)
    .\scripts\setup-claude.ps1 -DryRun    # show what would change, write nothing
#>
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$Settings = Join-Path $env:USERPROFILE ".claude\settings.json"
$Changes  = @()

# --- Load existing settings (or start from an empty object) ---------------------------
if (Test-Path $Settings) {
    $raw = Get-Content $Settings -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        $obj = [PSCustomObject]@{}
    } else {
        try { $obj = $raw | ConvertFrom-Json }
        catch { throw "Existing $Settings is not valid JSON. Fix it manually first; nothing was changed." }
    }
    $exists = $true
} else {
    $obj    = [PSCustomObject]@{}
    $exists = $false
    $Changes += "create $Settings"
}

# --- Merge attribution (keep any other attribution keys, e.g. sessionUrl) --------------
$attr = $obj.PSObject.Properties["attribution"]
if (-not $attr -or -not ($attr.Value -is [PSCustomObject])) {
    $obj | Add-Member -NotePropertyName "attribution" -NotePropertyValue ([PSCustomObject]@{}) -Force
    $attr = $obj.PSObject.Properties["attribution"]
    $Changes += "add attribution {}"
}
foreach ($key in @("commit", "pr")) {
    $p = $attr.Value.PSObject.Properties[$key]
    if (-not $p) {
        $attr.Value | Add-Member -NotePropertyName $key -NotePropertyValue ""
        $Changes += "set attribution.$key = `"`""
    } elseif ($p.Value -ne "") {
        $Changes += "set attribution.$key = `"`" (was: $($p.Value | ConvertTo-Json -Compress))"
        $p.Value = ""
    }
}

# --- Remove deprecated includeCoAuthoredBy (fully superseded by attribution above) -----
$legacy = $obj.PSObject.Properties["includeCoAuthoredBy"]
if ($legacy) {
    Write-Host "Found deprecated 'includeCoAuthoredBy' = $($legacy.Value | ConvertTo-Json -Compress); attribution.commit/pr = `"`" replaces it." -ForegroundColor Yellow
    $obj.PSObject.Properties.Remove("includeCoAuthoredBy")
    $Changes += "remove includeCoAuthoredBy"
}

# --- Nothing to do? -------------------------------------------------------------------
if ($Changes.Count -eq 0) {
    Write-Host "Already configured: $Settings has attribution.commit = `"`" and attribution.pr = `"`". No changes." -ForegroundColor Green
    exit 0
}

Write-Host "Planned changes to ${Settings}:" -ForegroundColor Cyan
$Changes | ForEach-Object { Write-Host "  - $_" }

if ($DryRun) {
    Write-Host "DRY RUN. Nothing written. Re-run without -DryRun to apply." -ForegroundColor Yellow
    exit 0
}

# --- Backup, write (UTF-8 without BOM), validate ---------------------------------------
$newJson = ($obj | ConvertTo-Json -Depth 100) + "`n"

if ($exists) {
    $backup = "$Settings.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $Settings $backup
    Write-Host "Backup created: $backup" -ForegroundColor Green
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $Settings) | Out-Null
}

[System.IO.File]::WriteAllText($Settings, $newJson, (New-Object System.Text.UTF8Encoding($false)))

$check = (Get-Content $Settings -Raw -Encoding UTF8) | ConvertFrom-Json
if ($check.attribution.commit -ne "" -or $check.attribution.pr -ne "") {
    throw "Validation failed: attribution not as expected after write. Restore from backup: $backup"
}
Write-Host "Wrote $Settings (valid JSON, UTF-8 no BOM). Claude Code picks this up automatically." -ForegroundColor Green
