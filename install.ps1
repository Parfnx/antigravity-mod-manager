$ErrorActionPreference = 'Stop'

function Assert-Tool($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Required tool '$name' was not found in PATH. $hint"
    }
}

Assert-Tool 'python' 'Install Python 3 from python.org or Microsoft Store.'
Assert-Tool 'node' 'Install Node.js LTS from nodejs.org.'

$installDir = Join-Path $env:USERPROFILE '.gemini\antigravity\mod-manager'
$zipUrl = 'https://github.com/Parfnx/antigravity-mod-manager/archive/refs/heads/main.zip'
$tmpZip = Join-Path $env:TEMP "agy-mod-manager-$([guid]::NewGuid().ToString('N')).zip"
$tmpExtract = Join-Path $env:TEMP "agy-mod-manager-$([guid]::NewGuid().ToString('N'))"

try {
    Write-Host 'Downloading Antigravity Mod Manager...'
    Invoke-WebRequest -Uri $zipUrl -OutFile $tmpZip -UseBasicParsing
    Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract -Force

    $inner = Get-ChildItem -Path $tmpExtract -Directory | Select-Object -First 1
    if (-not $inner) { throw 'Downloaded archive was empty.' }

    if (Test-Path $installDir) {
        Remove-Item -Path $installDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $installDir) -Force | Out-Null
    Move-Item -Path $inner.FullName -Destination $installDir -Force
} finally {
    Remove-Item -Path $tmpZip -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $tmpExtract -Recurse -Force -ErrorAction SilentlyContinue
}

$action = if ($env:AGY_ACTION) { $env:AGY_ACTION } else { 'apply' }
$mods = if ($env:AGY_MODS) { $env:AGY_MODS } else { 'fast-switch,mcp-panel,context-panel' }

$manageScript = Join-Path $installDir 'manage.ps1'
Write-Host "Running $manageScript ($action)..."
if ($action -eq 'apply') {
    & powershell -ExecutionPolicy Bypass -File $manageScript -Action apply -Mods $mods
} else {
    & powershell -ExecutionPolicy Bypass -File $manageScript -Action $action
}
