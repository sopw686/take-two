# Run Take Two: creates the Python env with uv, builds the frontend once, starts the server.
#
#   .\run.ps1                    start on http://127.0.0.1:8765
#   .\run.ps1 -Rebuild           force a frontend rebuild (it also rebuilds by itself when sources are newer than the build)
#   .\run.ps1 -Cpu               force CPU speech-to-text (the CUDA libraries stay installed)
#   .\run.ps1 -SttModel base.en  pick the local speech-to-text model (sets TAKE_TWO_STT_MODEL)
#   .\run.ps1 -TakesDir <path>   save takes there (sets TAKE_TWO_TAKES_DIR), e.g. outside a OneDrive folder
#
# Optional env vars: ANTHROPIC_API_KEY (Suggest marks, LLM define checks),
# OPENAI_API_KEY + TAKE_TWO_STT=openai (cloud transcription; installs the "cloud" extra), TAKE_TWO_STT_MODEL (base.en | small.en | ...).
# GEMINI_API_KEY (optional cloud voices for Hear it). The local natural voice downloads once (~190 MB) on first start.

param([switch]$Rebuild, [switch]$Cpu, [int]$Port = 8765, [string]$SttModel, [string]$TakesDir)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

# $ErrorActionPreference does not stop on a native command's exit code in Windows PowerShell 5.1.
function Stop-OnFailure([string]$what) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$what failed (exit code $LASTEXITCODE); not starting." -ForegroundColor Red
        exit 1
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv is required: https://docs.astral.sh/uv/  (winget install astral-sh.uv)" -ForegroundColor Yellow
    exit 1
}

# Checked first: a server already running holds files in .venv, so uv sync would fail with a less useful message.
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) {
    $owner = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Write-Host "Port $Port is already in use by $owner (PID $($busy.OwningProcess)); is Take Two already running?" -ForegroundColor Yellow
    Write-Host "Stop that process, or start on another port: .\run.ps1 -Port 8766" -ForegroundColor Yellow
    exit 1
}

# uv sync is exact: an extra left out is uninstalled. So -Cpu keeps the gpu extra and only picks the device.
$extras = @()
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $extras += "--extra", "gpu" }
if ($env:TAKE_TWO_STT -eq "openai") { $extras += "--extra", "cloud" }
uv sync @extras
Stop-OnFailure "uv sync"
if ($Cpu) { $env:TAKE_TWO_STT_DEVICE = "cpu" }
if ($SttModel) { $env:TAKE_TWO_STT_MODEL = $SttModel }
if ($TakesDir) { $env:TAKE_TWO_TAKES_DIR = $TakesDir }

$dist = Join-Path $root "frontend\dist\index.html"
# Rebuild when any frontend source is newer than the last build, so a pulled or edited UI is never served stale.
$stale = $false
if (Test-Path $dist) {
    $built = (Get-Item $dist).LastWriteTimeUtc
    $config = @("index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json") |
        ForEach-Object { Join-Path $root "frontend\$_" } | Where-Object { Test-Path $_ } | ForEach-Object { Get-Item $_ }
    $sources = @(Get-ChildItem (Join-Path $root "frontend\src") -Recurse -File) + @($config)
    $stale = [bool]($sources | Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1)
    if ($stale) { Write-Host "Frontend sources changed since the last build; rebuilding." }
}
if ($Rebuild -or $stale -or -not (Test-Path $dist)) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host "npm not found; the API will run without the UI." -ForegroundColor Yellow
    } else {
        Push-Location (Join-Path $root "frontend")
        if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
        if ($LASTEXITCODE -eq 0) { npm run build }
        Pop-Location
        Stop-OnFailure "The frontend build"
    }
}

Write-Host "Take Two -> http://127.0.0.1:$Port" -ForegroundColor Green
uv run uvicorn take_two.app:app --host 127.0.0.1 --port $Port
