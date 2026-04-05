#!/usr/bin/env python3
"""
Cloud Run Job wrapper for H3 Regional TEC Backfill.
Runs h3_01_backfill_regional_tec.py as a Cloud Run job.

Deploy:
    gcloud builds submit --tag gcr.io/synexis-project-sentinel/h3-tec-backfill
    gcloud run jobs create h3-tec-backfill \
        --image gcr.io/synexis-project-sentinel/h3-tec-backfill \
        --region us-central1 \
        --memory 2Gi \
        --task-timeout 86400 \
        --max-retries 1

Execute:
    gcloud run jobs execute h3-tec-backfill --region us-central1 --wait
"""

import os
import subprocess
import sys

START_YEAR = os.environ.get("START_YEAR", "2001")
END_YEAR   = os.environ.get("END_YEAR",   "2025")
BATCH_SIZE = os.environ.get("BATCH_SIZE", "100")

if __name__ == "__main__":
    cmd = [
        sys.executable, "h3_01_backfill_regional_tec.py",
        "--start-year", START_YEAR,
        "--end-year",   END_YEAR,
        "--batch-size", BATCH_SIZE,
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)
