#!/usr/bin/env bash
set -euo pipefail

# --------- Config ---------
PROJECT="${PROJECT:-synexis-project-sentinel}"
REGION="${REGION:-us-east1}"
NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

RUN_SERVICES=(
  poll-usgs-quakes-v3
  poll-nws-cap-v1
  poll-geomag-kp-v1
  poll-solarwind-v1
  poll-donki-v1
  poll-astro-daily-v1
  fusion-publisher-aoi-v1
  fusion-bq-sink
)

SCHEDULER_JOBS=(
  poll-usgs-quakes-v3-minutely
  poll-usgs-quakes-v3
  poll-nws-cap-v1-minutely
  poll-geomag-kp-v1
  poll-solarwind-v1
  poll-donki-v1
  poll-astro-daily-v1
  poll-astro-daily-v1-daily
  fusion-publisher-aoi-v1
)

PUBSUB_TOPICS=( fusion.hypotheses )
BQ_DATASETS=( sentinel_raw sentinel_derived astro_raw astro_derived sentinel_mart sentinel_fusion )

declare -A BQ_TABLES
BQ_TABLES["sentinel_raw.usgs_quakes_raw_v2"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_raw.usgs_quakes_raw_v2\` WHERE time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"
BQ_TABLES["sentinel_raw.cap_alerts_raw"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_raw.cap_alerts_raw\` WHERE sent >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"
BQ_TABLES["sentinel_raw.geomag_indices"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_raw.geomag_indices\` WHERE ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"
BQ_TABLES["sentinel_raw.solar_wind"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_raw.solar_wind\` WHERE ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"
BQ_TABLES["sentinel_raw.solar_events"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_raw.solar_events\` WHERE start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)"
BQ_TABLES["astro_raw.daily"]="SELECT COUNT(*) AS c FROM \`$PROJECT.astro_raw.daily\` WHERE date_utc >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
BQ_TABLES["sentinel_mart.fusion_signals_panel_safe_v2"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_mart.fusion_signals_panel_safe_v2\` WHERE snapshot_ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)"
BQ_TABLES["sentinel_mart.fusion_aoi_confidence_24h_v2"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_mart.fusion_aoi_confidence_24h_v2\`"
BQ_TABLES["sentinel_mart.fusion_hypotheses_aoi_view_v2"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_mart.fusion_hypotheses_aoi_view_v2\`"
BQ_TABLES["sentinel_fusion.fusion_hypotheses_ingest"]="SELECT COUNT(*) AS c FROM \`$PROJECT.sentinel_fusion.fusion_hypotheses_ingest\` WHERE received_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"

hdr(){ printf "\n================================================================================\n%s\n================================================================================\n" "$1"; }
sub(){ printf "\n-- %s --\n" "$1"; }
warn(){ printf "⚠️  %s\n" "$1"; }

bq_count(){
  local sql="$1"
  bq --use_google_auth=true query --nouse_legacy_sql --format=json "$sql" 2>/dev/null | python3 - <<'PY'
import sys, json
data=sys.stdin.read().strip()
rows=json.loads(data) if data else []
print(rows[0].get('c',0) if rows else 0)
PY
}

hdr "Project Sentinel — Fusion Core Status @ $NOW_UTC"
echo "Project: $PROJECT"
echo "Region : $REGION"

# Identity
sub "Active identity & project"
gcloud auth list --filter=status:ACTIVE
gcloud config list --format='text(core.project,core.account)'

# Cloud Run
hdr "Cloud Run services"
gcloud run services list --region "$REGION" --project "$PROJECT" \
  --format='table(metadata.name,status.url,status.conditions[?type=Ready].status:label=READY)'

for svc in "${RUN_SERVICES[@]}"; do
  sub "Describe: $svc"
  if gcloud run services describe "$svc" --region "$REGION" --project "$PROJECT" --format='value(metadata.name)' >/dev/null 2>&1; then
    gcloud run services describe "$svc" --region "$REGION" --project "$PROJECT" \
      --format='value(metadata.name,status.url,status.latestReadyRevisionName,status.conditions[?type=Ready].status)'
  else
    warn "Service not found: $svc"
  fi
done

# Scheduler
hdr "Cloud Scheduler jobs (location=$REGION)"
gcloud scheduler jobs list --location="$REGION" --project "$PROJECT" \
  --format='table(ID, SCHEDULE, TARGET_TYPE, STATE)'

for job in "${SCHEDULER_JOBS[@]}"; do
  sub "Describe: $job"
  if gcloud scheduler jobs describe "$job" --location="$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud scheduler jobs describe "$job" --location="$REGION" --project "$PROJECT" \
      --format='value(name,schedule,state,attemptDeadline,timeZone,userUpdateTime)'
  else
    warn "Job not found: $job"
  fi
done

# Pub/Sub
hdr "Pub/Sub topics"
gcloud pubsub topics list --project "$PROJECT" --format='table(name)'

for t in "${PUBSUB_TOPICS[@]}"; do
  sub "Topic & subscriptions: $t"
  if gcloud pubsub topics describe "$t" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud pubsub topics list-subscriptions "$t" --project "$PROJECT" --format='table(name)'
  else
    warn "Topic not found: $t"
  fi
done

# BigQuery datasets
hdr "BigQuery datasets"
bq --use_google_auth=true ls --project_id="$PROJECT" || true
for ds in "${BQ_DATASETS[@]}"; do
  if bq --use_google_auth=true ls --project_id="$PROJECT" | awk '{print $1}' | grep -qx "$ds"; then
    :
  else
    warn "Dataset missing: $ds"
  fi
done

# BigQuery tables/views counts
hdr "BigQuery key tables/views — counts"
for fq in "${!BQ_TABLES[@]}"; do
  sub "$fq"
  if bq --use_google_auth=true show --format=none "$PROJECT:$fq" >/dev/null 2>&1; then
    cnt="$(bq_count "${BQ_TABLES[$fq]}")"
    echo "Rows (filtered): $cnt"
  else
    warn "Not found: $PROJECT:$fq"
  fi
done

# Samples
hdr "Recent samples"
sub "Latest quakes (5)"
bq --use_google_auth=true query --nouse_legacy_sql \
"SELECT time, mag, place, lon, lat FROM \`$PROJECT.sentinel_raw.usgs_quakes_raw_v2\` ORDER BY time DESC LIMIT 5" || true

sub "Latest solar events (10)"
bq --use_google_auth=true query --nouse_legacy_sql \
"SELECT event_type, class, start_time FROM \`$PROJECT.sentinel_raw.solar_events\` ORDER BY ingested_at DESC LIMIT 10" || true

sub "Astro index (5)"
bq --use_google_auth=true query --nouse_legacy_sql \
"SELECT date_utc, phase_factor_0_1, flare_mx_count_24h, cme_count_24h, astro_index_0_1 FROM \`$PROJECT.astro_derived.astro_daily_index\` ORDER BY date_utc DESC LIMIT 5" || true

sub "AOI confidence (top 10)"
bq --use_google_auth=true query --nouse_legacy_sql \
"SELECT lat_deg, lon_deg, final_confidence_0_100, quake_count, max_mag, kp_factor, bz_south_factor, sw_speed_factor, astro_index_0_1 FROM \`$PROJECT.sentinel_mart.fusion_aoi_confidence_24h_v2\` ORDER BY final_confidence_0_100 DESC LIMIT 10" || true

sub "Latest fused hypotheses (20)"
bq --use_google_auth=true query --nouse_legacy_sql \
"SELECT received_at, JSON_VALUE(payload, '$.headline') AS headline, JSON_VALUE(payload, '$.attrs.astro_index_0_1') AS astro_idx FROM \`$PROJECT.sentinel_fusion.fusion_hypotheses_ingest\` ORDER BY received_at DESC LIMIT 20" || true

hdr "Done."
