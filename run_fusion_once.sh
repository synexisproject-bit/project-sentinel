#!/usr/bin/env bash
set -euo pipefail

PROJECT="${PROJECT:-synexis-project-sentinel}"
REGION="${REGION:-us-east1}"

SERVICES=(
  poll-usgs-quakes-v3
  poll-nws-cap-v1
  poll-geomag-kp-v1
  poll-solarwind-v1
  poll-donki-v1
  poll-astro-daily-v1
  poll-gcp-egg-v1
)

echo "=== Project Sentinel Manual Run ==="
echo "Project: $PROJECT  Region: $REGION"
TOKEN="$(gcloud auth print-identity-token)"

for SVC in "${SERVICES[@]}"; do
  URL="$(gcloud run services describe "$SVC" --region "$REGION" --format='value(status.url)')"
  echo "--> $SVC  POST $URL/run"
  curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}' \
    "$URL/run" || true
  echo
done

# publish hypotheses (AOI view -> Pub/Sub -> sink -> BQ)
PUB_URL="$(gcloud run services describe fusion-publisher-aoi-v1 --region "$REGION" --format='value(status.url)')"
echo "--> fusion-publisher-aoi-v1 POST $PUB_URL/run?limit=10"
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$PUB_URL/run?limit=10" || true
echo
