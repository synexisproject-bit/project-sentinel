#!/bin/bash
# d9_startup.sh
#
# Compute Engine startup script for the Project Sentinel D9 magnitude of
# completeness analysis. Runs unattended, checkpoints each stage to GCS as it
# finishes, and stops the instance when done.
#
# Cloud Shell cannot host this job: its VM terminates after about 20 minutes of
# session inactivity, which kills nohup'd work. This runs on a dedicated
# instance instead.
#
# Everything the run needs comes from GCS, and everything it produces goes back
# there, so the instance holds no state worth keeping and can be deleted.

set -uo pipefail

BUCKET="gs://synexis-project-sentinel-exports-central1/d9"
WORK="/opt/d9"
LOG="$WORK/d9_run.log"

mkdir -p "$WORK/results"
cd "$WORK" || exit 1

# Mirror the log to GCS every 60 seconds so progress is visible without SSH.
(
  while true; do
    sleep 60
    gsutil -q cp "$LOG" "$BUCKET/run/d9_run.log" 2>/dev/null
    gsutil -q -m rsync -r "$WORK/results" "$BUCKET/run/results" 2>/dev/null
  done
) &
MIRROR=$!

{
  echo "=== D9 run starting $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  echo "instance: $(hostname)   cores: $(nproc)   mem: $(free -g | awk '/^Mem:/{print $2}')GB"

  echo "--- installing dependencies ---"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3-pip python3-venv >/dev/null
  pip3 install --quiet --break-system-packages \
      "seismostats==1.0.1" pandas scipy numpy
  python3 -c "import seismostats, pandas, scipy, numpy; \
print('seismostats', seismostats.__version__)"

  echo "--- fetching inputs ---"
  gsutil cp "$BUCKET/estimate_mc_d9.py" .
  gsutil cp "$BUCKET/jma_mc_working_catalog.csv" .
  sha256sum estimate_mc_d9.py jma_mc_working_catalog.csv

  echo "--- running ---"
  # The script verifies the catalog hash against the registered value and
  # refuses to run on anything else. Each stage checkpoints independently, so a
  # failure costs one stage rather than the run.
  python3 -u estimate_mc_d9.py \
      --catalog jma_mc_working_catalog.csv \
      --out results \
      --workers "$(nproc)"
  RC=$?
  echo "--- estimator exited with $RC ---"

  echo "--- uploading results ---"
  gsutil -m cp -r results/* "$BUCKET/results/"
  echo "=== D9 run finished $(date -u +%Y-%m-%dT%H:%M:%SZ), rc=$RC ==="
} 2>&1 | tee -a "$LOG"

kill $MIRROR 2>/dev/null
gsutil -q cp "$LOG" "$BUCKET/results/d9_run.log"

# Stop rather than delete, so the log and any partial state survive inspection.
# Delete the instance by hand once the results are confirmed.
shutdown -h now
