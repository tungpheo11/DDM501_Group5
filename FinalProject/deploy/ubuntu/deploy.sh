#!/usr/bin/env bash
# Release-based deployment of the Compose stack on an Ubuntu host.
# Driven over SSH by .github/workflows/final-project-cd.yml; also usable by hand.
#
# Layout under DEPLOY_ROOT (default /opt/credit-risk):
#   releases/<tag>/     FinalProject tree of git tag <tag>; .image holds the image ref it runs
#   shared/.env         runtime config + secrets (never in git), linked into every release
#   current             symlink -> releases/<tag> that is live
#   previous_release    tag that was live before the last deploy (rollback target)
#
# Usage:
#   deploy.sh deploy <tag> <image-ref>   switch the stack to <tag> running <image-ref>
#   deploy.sh smoke                      health + predict check against the live API
#   deploy.sh rollback                   redeploy previous_release, then smoke test it
#   deploy.sh status                     show current/previous release and containers
#   deploy.sh start | stop               start/stop the live release (systemd credit-risk.service)
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/credit-risk}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-300}"
RELEASES_DIR="$DEPLOY_ROOT/releases"
CURRENT_LINK="$DEPLOY_ROOT/current"
SHARED_ENV="$DEPLOY_ROOT/shared/.env"
PREVIOUS_FILE="$DEPLOY_ROOT/previous_release"

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

# Last assignment of KEY in shared/.env, surrounding quotes stripped.
env_value() {
  sed -n "s/^$1=//p" "$SHARED_ENV" | tail -n 1 | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

# base -> production overlay (when the release ships one) -> prebuilt API image.
# Profiles come from COMPOSE_PROFILES in shared/.env.
compose() {
  local release_dir="$1" compose_dir
  shift
  compose_dir="$release_dir/deploy/compose"
  local files=(-f "$compose_dir/docker-compose.yml")
  [[ -f "$compose_dir/docker-compose.prod.yml" ]] && files+=(-f "$compose_dir/docker-compose.prod.yml")
  files+=(-f "$compose_dir/docker-compose.image.yml")
  API_IMAGE="$(cat "$release_dir/.image")" docker compose "${files[@]}" --env-file "$SHARED_ENV" "$@"
}

current_tag() {
  if [[ -L "$CURRENT_LINK" ]]; then basename "$(readlink -f "$CURRENT_LINK")"; fi
}

prune_releases() {
  local keep_current keep_previous name
  keep_current="$(current_tag)"
  keep_previous="$(cat "$PREVIOUS_FILE" 2>/dev/null || true)"
  # Newest first; everything past KEEP_RELEASES goes, except the live and rollback releases.
  while IFS= read -r release; do
    name="$(basename "$release")"
    [[ "$name" == "$keep_current" || "$name" == "$keep_previous" ]] && continue
    log "pruning old release $name"
    rm -rf -- "$release"
  done < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn \
    | tail -n +"$((KEEP_RELEASES + 1))" | cut -d' ' -f2-)
}

cmd_deploy() {
  local tag="${1:-}" image="${2:-}" release_dir previous
  [[ "$tag" =~ ^v[0-9A-Za-z._-]+$ ]] || die "release tag must look like v1.2.3, got '$tag'"
  [[ "$image" =~ ^[a-z0-9]([a-z0-9._/-]*[a-z0-9])?(:[A-Za-z0-9._-]+)?(@sha256:[a-f0-9]{64})?$ ]] \
    || die "invalid image reference '$image'"
  release_dir="$RELEASES_DIR/$tag"
  [[ -f "$release_dir/deploy/compose/docker-compose.yml" ]] || die "release bundle not found in $release_dir"
  [[ -f "$SHARED_ENV" ]] || die "missing $SHARED_ENV (copy .env.example there and set real secrets)"

  printf '%s\n' "$image" > "$release_dir/.image"
  ln -sfn "$SHARED_ENV" "$release_dir/.env"

  previous="$(current_tag)"
  if [[ -n "$previous" && "$previous" != "$tag" ]]; then
    printf '%s\n' "$previous" > "$PREVIOUS_FILE"
  fi
  log "deploying $tag ($image); rollback target: $(cat "$PREVIOUS_FILE" 2>/dev/null || echo none)"

  compose "$release_dir" config --quiet
  # The API image is referenced by digest, so "missing" never serves a stale image.
  compose "$release_dir" pull --quiet --policy missing
  compose "$release_dir" up -d --remove-orphans
  ln -sfn "$release_dir" "$CURRENT_LINK"
  log "stack is up on $tag"
  prune_releases
}

cmd_smoke() {
  local release_dir api_key api_port
  [[ -L "$CURRENT_LINK" ]] || die "no live release ($CURRENT_LINK missing)"
  release_dir="$(readlink -f "$CURRENT_LINK")"
  api_key="$(env_value API_KEY)"
  [[ -n "$api_key" ]] || api_key="$(env_value API_KEYS | cut -d, -f1 | tr -d '[:space:]')"
  api_port="$(env_value API_PORT)"
  log "smoke testing $(basename "$release_dir")"
  API_URL="http://127.0.0.1:${api_port:-18020}" API_KEY="$api_key" SMOKE_TIMEOUT="$SMOKE_TIMEOUT" \
    SMOKE_REQUIRE_READY="${SMOKE_REQUIRE_READY:-false}" bash "$release_dir/deploy/scripts/smoke_test.sh"
}

cmd_rollback() {
  local target release_dir
  target="$(cat "$PREVIOUS_FILE" 2>/dev/null || true)"
  [[ -n "$target" ]] || die "no previous release recorded; nothing to roll back to"
  release_dir="$RELEASES_DIR/$target"
  [[ -f "$release_dir/.image" ]] || die "previous release $target is incomplete ($release_dir/.image missing)"
  log "rolling back from $(current_tag || true) to $target ($(cat "$release_dir/.image"))"
  compose "$release_dir" up -d --remove-orphans
  ln -sfn "$release_dir" "$CURRENT_LINK"
  cmd_smoke
  # Only one level of history is kept: the rollback target is now live, so there is
  # nothing older to return to until the next successful deploy records one.
  rm -f "$PREVIOUS_FILE"
  log "rollback to $target complete"
}

live_release_dir() {
  [[ -L "$CURRENT_LINK" ]] || die "no live release ($CURRENT_LINK missing); run 'deploy.sh deploy' first"
  readlink -f "$CURRENT_LINK"
}

cmd_start() {
  local release_dir
  release_dir="$(live_release_dir)"
  log "starting $(basename "$release_dir")"
  compose "$release_dir" up -d --remove-orphans
}

cmd_stop() {
  local release_dir
  release_dir="$(live_release_dir)"
  log "stopping $(basename "$release_dir") (volumes kept)"
  compose "$release_dir" stop
}

cmd_status() {
  local tag
  tag="$(current_tag)"
  echo "current:  ${tag:-none}"
  echo "previous: $(cat "$PREVIOUS_FILE" 2>/dev/null || echo none)"
  if [[ -n "$tag" ]]; then
    echo "image:    $(cat "$RELEASES_DIR/$tag/.image")"
    compose "$RELEASES_DIR/$tag" ps
  fi
}

# curl and python3 are needed by the post-deploy smoke test (both ship with Ubuntu Server);
# checking them up front avoids deploying a release that can never pass its smoke test.
for tool in docker curl python3; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done
mkdir -p "$RELEASES_DIR"

case "${1:-}" in
  deploy) shift; cmd_deploy "$@" ;;
  smoke) cmd_smoke ;;
  rollback) cmd_rollback ;;
  status) cmd_status ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  *) sed -n '2,16p' "$0"; exit 64 ;;
esac
