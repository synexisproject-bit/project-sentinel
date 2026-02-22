#!/usr/bin/env bash
# ============================================================
# Project Sentinel — Manual Orchestrator
# Triggers all active environmental feeds in sequence,
# reports results, and logs the run to BigQuery.
# ============================================================
set -uo pipefail

PROJECT="synexis-project-sentinel"
RUN_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PASS=0
FAIL=0
SUMMARY=""

echo ""
echo "================================================"
echo "  PROJECT SENTINEL — MANUAL RUN"
echo "  $(date -u)"
echo "================================================"
echo ""

# Get auth token
TOKEN="$(gcloud auth print-identity-token)"

# ── POST helper ──────────────────────────────────────────────
call_post() {
  local name=$1
  local url=$2
  echo "--> Calling: $name"
  RESPONSE=$(curl -s -o /tmp/sentinel_resp.txt -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}' \
    "${url}" 2>/dev/null)
  BODY=$(cat /tmp/sentinel_resp.txt)
  if [ "$RESPONSE" == "200" ]; then
    echo "    ✓ SUCCESS (HTTP 200)"
    echo "    Response: $(echo $BODY | head -c 200)"
    PASS=$((PASS + 1))
    SUMMARY="${SUMMARY}${name}:OK "
  else
    echo "    ✗ FAILED (HTTP ${RESPONSE})"
    echo "    Response: $(echo $BODY | head -c 200)"
    FAIL=$((FAIL + 1))
    SUMMARY="${SUMMARY}${name}:FAIL "
  fi
  echo ""
}

# ── GET helper ───────────────────────────────────────────────
call_get() {
  local name=$1
  local url=$2
  echo "--> Calling: $name"
  RESPONSE=$(curl -s -o /tmp/sentinel_resp.txt -w "%{http_code}" \
    -X GET \
    -H "Authorization: Bearer $TOKEN" \
    "${url}" 2>/dev/null)
  BODY=$(cat /tmp/sentinel_resp.txt)
  if [ "$RESPONSE" == "200" ]; then
    echo "    ✓ SUCCESS (HTTP 200)"
    echo "    Response: $(echo $BODY | head -c 200)"
    PASS=$((PASS + 1))
    SUMMARY="${SUMMARY}${name}:OK "
  else
    echo "    ✗ FAILED (HTTP ${RESPONSE})"
    echo "    Response: $(echo $BODY | head -c 200)"
    FAIL=$((FAIL + 1))
    SUMMARY="${SUMMARY}${name}:FAIL "
  fi
  echo ""
}

# ── Feed Calls ───────────────────────────────────────────────
call_post "poll-usgs-eq-v1" \
  "https://poll-usgs-eq-v1-qnnlb3nima-ue.a.run.app/run"

call_post "poll-solarwind-v1" \
  "https://poll-solarwind-v2-88284566970.us-east1.run.app/"

call_post "poll-noaa-tsunami-cap-v2" \
  "https://poll-noaa-tsunami-cap-v2-qnnlb3nima-ue.a.run.app/run"

call_get "poll-geomag-kp-http-v1" \
  "https://poll-geomag-kp-http-v1-qnnlb3nima-ue.a.run.app/"

# ── Summary ──────────────────────────────────────────────────
echo "================================================"
echo "  RUN COMPLETE"
echo "  Passed: $PASS  |  Failed: $FAIL"
echo "  $SUMMARY"
echo "================================================"
echo ""

# ── Log to BigQuery ──────────────────────────────────────────
NOTE="manual_run ts=${RUN_TS} passed=${PASS} failed=${FAIL} ${SUMMARY}"
bq query --nouse_legacy_sql \
  "INSERT INTO \`${PROJECT}.sentinel_core.refresh_log\` (run_ts, note)
   VALUES (TIMESTAMP('${RUN_TS}'), '${NOTE}')" > /dev/null 2>&1
echo "  Run logged to sentinel_core.refresh_log"
echo ""
