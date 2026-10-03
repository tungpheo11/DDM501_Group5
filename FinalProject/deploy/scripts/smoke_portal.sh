#!/usr/bin/env bash
# Black-box smoke test of a running staff portal (and, through it, the scoring API):
# health -> login of the three roles -> cross-role 403 -> one scored request -> no API key in pages.
# Used by `make smoke` after deploy/scripts/smoke_test.sh. Needs only bash, curl and python3.
#
#   PORTAL_URL=http://localhost:18030 API_KEY=... deploy/scripts/smoke_portal.sh
#
# Environment:
#   PORTAL_URL                                base URL of the portal       (default http://localhost:18030)
#   API_KEY                                   scoring key that must never appear in HTML/JS (required)
#   PORTAL_{CSKH,ANALYST,ADMIN}_USERNAME      demo usernames               (default cskh / chuyenvien / admin)
#   PORTAL_{CSKH,ANALYST,ADMIN}_PASSWORD      demo passwords               (required)
#   SMOKE_TIMEOUT                             seconds to wait for /health  (default 300)
set -euo pipefail

PORTAL_URL="${PORTAL_URL:-http://localhost:18030}"
PORTAL_URL="${PORTAL_URL%/}"
API_KEY="${API_KEY:-}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-300}"

log() { printf '[smoke-portal] %s\n' "$*"; }
fail() { printf '[smoke-portal] FAIL: %s\n' "$*" >&2; exit 1; }

[[ -n "$API_KEY" ]] || fail "API_KEY is empty"
for tool in curl python3; do
  command -v "$tool" >/dev/null || fail "$tool is required"
done

# Plain functions instead of associative arrays: macOS still ships bash 3.2.
username_of() {
  case "$1" in
    cskh) echo "${PORTAL_CSKH_USERNAME:-cskh}" ;;
    analyst) echo "${PORTAL_ANALYST_USERNAME:-chuyenvien}" ;;
    admin) echo "${PORTAL_ADMIN_USERNAME:-admin}" ;;
  esac
}
password_of() {
  case "$1" in
    cskh) echo "${PORTAL_CSKH_PASSWORD:-}" ;;
    analyst) echo "${PORTAL_ANALYST_PASSWORD:-}" ;;
    admin) echo "${PORTAL_ADMIN_PASSWORD:-}" ;;
  esac
}
home_of() { echo "/$1"; }

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
body_file="$work_dir/body"
headers_file="$work_dir/headers"

# Prints the HTTP status; body -> $body_file, headers -> $headers_file. First argument: cookie jar.
http() {
  local jar="$1"
  shift
  curl --silent --show-error --max-time 15 --cookie "$jar" --cookie-jar "$jar" \
    --output "$body_file" --dump-header "$headers_file" --write-out '%{http_code}' "$@" || echo "000"
}

csrf_token() {
  python3 -c 'import re,sys; m=re.search(r"name=\"csrf_token\" value=\"([^\"]+)\"", open(sys.argv[1]).read()); print(m.group(1) if m else "")' "$body_file"
}

assert_no_key() {
  ! grep -qF -- "$API_KEY" "$body_file" || fail "API key found in $1"
}

log "target: $PORTAL_URL (timeout ${SMOKE_TIMEOUT}s)"
deadline=$((SECONDS + SMOKE_TIMEOUT))
anon="$work_dir/anon.jar"
until [[ "$(http "$anon" "$PORTAL_URL/health" 2>/dev/null)" == "200" ]]; do
  (( SECONDS < deadline )) || fail "GET /health did not return 200 within ${SMOKE_TIMEOUT}s"
  sleep 3
done
python3 - "$body_file" <<'PY' || fail "health check failed: $(cat "$body_file")"
import json
import sys

body = json.load(open(sys.argv[1]))
assert body["status"] == "ok" and body["database"] == "ok", body
assert body["accounts"] == 3, f"expected 3 demo accounts, got {body['accounts']}"
print(f"[smoke-portal] GET /health -> 200 catalog={body['catalog_size']} demo_mode={body['demo_mode']}")
PY

status="$(http "$anon" "$PORTAL_URL/admin")"
[[ "$status" == "303" ]] || fail "anonymous GET /admin returned $status, expected 303 to /login"
log "anonymous GET /admin -> 303 (login required)"

for role in cskh analyst admin; do
  user="$(username_of "$role")"
  password="$(password_of "$role")"
  home="$(home_of "$role")"
  [[ -n "$password" ]] || fail "no password configured for the $role account"
  jar="$work_dir/$role.jar"
  status="$(http "$jar" "$PORTAL_URL/login")"
  [[ "$status" == "200" ]] || fail "GET /login returned $status"
  assert_no_key "/login"
  token="$(csrf_token)"
  [[ -n "$token" ]] || fail "login page has no CSRF token"
  status="$(http "$jar" -X POST "$PORTAL_URL/login" --data-urlencode "username=$user" \
    --data-urlencode "password=$password" --data-urlencode "csrf_token=$token")"
  [[ "$status" == "303" ]] || fail "login as $user returned $status"
  grep -qi "^location: $home" "$headers_file" || fail "login as $role did not redirect to $home"
  status="$(http "$jar" "$PORTAL_URL$home")"
  [[ "$status" == "200" ]] || fail "GET $home as $role returned $status"
  assert_no_key "$home"
  log "login $user ($role) -> $home 200"
done

for pair in cskh:/admin analyst:/admin admin:/cskh cskh:/analyst; do
  role="${pair%%:*}"
  path="${pair#*:}"
  status="$(http "$work_dir/$role.jar" "$PORTAL_URL$path")"
  [[ "$status" == "403" ]] || fail "$role GET $path returned $status, expected 403"
done
log "cross-role access -> 403"

jar="$work_dir/cskh.jar"
http "$jar" "$PORTAL_URL/cskh" >/dev/null
customer="$(python3 -c 'import re,sys; m=re.search(r"/cskh/customers/(KH\d{6})", open(sys.argv[1]).read()); print(m.group(1) if m else "")' "$body_file")"
[[ -n "$customer" ]] || fail "customer search page lists no cardholder"
status="$(http "$jar" "$PORTAL_URL/cskh/customers/$customer")"
[[ "$status" == "200" ]] || fail "GET /cskh/customers/$customer returned $status"
token="$(csrf_token)"
status="$(http "$jar" -X POST "$PORTAL_URL/cskh/customers/$customer/requests" -H "HX-Request: true" \
  -H "X-CSRF-Token: $token" --data-urlencode "request_type=LIMIT_INCREASE")"
[[ "$status" == "200" ]] || fail "scoring request through the portal returned $status: $(head -c 400 "$body_file")"
grep -qE 'decision decision--(APPROVE|REVIEW|DECLINE)' "$body_file" || fail "no decision in the portal response"
assert_no_key "the decision panel"
decision="$(grep -oE 'decision--(APPROVE|REVIEW|DECLINE)' "$body_file" | head -1)"
log "CSKH request for $customer -> ${decision#decision--}"

status="$(http "$jar" -X POST "$PORTAL_URL/cskh/customers/$customer/requests" --data-urlencode "request_type=LIMIT_INCREASE")"
[[ "$status" == "403" ]] || fail "POST without CSRF token returned $status, expected 403"
log "POST without CSRF token -> 403"

for asset in /static/js/portal.js /static/vendor/htmx-2.0.11.min.js /static/css/portal.css; do
  status="$(http "$anon" "$PORTAL_URL$asset")"
  [[ "$status" == "200" ]] || fail "GET $asset returned $status"
  assert_no_key "$asset"
done
log "static assets served locally, no API key"

log "PASS"
