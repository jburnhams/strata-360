# Build the strata360 environment from scratch on Windows (Python 3.13, NVIDIA GPU, winget ffmpeg + exiftool).
#   scripts\setup_env.ps1 [-FetchModels] [-NoDfn] [-Cuda cu128]
# Prerequisites: winget install Python.Python.3.13 Gyan.FFmpeg OliverBetz.ExifTool OpenJS.NodeJS
# -Cuda is the PyTorch wheel index suffix (cu128 or newer is needed for RTX 50-series / Blackwell); -Cuda cpu installs the CPU build.
param([switch]$FetchModels, [switch]$NoDfn, [string]$Cuda = 'cu128')
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot; $Venv = Join-Path $Root '.venv'; $Py = Join-Path $Venv 'Scripts\python.exe'
function Say($m) { Write-Host "`n==> $m" }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw 'ffmpeg not found: winget install Gyan.FFmpeg OliverBetz.ExifTool' }
Say "virtual environment: $Venv"
py -3.13 -m venv $Venv
& $Py -m pip install --upgrade pip | Out-Null
Say "torch ($Cuda)"
& $Py -m pip install torch==2.9.1 torchaudio==2.9.1 --index-url "https://download.pytorch.org/whl/$Cuda"
Say 'requirements'
& $Py -m pip install numpy==2.2.6 -r (Join-Path $Root 'requirements.txt')
Say 'detector, speaker and face models (people, face_view, objects, speakers)'
& $Py -m pip install -r (Join-Path $Root 'requirements-vision.txt')
& $Py -m pip install --force-reinstall --no-deps torchvision==0.24.1 --index-url "https://download.pytorch.org/whl/$Cuda"       # ultralytics pulls the CPU torchvision, which has no CUDA nms
& $Py -m pip install --force-reinstall opencv-python==4.12.0.88                                                                 # and a headless OpenCV 5 over the pinned one
Say 'CUDA libraries for faster-whisper (ctranslate2 needs cuBLAS 12 and cuDNN 9)'
& $Py -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*
if (-not $NoDfn) {
  Say 'DeepFilterNet (optional enhancer)'
  & $Py -m pip install --no-deps deepfilternet==0.5.6 deepfilterlib==0.5.6
  if ($LASTEXITCODE) { Write-Host 'DeepFilterNet install failed (needs a Rust toolchain); continuing without it' } else { & $Py (Join-Path $Root 'scripts\patch_deepfilternet.py') $Py }
}
$env:PYTHONPATH = Join-Path $Root 'src'
if ($FetchModels) { Say 'models'; & $Py -m strata360 fetch-models }
Say 'checking'
& $Py -m strata360 doctor
if (Get-Command npm -ErrorAction SilentlyContinue) { Push-Location (Join-Path $Root 'web'); npm install --silent; npm run build; Pop-Location; Write-Host 'web app built' }
else { Write-Host 'npm not found: winget install OpenJS.NodeJS, then cd web; npm install; npm run build' }
