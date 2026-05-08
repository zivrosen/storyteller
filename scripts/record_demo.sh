#!/usr/bin/env bash
# Record a short demo of the bedtime UI and convert it to a GIF.
#
# Pre-reqs: server running on :8000, OPENAI_API_KEY in .env, ffmpeg installed.
#   ./scripts/record_demo.sh
# Output: docs/demo.gif (and an intermediate docs/demo.webm)

set -euo pipefail
cd "$(dirname "$0")"

node record_demo.js

cd ..
WEBM=docs/demo.webm
GIF=docs/demo.gif

# Build a colour palette so the GIF doesn't dither into mush.
# 10 fps + 640 px wide keeps the file under ~2 MB while staying readable.
PALETTE=$(mktemp -t bedtime-palette).png
FILTER="fps=10,scale=640:-1:flags=lanczos"
ffmpeg -y -i "$WEBM" -vf "${FILTER},palettegen=stats_mode=diff" "$PALETTE" >/dev/null 2>&1
ffmpeg -y -i "$WEBM" -i "$PALETTE" \
  -lavfi "${FILTER}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5" \
  "$GIF" >/dev/null 2>&1

rm -f "$PALETTE"
echo "Wrote $GIF ($(du -h "$GIF" | cut -f1))"
