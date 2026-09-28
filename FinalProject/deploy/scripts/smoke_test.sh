#!/usr/bin/env bash
# Black-box smoke test of a running scoring API: liveness -> readiness -> auth -> predict.
# Shared by `make smoke` (CI compose stack) and deploy/ubuntu/deploy.sh (post-deploy).
# Needs only bash, curl and python3.
#
#   API_URL=http://localhost:18020 API_KEY=... deploy/scripts/smoke_test.sh
#
# Environment:
#   API_URL               base URL of the API                 (default http://localhost:18020)
#   API_KEY               key sent as X-API-Key               (required)
#   SMOKE_TIMEOUT         seconds to wait for readiness       (default 300)
#   SMOKE_REQUIRE_READY   "true" rejects the degraded state   (default false)
set -euo pipefail

API_URL="${API_URL:-http://localhost:18020}"
API_URL="${API_URL%/}"
API_KEY="${API_KEY:-}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-300}"
SMOKE_REQUIRE_READY="${SMOKE_REQUIRE_READY:-false}"

log() { printf '[smoke] %s\n' "$*"; }
fail() { printf '[smoke] FAIL: %s\n' "$*" >&2; exit 1; }

[[ -n "$API_KEY" ]] || fail "API_KEY is empty"
for tool in curl python3; do
  command -v "$tool" >/dev/null || fail "$tool is required"
done

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT

# Prints the HTTP status; the response body goes to $body_file.
http() {
  curl --silent --show-error --max-time 10 --output "$body_file" --write-out '%{http_code}' "$@" || echo "000"
}

log "target: $API_URL (timeout ${SMOKE_TIMEOUT}s)"

deadline=$((SECONDS + SMOKE_TIMEOUT))
# Connection errors are expected while the container starts; keep the wait loop quiet.
until [[ "$(http "$API_URL/health/live" 2>/dev/null)" == "200" ]]; do
  (( SECONDS < deadline )) || fail "GET /health/live did not return 200 within ${SMOKE_TIMEOUT}s"
  sleep 3
done
log "GET /health/live -> 200"

until status="$(http "$API_URL/health/ready")" && [[ "$status" == "200" ]]; do
  (( SECONDS < deadline )) || fail "GET /health/ready returned $status: $(cat "$body_file")"
  sleep 3
done
readiness="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$body_file")"
case "$readiness" in
  ready) log "GET /health/ready -> 200 (ready)" ;;
  degraded)
    [[ "$SMOKE_REQUIRE_READY" != "true" ]] || fail "readiness is degraded: $(cat "$body_file")"
    log "GET /health/ready -> 200 (degraded: $(python3 -c 'import json,sys; print("; ".join(json.load(open(sys.argv[1]))["reasons"]))' "$body_file"))"
    ;;
  *) fail "unexpected readiness status '$readiness'" ;;
esac

payload='{"LIMIT_BAL": 200000.0, "SEX": 2, "EDUCATION": 1, "MARRIAGE": 2, "AGE": 38,
  "PAY_0": 0, "PAY_2": 0, "PAY_3": 0, "PAY_4": 0, "PAY_5": 0, "PAY_6": 0,
  "BILL_AMT1": 15000.0, "BILL_AMT2": 14000.0, "BILL_AMT3": 13000.0,
  "BILL_AMT4": 12000.0, "BILL_AMT5": 11000.0, "BILL_AMT6": 10000.0,
  "PAY_AMT1": 5000.0, "PAY_AMT2": 5000.0, "PAY_AMT3": 5000.0,
  "PAY_AMT4": 5000.0, "PAY_AMT5": 5000.0, "PAY_AMT6": 5000.0}'

status="$(http -X POST "$API_URL/api/v1/predict" -H 'Content-Type: application/json' --data "$payload")"
[[ "$status" == "401" ]] || fail "POST /api/v1/predict without API key returned $status, expected 401"
log "POST /api/v1/predict without key -> 401"

status="$(http -X POST "$API_URL/api/v1/predict" -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" --data "$payload")"
[[ "$status" == "200" ]] || fail "POST /api/v1/predict returned $status: $(cat "$body_file")"
python3 - "$body_file" <<'PY' || fail "prediction response failed validation: $(cat "$body_file")"
import json
import sys

body = json.load(open(sys.argv[1]))
assert 0.0 <= body["default_probability"] <= 1.0, body["default_probability"]
assert body["risk_decision"] in {"APPROVE", "REVIEW", "DECLINE"}, body["risk_decision"]
assert 300 <= body["credit_score"] <= 850, body["credit_score"]
assert body["model_version"] and body["served_by"] and body["request_id"]
print(
    f"[smoke] POST /api/v1/predict -> 200 decision={body['risk_decision']} "
    f"p_default={body['default_probability']:.4f} model={body['model_version']} ({body['served_by']})"
)
PY

log "PASS"
