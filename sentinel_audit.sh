#!/usr/bin/env bash
#
# Project Sentinel / Synexis Field Observatory — Infrastructure Audit
#
# SENTINEL WORKFLOW RULE: run at the START and END of every major
# workflow milestone. Catches idle resources, region drift, missing
# tables, and ingest jobs that have silently stopped running.
#
# Usage:
#   bash sentinel_audit.sh                       # audits both projects
#   bash sentinel_audit.sh synexis-project-sentinel
#   bash sentinel_audit.sh synexis-sfo
#
# Optional: export BILLING_EXPORT_TABLE=project.dataset.table to include
# month-to-date cost. Configure the export at
# Billing > Billing export > BigQuery export.
#
# Revision history:
#   2026-09-05  Scheduler region corrected us-east1 -> multi-region scan.
#               BQ table paths corrected to *_central1 datasets.
#               Added bucket and dataset location checks.
#               Added multi-project support and stale-job detection.
#               Added findings summary.
#   2026-09-06  Artifact Registry location fixed. The API returns no
#               top-level `location` field, so v1 printed blanks and the
#               off-region check silently passed. Location is now parsed
#               from the resource name path segment.
#               Added in-progress execution detection so a running job
#               is not reported as FAILED.
#               ENABLED schedulers now raise a finding, since an enabled
#               schedule firing into a failing job is the failure mode
#               that went unseen for two months.

set -uo pipefail

EXPECTED_LOCATION="us-central1"
SCHEDULER_REGIONS=(us-central1 us-east1 us-east4)
STALE_DAYS=7

PROJECTS=("$@")
if [ ${#PROJECTS[@]} -eq 0 ]; then
  PROJECTS=(synexis-project-sentinel synexis-sfo)
fi

declare -A CRITICAL_TABLES
CRITICAL_TABLES[synexis-project-sentinel]="sentinel_analysis_central1.hac_features_daily sentinel_analysis_central1.epoch_results_pathB sentinel_analysis_central1.precog_match_candidates"
CRITICAL_TABLES[synexis-sfo]=""

FINDINGS=()

note()  { FINDINGS+=("$1"); }
head1() { printf '\n===============================================\n %s\n===============================================\n' "$1"; }
head2() { printf '\n--- %s ---\n' "$1"; }

lower() { tr '[:upper:]' '[:lower:]'; }

epoch_of() {
  date -u -d "$1" +%s 2>/dev/null || true
}

printf '===============================================\n'
printf ' SENTINEL INFRASTRUCTURE AUDIT\n'
printf ' %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf ' Projects: %s\n' "${PROJECTS[*]}"
printf ' Expected location: %s\n' "$EXPECTED_LOCATION"
printf '===============================================\n'

for P in "${PROJECTS[@]}"; do

  head1 "PROJECT: $P"

  # ---------------------------------------------------------------
  head2 "Compute VMs (idle cost risk)"
  gcloud compute instances list --project="$P" \
    --format="table(name,zone,machineType.basename(),status)" 2>/dev/null \
    || echo "  (unable to list)"

  VM_COUNT=$(gcloud compute instances list --project="$P" \
    --format="value(name)" 2>/dev/null | wc -l)
  [ "$VM_COUNT" -gt 0 ] && note "$P: $VM_COUNT compute VM(s) present — confirm each is needed"

  # ---------------------------------------------------------------
  head2 "Persistent disks (orphan risk)"
  gcloud compute disks list --project="$P" \
    --format="table(name,zone,sizeGb,status,users.basename())" 2>/dev/null \
    || echo "  (unable to list)"

  ORPHANS=$(gcloud compute disks list --project="$P" \
    --filter="-users:*" --format="value(name)" 2>/dev/null | wc -l)
  [ "$ORPHANS" -gt 0 ] && note "$P: $ORPHANS orphaned disk(s) with no attached instance"

  # ---------------------------------------------------------------
  head2 "Cloud SQL instances"
  gcloud sql instances list --project="$P" 2>/dev/null || echo "  (none)"

  SQL_COUNT=$(gcloud sql instances list --project="$P" \
    --format="value(name)" 2>/dev/null | wc -l)
  [ "$SQL_COUNT" -gt 0 ] && note "$P: $SQL_COUNT Cloud SQL instance(s) present — these bill continuously"

  # ---------------------------------------------------------------
  head2 "Cloud Run services (all regions)"
  gcloud run services list --project="$P" 2>/dev/null || echo "  (none)"

  OFF_REGION_SVC=$(gcloud run services list --project="$P" \
    --format="value(metadata.labels['cloud.googleapis.com/location'])" 2>/dev/null \
    | lower | grep -v "^${EXPECTED_LOCATION}$" | grep -c . || true)
  [ "${OFF_REGION_SVC:-0}" -gt 0 ] && \
    note "$P: $OFF_REGION_SVC Cloud Run service(s) outside $EXPECTED_LOCATION"

  # ---------------------------------------------------------------
  head2 "Cloud Run jobs (all regions)"
  gcloud run jobs list --project="$P" 2>/dev/null || echo "  (none)"

  # ---------------------------------------------------------------
  head2 "Cloud Run job execution health"
  NOW=$(date -u +%s)
  JOBS_SEEN=0
  while IFS=$'\t' read -r JNAME JLOC; do
    [ -z "${JNAME:-}" ] && continue
    JOBS_SEEN=$((JOBS_SEEN + 1))
    if [ -z "${JLOC:-}" ]; then
      echo "  $JNAME: region unresolved, execution health NOT VERIFIED"
      note "$P: could not resolve region for job $JNAME — execution health unverified"
      continue
    fi

    EXEC=$(gcloud run jobs executions list --job="$JNAME" \
      --region="$JLOC" --project="$P" --limit=1 \
      --format="value(metadata.name,status.succeededCount,status.runningCount,metadata.creationTimestamp)" \
      2>/dev/null)

    if [ -z "$EXEC" ]; then
      echo "  $JNAME ($JLOC): NEVER RUN"
      note "$P: job $JNAME has never been executed"
      continue
    fi

    EXNAME=$(echo "$EXEC" | cut -f1)
    SUCCEEDED=$(echo "$EXEC" | cut -f2)
    RUNNING=$(echo "$EXEC" | cut -f3)
    CREATED=$(echo "$EXEC" | cut -f4)

    if [ -n "${RUNNING:-}" ] && [ "${RUNNING:-0}" -gt 0 ] 2>/dev/null; then
      echo "  $JNAME ($JLOC): execution $EXNAME currently RUNNING"
      continue
    fi

    if [ -z "${SUCCEEDED:-}" ] || [ "${SUCCEEDED:-0}" -eq 0 ] 2>/dev/null; then
      echo "  $JNAME ($JLOC): latest execution $EXNAME has 0 successful tasks — FAILED"
      note "$P: job $JNAME latest execution failed (0 succeeded)"
      continue
    fi

    CREATED_EPOCH=$(epoch_of "$CREATED")
    if [ -n "$CREATED_EPOCH" ]; then
      AGE_DAYS=$(( (NOW - CREATED_EPOCH) / 86400 ))
      if [ "$AGE_DAYS" -gt "$STALE_DAYS" ]; then
        echo "  $JNAME ($JLOC): last successful run ${AGE_DAYS}d ago — STALE"
        note "$P: job $JNAME last ran ${AGE_DAYS} days ago (threshold ${STALE_DAYS}d)"
      else
        echo "  $JNAME ($JLOC): OK, last run ${AGE_DAYS}d ago"
      fi
    else
      echo "  $JNAME ($JLOC): OK, timestamp unparsed"
    fi
  done < <(gcloud run jobs list --project="$P" \
      --format="value(metadata.name,metadata.labels['cloud.googleapis.com/location'])" \
      2>/dev/null)

  [ "$JOBS_SEEN" -eq 0 ] && echo "  (no Cloud Run jobs)"

  # ---------------------------------------------------------------
  head2 "Cloud Scheduler jobs (scanning ${SCHEDULER_REGIONS[*]})"
  SCHED_TOTAL=0
  for R in "${SCHEDULER_REGIONS[@]}"; do
    OUT=$(gcloud scheduler jobs list --project="$P" --location="$R" \
      --format="value(name.basename(),state,schedule)" 2>/dev/null)
    if [ -n "$OUT" ]; then
      echo "  [$R]"
      echo "$OUT" | sed 's/^/    /'
      COUNT=$(echo "$OUT" | grep -c .)
      SCHED_TOTAL=$((SCHED_TOTAL + COUNT))
      ENABLED_CT=$(echo "$OUT" | grep -c "ENABLED" || true)
      [ "${ENABLED_CT:-0}" -gt 0 ] && \
        note "$P: $ENABLED_CT ENABLED scheduler(s) in $R — confirm their target jobs are succeeding"
    fi
  done
  [ "$SCHED_TOTAL" -eq 0 ] && echo "  (none found in scanned regions)"

  # ---------------------------------------------------------------
  head2 "GCS buckets and locations"
  while IFS=$'\t' read -r BNAME BLOC; do
    [ -z "${BNAME:-}" ] && continue
    BLOC_LC=$(echo "$BLOC" | lower)
    if [ "$BLOC_LC" != "$EXPECTED_LOCATION" ]; then
      echo "  $BNAME  [$BLOC]  <-- OFF-REGION"
      note "$P: bucket $BNAME is in $BLOC, expected $EXPECTED_LOCATION"
    else
      echo "  $BNAME  [$BLOC]"
    fi
  done < <(gcloud storage buckets list --project="$P" \
      --format="value(name,location)" 2>/dev/null)

  # ---------------------------------------------------------------
  head2 "BigQuery datasets and locations"
  DATASETS=$(bq ls --project_id="$P" --format=json 2>/dev/null \
    | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
except Exception:
    d=[]
for x in d:
    print(x['datasetReference']['datasetId'])" 2>/dev/null)

  if [ -z "$DATASETS" ]; then
    echo "  (none)"
  else
    for D in $DATASETS; do
      DLOC=$(bq show --project_id="$P" --format=json "$D" 2>/dev/null \
        | python3 -c "import sys,json
try:
    print(json.load(sys.stdin).get('location',''))
except Exception:
    print('')" 2>/dev/null | lower)
      if [ "$DLOC" != "$EXPECTED_LOCATION" ]; then
        echo "  $D  [${DLOC:-unknown}]  <-- OFF-REGION"
        note "$P: dataset $D is in ${DLOC:-unknown}, expected $EXPECTED_LOCATION"
      else
        echo "  $D  [$DLOC]"
      fi
    done
  fi

  # ---------------------------------------------------------------
  # Artifact Registry.
  # The list API returns no top-level `location` field. The resource
  # name is projects/<P>/locations/<LOC>/repositories/<REPO>, so the
  # location is parsed from path segment 4.
  head2 "Artifact Registry"
  AR_FOUND=0
  while IFS=$'\t' read -r ARNAME ARFMT ARSIZE; do
    [ -z "${ARNAME:-}" ] && continue
    AR_FOUND=1
    ARLOC=$(echo "$ARNAME" | cut -d/ -f4 | lower)
    ARREPO=$(echo "$ARNAME" | awk -F/ '{print $NF}')
    case "${ARSIZE:-}" in
      ''|*[!0-9]*) ARMB="?" ;;
      *)           ARMB=$(( ARSIZE / 1048576 )) ;;
    esac
    if [ "$ARLOC" != "$EXPECTED_LOCATION" ]; then
      printf '  %-34s %-8s %8s MB  [%s]  <-- OFF-REGION\n' "$ARREPO" "$ARFMT" "$ARMB" "$ARLOC"
      note "$P: Artifact Registry repo $ARREPO is in $ARLOC (${ARMB} MB), expected $EXPECTED_LOCATION"
    else
      printf '  %-34s %-8s %8s MB  [%s]\n' "$ARREPO" "$ARFMT" "$ARMB" "$ARLOC"
    fi
  done < <(gcloud artifacts repositories list --project="$P" \
      --format="value(name,format,sizeBytes)" 2>/dev/null)
  [ "$AR_FOUND" -eq 0 ] && echo "  (none)"

  # ---------------------------------------------------------------
  head2 "Critical BigQuery tables"
  TABLES="${CRITICAL_TABLES[$P]:-}"
  if [ -z "$TABLES" ]; then
    echo "  (none registered for this project)"
  else
    for T in $TABLES; do
      if bq show --project_id="$P" --quiet "${P}:${T}" >/dev/null 2>&1; then
        echo "  OK:      $T"
      else
        echo "  MISSING: $T"
        note "$P: critical table $T not found"
      fi
    done
  fi

done

# -----------------------------------------------------------------
head1 "MONTH-TO-DATE COST"
if [ -n "${BILLING_EXPORT_TABLE:-}" ]; then
  bq query --nouse_legacy_sql --format=pretty "
    SELECT project.id AS project,
           ROUND(SUM(cost), 2) AS usage_cost_usd
    FROM \`${BILLING_EXPORT_TABLE}\`
    WHERE DATE(usage_start_time) >= DATE_TRUNC(CURRENT_DATE(), MONTH)
    GROUP BY project
    ORDER BY usage_cost_usd DESC
  " 2>/dev/null || echo "  Query failed. Verify BILLING_EXPORT_TABLE."
else
  echo "  BILLING_EXPORT_TABLE not set."
  echo "  Read MTD cost from the console: Billing > Reports,"
  echo "  Group by = Project, Time range = Current month."
  echo "  To automate, enable Billing > Billing export > BigQuery export,"
  echo "  then export BILLING_EXPORT_TABLE=project.dataset.table"
fi

# -----------------------------------------------------------------
head1 "FINDINGS SUMMARY"
if [ ${#FINDINGS[@]} -eq 0 ]; then
  echo "  No findings. All checks clean."
else
  printf '  %d finding(s):\n\n' "${#FINDINGS[@]}"
  for F in "${FINDINGS[@]}"; do
    echo "  - $F"
  done
fi

printf '\n=== END AUDIT %s ===\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
