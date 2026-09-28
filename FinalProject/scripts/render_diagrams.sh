#!/usr/bin/env bash
# Render docs/assets/diagrams/src/*.mmd to SVG + PNG next to the sources' parent dir.
#
#   bash scripts/render_diagrams.sh            # all diagrams
#   bash scripts/render_diagrams.sh 05-data-flow
#
# Needs Node.js. Uses $MMDC when set (e.g. a locally installed mmdc binary),
# otherwise `npx -y @mermaid-js/mermaid-cli`. Puppeteer's bundled Chromium is used
# unless CHROME_PATH (or a system Google Chrome on macOS) is available.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIAGRAMS="$ROOT/docs/assets/diagrams"
SRC="$DIAGRAMS/src"
CONFIG="$DIAGRAMS/mermaid.config.json"
read -r -a MMDC_CMD <<< "${MMDC:-npx -y @mermaid-js/mermaid-cli@12}"

CHROME_PATH="${CHROME_PATH:-}"
if [[ -z "$CHROME_PATH" && -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi
PUPPETEER_CFG="$(mktemp -t mmdc-puppeteer.XXXXXX)"
trap 'rm -f "$PUPPETEER_CFG"' EXIT
if [[ -n "$CHROME_PATH" ]]; then
  printf '{"executablePath":"%s","args":["--no-sandbox"]}\n' "$CHROME_PATH" > "$PUPPETEER_CFG"
else
  printf '{"args":["--no-sandbox"]}\n' > "$PUPPETEER_CFG"
fi

shopt -s nullglob
if [[ $# -gt 0 ]]; then
  sources=()
  for name in "$@"; do sources+=("$SRC/${name%.mmd}.mmd"); done
else
  sources=("$SRC"/*.mmd)
fi
[[ ${#sources[@]} -gt 0 ]] || { echo "no .mmd sources in $SRC" >&2; exit 1; }

for source in "${sources[@]}"; do
  [[ -f "$source" ]] || { echo "missing $source" >&2; exit 1; }
  name="$(basename "$source" .mmd)"
  echo "rendering $name"
  "${MMDC_CMD[@]}" -q -c "$CONFIG" -p "$PUPPETEER_CFG" -b white -i "$source" -o "$DIAGRAMS/$name.svg"
  "${MMDC_CMD[@]}" -q -c "$CONFIG" -p "$PUPPETEER_CFG" -b white -s 2 -i "$source" -o "$DIAGRAMS/$name.png"
done
echo "done: ${#sources[@]} diagram(s) in $DIAGRAMS"
