#!/usr/bin/env bash
# Export docs/presentation/index.html to docs/presentation/slides.{pdf,pptx}.
#
#   bash scripts/export_deck.sh
#
# Needs Node.js and python3. Tooling (puppeteer, Pillow, python-pptx) is installed into a
# throwaway temp dir, never into the project .venv. Uses CHROME_PATH (or system Google
# Chrome on macOS) when available, otherwise puppeteer's bundled Chromium.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DECK="$ROOT/docs/presentation/index.html"
OUT="$ROOT/docs/presentation"
WORK="$(mktemp -d -t deck-export.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

if [[ -z "${CHROME_PATH:-}" && -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  export CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi
if [[ -n "${CHROME_PATH:-}" ]]; then
  export PUPPETEER_SKIP_DOWNLOAD=1
fi

echo "==> installing export tooling in $WORK"
(cd "$WORK" && npm init -y >/dev/null && npm install --silent --no-audit --no-fund puppeteer@25)
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet "pillow>=12" "python-pptx>=1.0"

echo "==> screenshotting slides"
cp "$ROOT/scripts/deck/export_slides.mjs" "$WORK/"
(cd "$WORK" && node export_slides.mjs "$DECK" "$WORK/png")

echo "==> bundling"
"$WORK/venv/bin/python" "$ROOT/scripts/deck/bundle_slides.py" "$WORK/png" "$OUT"
