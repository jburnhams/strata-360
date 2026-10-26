#!/bin/bash
# Build the strata360 environment from scratch (macOS Apple Silicon, Python 3.13, Homebrew ffmpeg + exiftool).
#   scripts/setup_env.sh [--with-cv] [--no-dfn] [--fetch-models]
# Environment variables: VENV (default .venv), PYTHON (default python3), CV_VENV (default .venv-cv), SKIP_ROCM=1 (keep PyPI's torch on an AMD machine)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv}"; PYTHON="${PYTHON:-python3}"; CV_VENV="${CV_VENV:-$ROOT/.venv-cv}"
WITH_CV=0; DFN=1; MODELS=0
for a in "$@"; do case "$a" in --with-cv) WITH_CV=1;; --no-dfn) DFN=0;; --fetch-models) MODELS=1;; *) echo "unknown option $a"; exit 2;; esac; done
say() { printf '\n==> %s\n' "$*"; }
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || { echo "ffmpeg/ffprobe not found: brew install ffmpeg exiftool"; exit 1; }
"$PYTHON" -c 'import sys; assert sys.version_info[:2] >= (3, 11), "Python 3.11+ required (tested on 3.13)"'
say "virtual environment: $VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip >/dev/null
say "requirements"
"$VENV/bin/pip" install -r "$ROOT/requirements.txt"
say "numpy (OpenBLAS build on macOS arm64; see requirements.txt for why)"
NUMPY_VERSION=2.2.6
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  TMP="$(mktemp -d)"
  "$VENV/bin/pip" download --no-deps --only-binary=:all: --platform macosx_11_0_arm64 --python-version 313 --implementation cp "numpy==$NUMPY_VERSION" -d "$TMP"
  "$VENV/bin/pip" install --force-reinstall --no-deps "$TMP"/numpy-*.whl
else
  "$VENV/bin/pip" install "numpy==$NUMPY_VERSION"
fi
# AMD GPU on Linux (no NVIDIA card): PyPI's torch is the CUDA build (with GBs of nvidia-* packages); swap it for the ROCm 6.4 build of the same version (requirements.txt pins torch and torchaudio 2.9.1; the wheel bundles ROCm, about 15 GB installed).
# The chip is read from /sys/class/kfd (gfx_target_version, 100300 = gfx1030 = RDNA2 and newer); the HSA_OVERRIDE_GFX_VERSION a Radeon 780M needs is set by strata360/__init__.py. SKIP_ROCM=1 keeps the PyPI build.
amd_gfx() { for f in /sys/class/kfd/kfd/topology/nodes/*/properties; do [ -r "$f" ] && awk '$1=="vendor_id"{v=$2} $1=="gfx_target_version"{g=$2} END{ if (v==4098) print g+0 }' "$f"; done 2>/dev/null | sort -n | tail -1 | grep . || echo 0; }
if [ "$(uname -s)" = "Linux" ] && ! command -v nvidia-smi >/dev/null 2>&1 && [ "${SKIP_ROCM:-0}" != 1 ] && [ "$(amd_gfx)" -ge 100300 ]; then
  say "AMD GPU (gfx_target_version $(amd_gfx)): torch with ROCm 6.4 instead of the CUDA build"
  TORCH_VERSION=$(sed -n 's/^torch==\([0-9.]*\).*/\1/p' "$ROOT/requirements.txt" | head -1)
  "$VENV/bin/pip" uninstall -y triton $("$VENV/bin/pip" list --format=freeze | sed -n 's/^\(nvidia-[^=]*\)==.*/\1/p') >/dev/null 2>&1 || true
  "$VENV/bin/pip" install --force-reinstall --index-url https://download.pytorch.org/whl/rocm6.4 "torch==$TORCH_VERSION" "torchaudio==$TORCH_VERSION" torchvision --extra-index-url https://pypi.org/simple   # torchvision too: the PyPI one is built for the CUDA torch ("operator torchvision::nms does not exist"); the resolver picks the one that matches torch
  PYTHONPATH="$ROOT/src" "$VENV/bin/python" -c "import strata360, torch; assert torch.cuda.is_available(), 'torch (ROCm) does not see the GPU'; x = torch.ones(256, 256, device='cuda'); print('ROCm torch OK on', torch.cuda.get_device_name(0), float((x @ x).sum()))"
fi
if [ "$DFN" = 1 ]; then
  say "DeepFilterNet (optional enhancer)"
  "$VENV/bin/pip" install --no-deps deepfilternet==0.5.6 deepfilterlib==0.5.6 || echo "DeepFilterNet install failed (needs a Rust toolchain: brew install rust); continuing without it"
  "$VENV/bin/python" "$ROOT/scripts/patch_deepfilternet.py" "$VENV/bin/python" || true
fi
if [ "$WITH_CV" = 1 ]; then
  say "MossFormer2 environment: $CV_VENV"
  "$PYTHON" -m venv "$CV_VENV"; "$CV_VENV/bin/pip" install -r "$ROOT/requirements-cv.txt"
fi
if [ "$MODELS" = 1 ]; then say "models"; STRATA_PYTHON="$VENV/bin/python" "$ROOT/strata360" fetch-models; fi
say "checking"
STRATA_PYTHON="$VENV/bin/python" "$ROOT/strata360" doctor

# ---- web app (React + Tailwind, built into src/strata360/server/static) -------------------------------------------------------------
if command -v npm >/dev/null 2>&1; then
  ( cd "$(dirname "$0")/../web" && npm install --silent && npm run build ) && echo "web app built"
else
  echo "npm not found: install Node.js to build the web app (cd web && npm install && npm run build)"
fi
