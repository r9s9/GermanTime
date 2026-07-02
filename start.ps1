# GermanTime launcher — starts LM Studio server, the backend, and opens the app window.
# Usage:  powershell -ExecutionPolicy Bypass -File start.ps1 [-NoWindow]
param(
    [switch]$NoWindow
)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$py = "$root\.venv\Scripts\python.exe"
$port = 8710

if (-not (Test-Path $py)) {
    Write-Host "venv missing - run install.ps1 first." -ForegroundColor Red
    exit 1
}

# 1) LM Studio server (idempotent) + preload tutor model if the app has chosen one
Write-Host "Starting LM Studio server..." -ForegroundColor Cyan
lms server start
$tutorFile = "$root\data\tutor_model.txt"
if (Test-Path $tutorFile) {
    $tutor = (Get-Content $tutorFile -TotalCount 1).Trim()
    if ($tutor) {
        Write-Host "Preloading tutor model: $tutor" -ForegroundColor Cyan
        lms load $tutor --context-length 8192 -y
    }
}

# 2) Backend
$env:PYTHONUTF8 = "1"
Write-Host "Starting GermanTime backend on port $port..." -ForegroundColor Cyan
$backend = Start-Process -FilePath $py -ArgumentList @(
    "-m", "uvicorn", "app.main:app", "--app-dir", "$root\backend",
    "--host", "127.0.0.1", "--port", "$port"
) -PassThru -WindowStyle Hidden

# 3) Wait for health, then open the app window
$deadline = (Get-Date).AddSeconds(60)
$up = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-RestMethod "http://localhost:$port/api/health" -TimeoutSec 2
        if ($r.ok) { $up = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
}

if (-not $up) {
    Write-Host "Backend did not come up within 60s. Check logs." -ForegroundColor Red
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
    exit 1
}

Write-Host "GermanTime laeuft auf http://localhost:$port" -ForegroundColor Green
if (-not $NoWindow) {
    Start-Process "msedge" -ArgumentList "--app=http://localhost:$port", "--window-size=1280,860"
}

Write-Host "Druecke Strg+C oder schliesse dieses Fenster, um den Server zu beenden."
try {
    Wait-Process -Id $backend.Id
} finally {
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
