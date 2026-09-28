#!/usr/bin/env bash
# Backup and restore of the stateful data of the Credit Risk stack on a Docker host.
#
#   PostgreSQL  one pg_dump (custom format) per database: inference logs, MLflow metadata, Airflow
#   MinIO       mc mirror of the MLflow artifact bucket (model binaries, plots, reports)
#
# Prometheus TSDB, Grafana and Alertmanager state are not backed up: dashboards, rules and
# datasources are provisioned from git and metrics are disposable.
#
# Usage:
#   backup.sh backup            write BACKUP_DIR/<UTC timestamp>/ and keep the newest BACKUP_KEEP
#   backup.sh list              list backups with their size
#   backup.sh restore <dir>     stop the app services, restore PostgreSQL + MinIO, start them again
#
# Environment:
#   DEPLOY_ROOT      /opt/credit-risk
#   ENV_FILE         $DEPLOY_ROOT/shared/.env (POSTGRES_USER, MINIO_ROOT_USER/PASSWORD, MINIO_BUCKET)
#   BACKUP_DIR       /var/backups/credit-risk
#   BACKUP_KEEP      7
#   COMPOSE_PROJECT  credit-risk-mlops
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/credit-risk}"
ENV_FILE="${ENV_FILE:-$DEPLOY_ROOT/shared/.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/credit-risk}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-credit-risk-mlops}"
MC_IMAGE="${MC_IMAGE:-pgsty/mc:RELEASE.2026-08-04T00-00-00Z@sha256:b57234d21057175b6c3358509733128e35da330094aaacf37bf33348b11d1f92}"
# Services that write to PostgreSQL or MinIO; stopped during a restore and restarted in
# this order. MLflow must be healthy before the API starts, otherwise the API boots on
# the local fallback artifact instead of the registry @champion.
APP_SERVICES=(mlflow api drift-monitor airflow-webserver airflow-scheduler)
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

log() { printf '[backup] %s\n' "$*"; }
die() { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }

# Last assignment of KEY in ENV_FILE (quotes stripped), or the default.
env_value() {
  local value=""
  [[ -f "$ENV_FILE" ]] && value="$(sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | sed -e 's/^["'\'']//' -e 's/["'\'']$//')"
  printf '%s' "${value:-$2}"
}

container_of() {
  docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
    --filter "label=com.docker.compose.service=$1" | head -n 1
}

require_container() {
  local id
  id="$(container_of "$1")"
  [[ -n "$id" ]] || die "service '$1' of project '$COMPOSE_PROJECT' is not running"
  printf '%s' "$id"
}

wait_healthy() {
  local id="$1" deadline=$((SECONDS + HEALTH_TIMEOUT)) status
  while true; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")"
    [[ "$status" == "healthy" || "$status" == "running" ]] && return 0
    (( SECONDS < deadline )) || die "container $id not healthy after ${HEALTH_TIMEOUT}s (status: $status)"
    sleep 3
  done
}

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi
}

# mc runs inside the MinIO container's network namespace, as the calling user so the
# mirrored files stay removable by the retention step.
mc_run() {
  local minio="$1" mount="$2" script="$3"
  docker run --rm --network "container:$minio" --user "$(id -u):$(id -g)" \
    -e MC_USER="$(env_value MINIO_ROOT_USER minioadmin)" \
    -e MC_PASS="$(env_value MINIO_ROOT_PASSWORD miniopassword)" \
    -v "$mount:/backup" --entrypoint /bin/sh "$MC_IMAGE" -c \
    "mc -C /tmp/mc alias set src http://127.0.0.1:9000 \"\$MC_USER\" \"\$MC_PASS\" >/dev/null && $script"
}

cmd_backup() {
  local pg minio pg_user bucket stamp dest db release=""
  pg="$(require_container postgres)"
  minio="$(require_container minio)"
  pg_user="$(env_value POSTGRES_USER mlops)"
  bucket="$(env_value MINIO_BUCKET mlflow)"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dest="$BACKUP_DIR/$stamp"
  mkdir -p "$dest/postgres" "$dest/minio"
  chmod 700 "$dest"

  while IFS= read -r db; do
    [[ -n "$db" ]] || continue
    log "pg_dump $db"
    docker exec "$pg" pg_dump -U "$pg_user" -Fc "$db" > "$dest/postgres/$db.dump"
  done < <(docker exec "$pg" psql -U "$pg_user" -d postgres -Atc \
    "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1")

  log "mc mirror $bucket"
  mc_run "$minio" "$dest/minio" "mc -C /tmp/mc mirror --overwrite src/$bucket /backup/$bucket >/dev/null"

  [[ -L "$DEPLOY_ROOT/current" ]] && release="$(basename "$(readlink -f "$DEPLOY_ROOT/current")")"
  {
    echo "created_utc=$stamp"
    echo "compose_project=$COMPOSE_PROJECT"
    echo "release=${release:-unknown}"
    echo "minio_bucket=$bucket"
  } > "$dest/MANIFEST"
  (cd "$dest" && find postgres minio -type f | sort | while IFS= read -r file; do sha256 "$file"; done > SHA256SUMS)
  log "backup written to $dest ($(du -sh "$dest" | cut -f1))"
  prune
}

prune() {
  local total
  total="$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' | wc -l | tr -d ' ')"
  (( total > BACKUP_KEEP )) || return 0
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | head -n "$((total - BACKUP_KEEP))" \
    | while IFS= read -r old; do
        log "pruning $old"
        rm -rf -- "$old"
      done
}

cmd_list() {
  [[ -d "$BACKUP_DIR" ]] || { echo "no backups in $BACKUP_DIR"; return 0; }
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | while IFS= read -r dir; do
    printf '%s  %s\n' "$(du -sh "$dir" | cut -f1)" "$dir"
  done
}

cmd_restore() {
  local src="${1:-}" pg minio pg_user bucket dump db service id
  local stopped=()
  [[ -n "$src" && -d "$src/postgres" && -f "$src/SHA256SUMS" ]] || die "usage: backup.sh restore <backup dir>"
  src="$(cd "$src" && pwd)"
  (cd "$src" && sha256 -c --quiet SHA256SUMS) || die "checksum mismatch in $src"
  pg="$(require_container postgres)"
  minio="$(require_container minio)"
  pg_user="$(env_value POSTGRES_USER mlops)"
  bucket="$(sed -n 's/^minio_bucket=//p' "$src/MANIFEST")"
  bucket="${bucket:-$(env_value MINIO_BUCKET mlflow)}"

  for service in "${APP_SERVICES[@]}"; do
    id="$(container_of "$service")"
    [[ -n "$id" ]] || continue
    log "stopping $service"
    docker stop "$id" >/dev/null
    stopped+=("$id")
  done

  for dump in "$src"/postgres/*.dump; do
    db="$(basename "$dump" .dump)"
    log "restoring database $db"
    docker exec "$pg" psql -U "$pg_user" -d postgres -v ON_ERROR_STOP=1 -q \
      -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" -c "CREATE DATABASE \"$db\" OWNER \"$pg_user\""
    docker exec -i "$pg" pg_restore -U "$pg_user" -d "$db" --no-owner --exit-on-error < "$dump"
  done

  if [[ -d "$src/minio/$bucket" ]]; then
    log "restoring bucket $bucket"
    mc_run "$minio" "$src/minio" \
      "mc -C /tmp/mc mb --ignore-existing src/$bucket >/dev/null && mc -C /tmp/mc mirror --overwrite --remove /backup/$bucket src/$bucket >/dev/null"
  fi

  for id in ${stopped[@]+"${stopped[@]}"}; do
    log "starting $(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id")"
    docker start "$id" >/dev/null
    wait_healthy "$id"
  done
  log "restore from $src complete; verify with 'make health' or 'deploy.sh smoke'"
}

command -v docker >/dev/null || die "docker is not installed"

case "${1:-}" in
  backup) cmd_backup ;;
  list) cmd_list ;;
  restore) shift; cmd_restore "$@" ;;
  *) sed -n '2,20p' "$0"; exit 64 ;;
esac
