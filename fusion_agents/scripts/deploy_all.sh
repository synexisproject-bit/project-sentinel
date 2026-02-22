#!/usr/bin/env bash
set -euo pipefail

# ====== GLOBAL CONFIG ======
PROJECT="${PROJECT:-synexis-project-sentinel}"
REGION="${REGION:-us-east1}"
SA="${SA:-88284566970-compute@developer.gserviceaccount.com}"
DATASET="${DATASET:-sentinel_raw}"

# Source URLs (edit to taste)
VHP_URL="${VHP_URL:-https://volcanoes.usgs.gov/feeds/json/volcanoes.geojson}"
TSU_URL="${TSU_URL:-https://www.tsunami.gov/events/xml/PAAQAtom.xml}"
SWPC_ALERTS_URL="${SWPC_ALERTS_URL:-https://services.swpc.noaa.gov/json/alerts.json}"
GEOMAG_URL="${GEOMAG_URL:-https://services.swpc.noaa.gov/json/planetary_k_index_1m.json}"
WATER_URL="${WATER_URL:-https://waterservices.usgs.gov/nwis/iv/?format=json&sites=01646500,01651000&parameterCd=00060,00065}"

gcloud config set project "$PROJECT" >/dev/null

deploy_one () {
  local DIR="$1" FN="$2" TABLE="$3" URL="$4" EXTRA="$5"
  echo "——— Deploying $FN from $DIR ———"
  pushd "$DIR" >/dev/null

  # Custom delimiter so commas in URLs are OK
  gcloud functions deploy "$FN" \
    --gen2 --region="$REGION" --runtime=python311 \
    --entry-point=handler --source=. \
    --set-env-vars=^@^BQ_DATASET="$DATASET"@BQ_TABLE="$TABLE"@SOURCE_URL="$URL"$([ -n "$EXTRA" ] && printf '@%s' "$EXTRA") \
    --trigger-http --allow-unauthenticated

  local SVC_NAME SVC_SHORT FURL JOB
  SVC_NAME="$(gcloud functions describe "$FN" --region="$REGION" --format='value(serviceConfig.service)')"
  FURL="$(gcloud functions describe "$FN" --region="$REGION" --format='value(serviceConfig.uri)')"
  SVC_SHORT="$(basename "$SVC_NAME")"
  echo "  Function URL: $FURL"

  # Ensure scheduler SA can invoke Cloud Run
  gcloud run services add-iam-policy-binding "$SVC_SHORT" \
    --region="$REGION" \
    --member="serviceAccount:$SA" \
    --role="roles/run.invoker" >/dev/null

  JOB="${FN}-5min"
  if gcloud scheduler jobs describe "$JOB" --location="$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$JOB" \
      --location="$REGION" --schedule="*/5 * * * *" \
      --uri="$FURL" --http-method=GET \
      --oidc-service-account-email="$SA" \
      --oidc-token-audience="$FURL" >/dev/null
    echo "  Scheduler updated: $JOB"
  else
    gcloud scheduler jobs create http "$JOB" \
      --location="$REGION" --schedule="*/5 * * * *" \
      --uri="$FURL" --http-method=GET \
      --oidc-service-account-email="$SA" \
      --oidc-token-audience="$FURL" >/dev/null
    echo "  Scheduler created: $JOB"
  fi

  popd >/dev/null
  echo "——— $FN done ———"
  echo
}

deploy_one "$HOME/fusion_agents/poll_usgs_vhp_v1"       "poll_usgs_vhp_v1"       "usgs_volcano_raw"        "$VHP_URL"        ""
deploy_one "$HOME/fusion_agents/poll_noaa_tsunami_v1"   "poll_noaa_tsunami_v1"   "tsunami_alerts_raw"      "$TSU_URL"        ""
deploy_one "$HOME/fusion_agents/poll_swpc_alerts_v1"    "poll_swpc_alerts_v1"    "space_weather_alerts_raw""$SWPC_ALERTS_URL" ""
deploy_one "$HOME/fusion_agents/poll_geomag_indices_v1" "poll_geomag_indices_v1" "geomag_indices_raw"      "$GEOMAG_URL"     "SRC_TAG=swpc"
deploy_one "$HOME/fusion_agents/poll_usgs_water_iv_v1"  "poll_usgs_water_iv_v1"  "water_iv_raw"            "$WATER_URL"      ""

echo "All deploys attempted."
