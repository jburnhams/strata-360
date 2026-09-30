#!/bin/bash
# Build the strata360 environment from scratch (macOS Apple Silicon, Python 3.13, Homebrew ffmpeg + exiftool).
#   scripts/setup_env.sh [--with-cv] [--no-dfn] [--fetch-models]
# Environment variables: VENV (default .venv), PYTHON (default python3), CV_VENV (default .venv-cv)
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
