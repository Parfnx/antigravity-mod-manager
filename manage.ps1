param(
    [ValidateSet('menu', 'status', 'apply', 'reapply', 'restore')]
    [string]$Action = 'menu',
    [string]$Mods = 'fast-switch,mcp-panel,context-panel,runtime-panel,sessions-panel',
    [switch]$Offline
)

$ErrorActionPreference = 'Stop'
$resDir = Join-Path $env:LOCALAPPDATA 'Programs\antigravity\resources'
$asar = Join-Path $resDir 'app.asar'
$staged = Join-Path $resDir 'app.asar.mod-manager.staged'
$backup = Join-Path $resDir 'app.asar.mod-manager.backup'
$exe = Join-Path $env:LOCALAPPDATA 'Programs\antigravity\Antigravity.exe'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here 'mod_manager.py'

function Commit-Staged {
    Write-Host 'Stopping Antigravity...'
    Get-Process Antigravity -ErrorAction SilentlyContinue | Stop-Process -Force
    Get-Process language_server -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 800

    if (-not (Test-Path $backup)) {
        Copy-Item -Path $asar -Destination $backup -Force
    }
    Move-Item -Path $staged -Destination $asar -Force
    Write-Host 'Updated app.asar successfully. Launching Antigravity...'
    Start-Process -FilePath $exe
}

if ($Action -eq 'menu') {
    python $py status
    Write-Host ''
    Write-Host '[1] Apply all (fast-switch + mcp-panel + context-panel + runtime-panel + sessions-panel)'
    Write-Host '[2] Re-apply saved modules (after Antigravity update)'
    Write-Host '[3] Custom module list'
    Write-Host '[4] Restore backup app.asar'
    $pick = Read-Host 'Select action (1-4)'
    switch ($pick) {
        '1' { $Action = 'apply' }
        '2' { $Action = 'reapply' }
        '3' {
            $Mods = Read-Host 'Comma-separated (fast-switch,mcp-panel,context-panel,runtime-panel,sessions-panel)'
            $Action = 'apply'
        }
        '4' { $Action = 'restore' }
        default { throw "Cancelled." }
    }
}

if ($Action -eq 'status') {
    python $py status
    exit 0
}

if ($Action -eq 'restore') {
    if (-not (Test-Path $backup)) { throw "Backup not found: $backup" }
    Get-Process Antigravity -ErrorAction SilentlyContinue | Stop-Process -Force
    Get-Process language_server -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 800
    Copy-Item -Path $backup -Destination $asar -Force
    Write-Host 'Restored backup app.asar. Launching Antigravity...'
    Start-Process -FilePath $exe
    exit 0
}

$extra = @()
if ($Offline) { $extra += '--offline' }
if ($Action -eq 'apply') {
    python $py apply --mods $Mods --stage @extra
} elseif ($Action -eq 'reapply') {
    python $py reapply --stage @extra
}
if (-not $?) { exit 1 }
Commit-Staged
