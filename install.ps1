# GermanTime installer — creates venv, installs pinned ML stack (RTX 5090 / cu128),
# builds the frontend, downloads voice/STT models, and runs smoke tests.
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1 [-SkipModels] [-SkipFrontend]
param(
    [switch]$SkipModels,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n==== $msg ====" -ForegroundColor Cyan }

Step "Python venv"
if (-not (Test-Path "$root\.venv")) {
    python -m venv "$root\.venv"
}
$py = "$root\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip wheel | Out-Null

Step "PyTorch cu128 (Blackwell/sm_120)"
& $py -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "torch install failed" }

Step "Python requirements"
& $py -m pip install -r "$root\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "requirements install failed" }

Step "Chatterbox TTS (--no-deps; its pins conflict with our torch)"
& $py -m pip install chatterbox-tts==0.1.7 --no-deps
& $py -m pip install s3tokenizer resemble-perth conformer diffusers safetensors librosa einops omegaconf pykakasi pyloudnorm spacy-pkuseg
if ($LASTEXITCODE -ne 0) { Write-Warning "Chatterbox deps failed - app will fall back to Piper-only voice." }

if (-not $SkipFrontend) {
    Step "Frontend (npm install + build)"
    Push-Location "$root\frontend"
    npm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm build failed" }
    Pop-Location
}

if (-not $SkipModels) {
    Step "Voice + STT model downloads (Piper voices, Whisper, wav2vec2, Chatterbox)"
    & $py "$root\scripts\download_models.py"
    if ($LASTEXITCODE -ne 0) { Write-Warning "Some model downloads failed - re-run scripts\download_models.py later." }
}

Step "Smoke tests"
& $py "$root\scripts\smoke_test.py"
if ($LASTEXITCODE -ne 0) { Write-Warning "Smoke test reported problems (see above)." }

Write-Host "`nInstall finished. Launch with:  powershell -ExecutionPolicy Bypass -File start.ps1" -ForegroundColor Green
