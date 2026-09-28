#!/usr/bin/env bash
# One-time host bootstrap for Ubuntu 22.04 / 24.04 (run as root from an unpacked release):
#
#   sudo API_DOMAIN=api.example.com GRAFANA_DOMAIN=grafana.example.com bash deploy/ubuntu/install.sh
#
# Idempotent. Installs Docker Engine + compose plugin (download.docker.com, not the Ubuntu
# docker.io package), nginx, certbot, ufw, curl, python3; creates the deploy user and the
# DEPLOY_ROOT layout; configures UFW (22/80/443 only); installs the nginx vhost and the
# systemd units (stack + daily backup). Secrets are NOT created here: copy .env.example to
# $DEPLOY_ROOT/shared/.env and edit it (docs/guides/ubuntu-deployment.md).
#
# Environment:
#   DEPLOY_USER      deploy
#   DEPLOY_ROOT      /opt/credit-risk
#   BACKUP_DIR       /var/backups/credit-risk
#   API_DOMAIN       api.credit-risk.local       (nginx server_name of the scoring API)
#   GRAFANA_DOMAIN   grafana.credit-risk.local   (nginx server_name of Grafana)
#   SSH_PORT         22
#   SKIP_UFW         set to 1 to leave the firewall untouched (e.g. inside a container)
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/credit-risk}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/credit-risk}"
API_DOMAIN="${API_DOMAIN:-api.credit-risk.local}"
GRAFANA_DOMAIN="${GRAFANA_DOMAIN:-grafana.credit-risk.local}"
SSH_PORT="${SSH_PORT:-22}"
SKIP_UFW="${SKIP_UFW:-0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '[install] %s\n' "$*"; }
die() { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "run as root (sudo)"
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "Ubuntu required, found ${ID:-unknown}"
case "${VERSION_ID:-}" in
  22.04 | 24.04) ;;
  *) log "warning: tested on Ubuntu 22.04/24.04, found ${VERSION_ID:-unknown}" ;;
esac
[[ "$API_DOMAIN" =~ ^[A-Za-z0-9.-]+$ && "$GRAFANA_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "invalid domain name"

install_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg python3 nginx certbot python3-certbot-nginx ufw >/dev/null
  if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    log "installing Docker Engine from download.docker.com"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  fi
  systemctl enable --now docker >/dev/null 2>&1 || log "warning: could not enable docker.service (no systemd?)"
  log "$(docker --version); $(docker compose version)"
}

create_user_and_layout() {
  if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
    log "creating user $DEPLOY_USER"
    adduser --disabled-password --gecos "" "$DEPLOY_USER" >/dev/null
  fi
  usermod -aG docker "$DEPLOY_USER"
  install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0755 "$DEPLOY_ROOT" "$DEPLOY_ROOT/releases"
  install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$DEPLOY_ROOT/shared" "$BACKUP_DIR"
}

configure_firewall() {
  if [[ "$SKIP_UFW" == "1" ]]; then
    log "SKIP_UFW=1: firewall left unchanged"
    return
  fi
  ufw default deny incoming >/dev/null
  ufw default allow outgoing >/dev/null
  ufw allow "$SSH_PORT/tcp" comment "ssh" >/dev/null
  ufw allow 80/tcp comment "http (ACME + redirect)" >/dev/null
  ufw allow 443/tcp comment "https" >/dev/null
  ufw --force enable >/dev/null
  log "ufw: $(ufw status | head -n 1)"
}

install_nginx() {
  local site=/etc/nginx/sites-available/credit-risk.conf
  sed -e "s/__API_DOMAIN__/$API_DOMAIN/g" -e "s/__GRAFANA_DOMAIN__/$GRAFANA_DOMAIN/g" \
    "$SCRIPT_DIR/nginx/credit-risk.conf" > "$site"
  ln -sfn "$site" /etc/nginx/sites-enabled/credit-risk.conf
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || log "warning: nginx not reloaded"
  log "nginx vhost: $API_DOMAIN -> 127.0.0.1:18020, $GRAFANA_DOMAIN -> 127.0.0.1:13000"
}

install_units() {
  local unit
  for unit in credit-risk.service credit-risk-backup.service credit-risk-backup.timer; do
    sed -e "s#/opt/credit-risk#$DEPLOY_ROOT#g" -e "s#^User=deploy#User=$DEPLOY_USER#" \
      -e "s#^Environment=BACKUP_DIR=.*#Environment=BACKUP_DIR=$BACKUP_DIR#" \
      "$SCRIPT_DIR/systemd/$unit" > "/etc/systemd/system/$unit"
  done
  if systemctl daemon-reload 2>/dev/null; then
    systemctl enable credit-risk.service credit-risk-backup.timer >/dev/null
    systemctl start credit-risk-backup.timer
    log "systemd: credit-risk.service enabled (starts the live release on boot), backup timer 02:00"
  else
    log "warning: systemd not available; units copied to /etc/systemd/system only"
  fi
}

install_packages
create_user_and_layout
configure_firewall
install_nginx
install_units

log "done. Next: put secrets in $DEPLOY_ROOT/shared/.env (chmod 600), deploy a release with deploy.sh,"
log "then 'sudo certbot --nginx -d $API_DOMAIN -d $GRAFANA_DOMAIN --redirect' once DNS points here."
