#!/bin/sh
# Render alertmanager.yml from the template and exec Alertmanager.
# Runs in the busybox-based prom/alertmanager image (POSIX sh + sed only).
# The bot token is written to a tmpfs file instead of the rendered config so
# it never appears in /api/v2/status or the container filesystem layers.
set -eu

TEMPLATE=/etc/alertmanager/alertmanager.yml.tmpl
OUT_DIR=/tmp/alertmanager
OUT="${OUT_DIR}/alertmanager.yml"

mkdir -p "${OUT_DIR}"
umask 077

TOKEN="${TELEGRAM_BOT_TOKEN:-}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"

if [ -n "${TOKEN}" ] && [ -n "${CHAT_ID}" ]; then
  case "${CHAT_ID}" in
    *[!0-9-]*) echo "render_config: TELEGRAM_CHAT_ID must be numeric" >&2; exit 1 ;;
  esac
  printf '%s' "${TOKEN}" > "${OUT_DIR}/telegram_bot_token"
  sed -e '/# BEGIN_TELEGRAM/d' -e '/# END_TELEGRAM/d' \
      -e "s/__TELEGRAM_CHAT_ID__/${CHAT_ID}/" "${TEMPLATE}" > "${OUT}"
  echo "render_config: Telegram receiver enabled (+ webhook fallback)"
else
  sed -e '/# BEGIN_TELEGRAM/,/# END_TELEGRAM/d' "${TEMPLATE}" > "${OUT}"
  echo "render_config: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set, webhook receiver only"
fi

exec /bin/alertmanager \
  --config.file="${OUT}" \
  --storage.path=/alertmanager \
  --web.listen-address=:9093 \
  --web.external-url="${ALERTMANAGER_EXTERNAL_URL:-http://localhost:9093}" \
  "$@"
