#!/usr/bin/env bash
# ============================================================
# Project Sentinel — Manual Orchestrator v3
# All verified environmental feeds
# ============================================================
set -uo pipefail

PROJECT="synexis-project-sentinel"
RUN_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PASS=0
FAIL=0
SUMMARY=""

echo ""
echo "================================================"
echo "  PROJECT SENTINEL — MANUAL RUN v3"
echo "  $(date -u)"
echo "================================================"
echo ""

TOKEN="$(gcloud auth print-identity-token)"

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

# ── Seismic ──────────────────────────────────────────────────
call_post "poll-usgs-eq-v1" "https://poll-usgs-eq-v1-qnnlb3nima-ue.a.run.app/run"
call_post "poll-usgs-volcano-cap-v2" "https://poll-usgs-volcano-cap-v2-88284566970.us-east1.run.app/run"
call_post "poll-usgs-vhp-v1" "https://poll-usgs-vhp-v1-88284566970.us-east1.run.app/run"

# ── Tsunami & Weather ────────────────────────────────────────
call_post "poll-noaa-tsunami-cap-v2" "https://poll-noaa-tsunami-cap-v2-qnnlb3nima-ue.a.run.app/run"
call_post "poll-usgs-water-iv-v2" "https://poll-usgs-water-iv-v2-88284566970.us-east1.run.app/run"

# ── Solar & Geomagnetic ──────────────────────────────────────
call_post "poll-solarwind-v2" "https://poll-solarwind-v2-88284566970.us-east1.run.app/"
call_get  "poll-geomag-kp-http-v1" "https://poll-geomag-kp-http-v1-qnnlb3nima-ue.a.run.app/"
call_post "poll-swpc-alerts-v2" "https://poll-swpc-alerts-v2-88284566970.us-east1.run.app/run"
call_post "poll-swpc-solar-v1" "$(gcloud run services describe poll-swpc-solar-v1 --region=us-east1 --format='value(status.url)')/run"
call_post "poll-donki-v2" "https://poll-donki-v2-88284566970.us-east1.run.app/"

# ── RNG Proxy ────────────────────────────────────────────────
call_get  "poll-gcp-egg-v1" "$(gcloud run services describe poll-gcp-egg-v1 --region=us-east1 --format='value(status.url)')/"

# ── Summary ──────────────────────────────────────────────────
echo "================================================"
echo "  RUN COMPLETE"
echo "  Passed: $PASS  |  Failed: $FAIL"
echo "  $SUMMARY"
echo "================================================"
echo ""

NOTE="manual_run ts=${RUN_TS} passed=${PASS} failed=${FAIL} ${SUMMARY}"
bq query --nouse_legacy_sql \
  "INSERT INTO \`${PROJECT}.sentinel_core.refresh_log\` (run_ts, note)
   VALUES (TIMESTAMP('${RUN_TS}'), '${NOTE}')" > /dev/null 2>&1
echo "  Run logged to sentinel_core.refresh_log"
echo ""
