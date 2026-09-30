#!/bin/bash
# Put the GPX map/dashboard overlay on one rendered segment (README Phase 8).
#   scripts/overlay/overlay_segment.sh SEGMENT.mp4 RACE.gpx OUT.mp4 [extra gopro-dashboard.py args]
# Needs: ../gopro-dashboard-overlay on branch mp4-exact-start (or support-mp4-creation-datetime), .venv-overlay, and cairo (brew install cairo pkg-config).
# The segment must carry its true UTC start (render with --start-utc): creation_time, or the exact comment tag on the mp4-exact-start branch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; GDO="${GDO:-$ROOT/../gopro-dashboard-overlay}"
SEG="$1"; GPX="$2"; OUT="$3"; shift 3
CFG="$ROOT/scripts/overlay"
PYTHONPATH="$GDO" PYTHONWARNINGS=ignore "$ROOT/.venv-overlay/bin/python" "$GDO/bin/gopro-dashboard.py" \
  --font "${FONT:-/System/Library/Fonts/Supplemental/Arial.ttf}" --profile hevc10 --config-dir "$CFG" --cache-dir "$ROOT/.cache/gdo" \
  --use-gpx-only --gpx "$GPX" --video-time-start mp4-created "$@" "$SEG" "$OUT"
