# Run Marked: creates the Python env with uv, builds the frontend once, starts the server.
#
#   .\run.ps1            start on http://127.0.0.1:8765
#   .\run.ps1 -Rebuild   force a frontend rebuild (it also rebuilds by itself when sources are newer than the build)
#   .\run.ps1 -Cpu       force CPU speech-to-text
#
# Optional env vars: ANTHROPIC_API_KEY (Suggest marks, LLM define checks),
# OPENAI_API_KEY + MARKED_STT=openai (cloud transcription), MARKED_STT_MODEL (base.en | small.en | ...).

param([switch]$Rebuild, [switch]$Cpu, [int]$Port = 8765)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv is required: https://docs.astral.sh/uv/  (winget install astral-sh.uv)" -ForegroundColor Yellow
    exit 1
}

$hasNvidia = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($hasNvidia -and -not $Cpu) { uv sync --extra gpu } else { uv sync }
if ($Cpu) { $env:MARKED_STT_DEVICE = "cpu" }

$dist = Join-Path $root "frontend\dist\index.html"
# Rebuild when any frontend source is newer than the last build, so a pulled or edited UI is never served stale.
$stale = $false
if (Test-Path $dist) {
    $built = (Get-Item $dist).LastWriteTimeUtc
    $sources = @(Get-ChildItem (Join-Path $root "frontend\src") -Recurse -File) +
        @(Get-Item (Join-Path $root "frontend\index.html"), (Join-Path $root "frontend\package.json"))
    $stale = [bool]($sources | Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1)
    if ($stale) { Write-Host "Frontend sources changed since the last build; rebuilding." }
}
if ($Rebuild -or $stale -or -not (Test-Path $dist)) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host "npm not found; the API will run without the UI." -ForegroundColor Yellow
    } else {
        Push-Location (Join-Path $root "frontend")
        if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
        npm run build
        Pop-Location
    }
}

Write-Host "Marked -> http://127.0.0.1:$Port" -ForegroundColor Green
uv run uvicorn marked.app:app --host 127.0.0.1 --port $Port
