#!/bin/bash
# Sentinel GCP Resource Audit
# Run monthly or before any major infrastructure phase
# Usage: bash sentinel_audit.sh

PROJECT=synexis-project-sentinel

echo "==============================="
echo " SENTINEL GCP RESOURCE AUDIT"
echo " $(date)"
echo "==============================="

echo ""
echo "=== COMPUTE VMs ==="
gcloud compute instances list --project=$PROJECT

echo ""
echo "=== PERSISTENT DISKS ==="
gcloud compute disks list --project=$PROJECT

echo ""
echo "=== CLOUD SQL INSTANCES ==="
gcloud sql instances list --project=$PROJECT

echo ""
echo "=== CLOUD RUN SERVICES ==="
gcloud run services list --project=$PROJECT

echo ""
echo "=== CLOUD SCHEDULER JOBS ==="
gcloud scheduler jobs list --project=$PROJECT --location=us-east1

echo ""
echo "=== ARTIFACT REGISTRY ==="
gcloud artifacts repositories list --project=$PROJECT

echo ""
echo "=== BIGQUERY DATASETS ==="
bq ls --project_id=$PROJECT

echo ""
echo "==============================="
echo " Audit complete. Review above"
echo " for any unexpected resources."
echo "==============================="

# Check critical intermediate tables
echo "--- Critical BQ Tables ---"
for tbl in "sentinel_analysis.hac_features_daily" "sentinel_analysis.epoch_results_pathB" "sentinel_analysis.precog_match_candidates"; do
  result=$(bq show --quiet synexis-project-sentinel:${tbl} 2>&1)
  if echo "$result" | grep -q "Not found"; then
    echo "MISSING: ${tbl}"
  else
    echo "OK: ${tbl}"
  fi
done
