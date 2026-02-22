#!/usr/bin/env bash
set -e
PROJECT="${PROJECT:-synexis-project-sentinel}"
REGION="${REGION:-us-east1}"
SA="${SA:-88284566970-compute@developer.gserviceaccount.com}"
DATASET="sentinel_raw"

VHP_URL="https://volcanoes.usgs.gov/feeds/json/volcanoes.geojson"
TSU_URL="https://tsunami.gov/events/xml/PAAQAtom10.1.xml"
SWPC_ALERTS_URL="https://services.swpc.noaa.gov/json/alerts.json"
GEOMAG_URL="https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
WATER_URL="https://waterservices.usgs.gov/nwis/iv/?format=json&sites=01646500,01651000&parameterCd=00060,00065"

gcloud config set project "$PROJECT" >/dev/null

deploy_one () {
  local DIR="$1" FN="$2" TABLE="$3" URL="$4" EXTRA="$5"
  pushd "$DIR" >/dev/null
  gcloud functions deploy "$FN" \
    --gen2 --region="$REGION" --runtime=python311 \
    --entry-point=handler --source=. \
    --set-env-vars="BQ_DATASET=$DATASET,BQ_TABLE=$TABLE,SOURCE_URL=$URL$([ -n "$EXTRA" ] && echo ",$EXTRA")" \
    --trigger-http --allow-unauthenticated
  local FURL
  FURL="$(gcloud functions describe "$FN" --region="$REGION" --format='value(serviceConfig.uri)')"
  local JOB="${FN}-5min"
  if gcloud scheduler jobs describe "$JOB" --location="$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$JOB" \
      --location="$REGION" --schedule="*/5 * * * *" \
      --uri="$FURL" --http-method=GET \
      --oidc-service-account-email="$SA" \
      --oidc-token-audience="$FURL" >/dev/null
  else
    gcloud scheduler jobs create http "$JOB" \
      --location="$REGION" --schedule="*/5 * * * *" \
      --uri="$FURL" --http-method=GET \
      --oidc-service-account-email="$SA" \
      --oidc-token-audience="$FURL" >/dev/null
  fi
  popd >/dev/null
}

deploy_one "$HOME/fusion_agents/poll_usgs_vhp_v1"       "poll_usgs_vhp_v1"       "usgs_volcano_raw"        "$VHP_URL"        ""
deploy_one "$HOME/fusion_agents/poll_noaa_tsunami_v1"   "poll_noaa_tsunami_v1"   "tsunami_alerts_raw"      "$TSU_URL"        ""
deploy_one "$HOME/fusion_agents/poll_swpc_alerts_v1"    "poll_swpc_alerts_v1"    "space_weather_alerts_raw""$SWPC_ALERTS_URL" ""
deploy_one "$HOME/fusion_agents/poll_geomag_indices_v1" "poll_geomag_indices_v1" "geomag_indices_raw"      "$GEOMAG_URL"     "SRC_TAG=swpc"
deploy_one "$HOME/fusion_agents/poll_usgs_water_iv_v1"  "poll_usgs_water_iv_v1"  "water_iv_raw"            "$WATER_URL"      ""
