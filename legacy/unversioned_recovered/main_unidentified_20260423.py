"""
Project Sentinel — HAC Stratified Superposed Epoch Analysis
GCP Project: synexis-project-sentinel
Amendment #3 §4.2: Added --scs-weighted flag for SCS-weighted secondary outcome.

Usage:
  python main.py [--scs-weighted] [--output-table DATASET.TABLE] [--dry-run]

Flags:
  --scs-weighted     Use SCS weights (from sentinel_analysis.scs_weights) in
                     superposed epoch analysis. Secondary exploratory outcome
                     per Amendment #3 §4.2. Unweighted run always executes
                     first as primary outcome.
  --output-table     BigQuery destination for results. Default:
                     sentinel_analysis.epoch_results
  --dry-run          Build queries and print them; do not execute against BQ.
  --magnitude-min    Minimum event magnitude for ground truth filter (default: 6.0)
  --hazard-type      Comma-separated hazard types to include. Default: all.
                     Options: Earthquake,Flood,Volcanic,Avalanche,Landslide,Tsunami
  --window-days      Half-window for epoch analysis in days (default: 7)
  --walk-forward     Use walk-forward validation (Amendment #1 protocol).
                     Required for H1-WF; optional for exploratory runs.
"""

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
from typing import Optional

from google.cloud import bigquery

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT      = "synexis-project-sentinel"
DATASET_HAC  = "hac_intake"
DATASET_GT   = "sentinel_groundtruth"
DATASET_ANA  = "sentinel_analysis"

TABLE_NORMALIZED   = f"{PROJECT}.{DATASET_HAC}.hac_normalized"
TABLE_FEATURES     = f"{PROJECT}.{DATASET_HAC}.hac_features_daily"
TABLE_ENRICHMENT   = f"{PROJECT}.{DATASET_HAC}.hac_enrichment"
TABLE_EVENTS       = f"{PROJECT}.{DATASET_GT}.events"
TABLE_SCS_WEIGHTS  = f"{PROJECT}.{DATASET_ANA}.scs_weights"   # Amendment #3 §4.2
TABLE_RESULTS_DEF  = f"{PROJECT}.{DATASET_ANA}.epoch_results"

HAZARD_TYPES_ALL   = ["Earthquake", "Flood", "Volcanic", "Avalanche", "Landslide", "Tsunami"]
EPOCH_DAYS_DEF     = 7      # ± window
MAGNITUDE_MIN_DEF  = 6.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="HAC Stratified Superposed Epoch Analysis")
    p.add_argument("--scs-weighted", action="store_true",
                   help="Run SCS-weighted analysis as secondary exploratory outcome "
                        "(Amendment #3 §4.2). Unweighted run always executes first.")
    p.add_argument("--output-table", default=TABLE_RESULTS_DEF,
                   help=f"BigQuery destination table. Default: {TABLE_RESULTS_DEF}")
    p.add_argument("--dry-run", action="store_true",
                   help="Print queries without executing.")
    p.add_argument("--magnitude-min", type=float, default=MAGNITUDE_MIN_DEF,
                   help=f"Minimum event magnitude. Default: {MAGNITUDE_MIN_DEF}")
    p.add_argument("--hazard-type", default=None,
                   help="Comma-separated hazard types. Default: all.")
    p.add_argument("--window-days", type=int, default=EPOCH_DAYS_DEF,
                   help=f"Epoch half-window in days. Default: {EPOCH_DAYS_DEF}")
    p.add_argument("--walk-forward", action="store_true",
                   help="Use walk-forward validation protocol (Amendment #1).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# BigQuery helpers
# ---------------------------------------------------------------------------

def bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT)


def run_query(client: bigquery.Client, sql: str, dry_run: bool = False,
              label: str = "") -> Optional[list]:
    if dry_run:
        log.info(f"[DRY RUN] {label}\n{sql}\n")
        return None
    log.info(f"Running query: {label}")
    job = client.query(sql)
    rows = list(job.result())
    log.info(f"  → {len(rows)} rows returned")
    return rows


# ---------------------------------------------------------------------------
# Core: epoch window query (unweighted)
# ---------------------------------------------------------------------------

def build_epoch_query_unweighted(
    hazard_types: list[str],
    magnitude_min: float,
    window_days: int,
    walk_forward: bool,
) -> str:
    """
    Primary outcome: simple mean z-score across all HAC records in each
    day-lag bucket relative to qualifying events.
    Walk-forward split: training window = all events before the held-out year.
    """
    hazard_list = ", ".join(f"'{h}'" for h in hazard_types)

    walk_forward_filter = ""
    if walk_forward:
        # Amendment #1: exclude training-period records from test evaluation
        walk_forward_filter = """
        AND EXTRACT(YEAR FROM e.event_date) >= (
            SELECT MAX(EXTRACT(YEAR FROM event_date)) - 1
            FROM `{TABLE_EVENTS}`
            WHERE magnitude >= {magnitude_min}
              AND event_type IN ({hazard_list})
        )""".format(
            TABLE_EVENTS=TABLE_EVENTS,
            magnitude_min=magnitude_min,
            hazard_list=hazard_list,
        )

    return f"""
-- HAC Stratified Superposed Epoch Analysis (UNWEIGHTED — Primary Outcome)
-- Window: ±{window_days} days | Magnitude ≥ {magnitude_min} | Types: {', '.join(hazard_types)}
WITH qualifying_events AS (
  SELECT
    event_id,
    event_type,
    event_date,
    magnitude,
    lat,
    lon
  FROM `{TABLE_EVENTS}`
  WHERE magnitude >= {magnitude_min}
    AND event_type IN ({hazard_list})
    {walk_forward_filter}
),

-- For each event, collect HAC daily z-scores in the ±window
epoch_pairs AS (
  SELECT
    e.event_id,
    e.event_type,
    e.magnitude,
    f.feature_date,
    DATE_DIFF(f.feature_date, e.event_date, DAY) AS day_lag,
    f.feature_name,
    f.z_score
  FROM qualifying_events e
  CROSS JOIN `{TABLE_FEATURES}` f
  WHERE DATE_DIFF(f.feature_date, e.event_date, DAY)
        BETWEEN -{window_days} AND {window_days}
),

-- Aggregate: mean z-score per day_lag × feature_name × hazard_type
aggregated AS (
  SELECT
    event_type                         AS hazard_type,
    feature_name,
    day_lag,
    COUNT(*)                           AS n_obs,
    AVG(z_score)                       AS mean_z,
    STDDEV(z_score)                    AS std_z,
    AVG(z_score) / NULLIF(
      STDDEV(z_score) / SQRT(COUNT(*)), 0
    )                                  AS t_stat,
    FALSE                              AS scs_weighted,
    1.0                                AS mean_weight,
    CURRENT_TIMESTAMP()                AS run_at,
    '{datetime.now(timezone.utc).isoformat()}'  AS run_id
  FROM epoch_pairs
  GROUP BY hazard_type, feature_name, day_lag
)

SELECT * FROM aggregated
ORDER BY hazard_type, feature_name, day_lag;
"""


# ---------------------------------------------------------------------------
# Core: epoch window query (SCS-weighted) — Amendment #3 §4.2
# ---------------------------------------------------------------------------

def build_epoch_query_scs_weighted(
    hazard_types: list[str],
    magnitude_min: float,
    window_days: int,
    walk_forward: bool,
) -> str:
    """
    Secondary exploratory outcome: weighted mean z-score using SCS weights
    from sentinel_analysis.scs_weights. Records with no geocode get weight=1.0
    (neutral baseline). Weight rules per Amendment #3 §4.2:
      no_geo        → 1.0
      far_field     → 0.5  (> 5000 km)
      mid_field     → 1.0  (2000–5000 km)
      near_field    → 1.5  (≤ 2000 km)
      same_region   → 2.0
    """
    hazard_list = ", ".join(f"'{h}'" for h in hazard_types)

    walk_forward_filter = ""
    if walk_forward:
        walk_forward_filter = f"""
        AND EXTRACT(YEAR FROM e.event_date) >= (
            SELECT MAX(EXTRACT(YEAR FROM event_date)) - 1
            FROM `{TABLE_EVENTS}`
            WHERE magnitude >= {magnitude_min}
              AND event_type IN ({hazard_list})
        )"""

    return f"""
-- HAC Stratified Superposed Epoch Analysis (SCS-WEIGHTED — Secondary Exploratory Outcome)
-- Amendment #3 §4.2
-- Window: ±{window_days} days | Magnitude ≥ {magnitude_min} | Types: {', '.join(hazard_types)}
WITH qualifying_events AS (
  SELECT
    event_id,
    event_type,
    event_date,
    magnitude,
    lat,
    lon,
    tectonic_region
  FROM `{TABLE_EVENTS}`
  WHERE magnitude >= {magnitude_min}
    AND event_type IN ({hazard_list})
    {walk_forward_filter}
),

-- Attach SCS weight to each HAC record (pre-computed in sentinel_analysis.scs_weights)
hac_with_weights AS (
  SELECT
    f.submission_id,
    f.feature_date,
    f.feature_name,
    f.z_score,
    COALESCE(w.scs_weight, 1.0) AS scs_weight,  -- default neutral if missing
    COALESCE(w.weight_tier, 'no_geocode')        AS weight_tier
  FROM `{TABLE_FEATURES}` f
  LEFT JOIN `{TABLE_SCS_WEIGHTS}` w
    ON f.submission_id = w.submission_id
),

-- Epoch pairs with weights
epoch_pairs AS (
  SELECT
    e.event_id,
    e.event_type,
    e.magnitude,
    h.feature_date,
    DATE_DIFF(h.feature_date, e.event_date, DAY) AS day_lag,
    h.feature_name,
    h.z_score,
    h.scs_weight,
    h.weight_tier
  FROM qualifying_events e
  CROSS JOIN hac_with_weights h
  WHERE DATE_DIFF(h.feature_date, e.event_date, DAY)
        BETWEEN -{window_days} AND {window_days}
),

-- Weighted mean: Σ(w_i * z_i) / Σ(w_i)
-- Weighted variance for t-stat: use Heckman weighted SE approximation
aggregated AS (
  SELECT
    event_type                                     AS hazard_type,
    feature_name,
    day_lag,
    COUNT(*)                                       AS n_obs,
    -- Weighted mean z-score
    SAFE_DIVIDE(
      SUM(scs_weight * z_score),
      SUM(scs_weight)
    )                                              AS mean_z,
    -- Weighted std (population approximation for t-stat denominator)
    SQRT(
      SAFE_DIVIDE(
        SUM(scs_weight * POW(z_score - SAFE_DIVIDE(
          SUM(scs_weight * z_score) OVER (
            PARTITION BY event_type, feature_name, day_lag),
          SUM(scs_weight) OVER (
            PARTITION BY event_type, feature_name, day_lag)
          ), 2)),
        SUM(scs_weight)
      )
    )                                              AS std_z,
    -- Effective N for weighted SE (Kish approximation)
    POW(SUM(scs_weight), 2)
      / NULLIF(SUM(POW(scs_weight, 2)), 0)        AS n_eff,
    AVG(scs_weight)                                AS mean_weight,
    TRUE                                           AS scs_weighted,
    CURRENT_TIMESTAMP()                            AS run_at,
    '{datetime.now(timezone.utc).isoformat()}'     AS run_id
  FROM epoch_pairs
  GROUP BY hazard_type, feature_name, day_lag
),

-- T-stat using effective N
with_tstat AS (
  SELECT
    *,
    SAFE_DIVIDE(mean_z,
      SAFE_DIVIDE(std_z, SQRT(NULLIF(n_eff, 0)))
    )                                              AS t_stat
  FROM aggregated
)

SELECT * FROM with_tstat
ORDER BY hazard_type, feature_name, day_lag;
"""


# ---------------------------------------------------------------------------
# Result writer
# ---------------------------------------------------------------------------

def write_results(
    client: bigquery.Client,
    rows: list,
    output_table: str,
    scs_weighted: bool,
    dry_run: bool,
):
    if dry_run or not rows:
        return

    run_label = "scs_weighted" if scs_weighted else "unweighted"
    log.info(f"Writing {len(rows)} rows to {output_table} [{run_label}]")

    # Append results (do not overwrite — both weighted and unweighted land here)
    job_config = bigquery.QueryJobConfig(
        destination=output_table,
        write_disposition="WRITE_APPEND",
        create_disposition="CREATE_IF_NEEDED",
    )

    # Rows are already BigQuery Row objects; re-insert via JSON
    records = [dict(r) for r in rows]

    # Serialize datetimes
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, datetime):
                rec[k] = v.isoformat()

    errors = client.insert_rows_json(output_table, records)
    if errors:
        log.error(f"BigQuery insert errors: {errors}")
        raise RuntimeError("Failed to write results to BigQuery")
    log.info("Write complete.")


# ---------------------------------------------------------------------------
# SCS weight sanity check
# ---------------------------------------------------------------------------

def verify_scs_weights(client: bigquery.Client, dry_run: bool) -> bool:
    """
    Pre-flight check: confirm sentinel_analysis.scs_weights exists and
    has non-zero rows before running weighted analysis.
    Returns True if weights are usable.
    """
    sql = f"""
    SELECT
      COUNT(*) AS n,
      COUNTIF(scs_weight IS NULL) AS null_weights,
      AVG(scs_weight) AS mean_weight
    FROM `{TABLE_SCS_WEIGHTS}`
    """
    if dry_run:
        log.info("[DRY RUN] Would verify SCS weight table exists and is populated.")
        return True

    try:
        rows = run_query(client, sql, dry_run=False, label="SCS weight verification")
        r = rows[0]
        n = r["n"]
        null_w = r["null_weights"]
        mean_w = r["mean_weight"]
        log.info(f"SCS weights: {n} rows, {null_w} null, mean_weight={mean_w:.4f}")
        if n == 0:
            log.error("scs_weights table is empty — run build_scs_weights.sql first.")
            return False
        return True
    except Exception as ex:
        log.error(f"SCS weight verification failed: {ex}")
        log.error("Ensure sentinel_analysis.scs_weights exists. "
                  "Run build_scs_weights.sql to populate it.")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    hazard_types = (
        [h.strip() for h in args.hazard_type.split(",")]
        if args.hazard_type
        else HAZARD_TYPES_ALL
    )

    log.info("=== HAC Stratified Epoch Analysis ===")
    log.info(f"  Hazard types   : {hazard_types}")
    log.info(f"  Magnitude min  : {args.magnitude_min}")
    log.info(f"  Window days    : ±{args.window_days}")
    log.info(f"  Walk-forward   : {args.walk_forward}")
    log.info(f"  SCS-weighted   : {args.scs_weighted}")
    log.info(f"  Output table   : {args.output_table}")
    log.info(f"  Dry run        : {args.dry_run}")

    client = bq_client() if not args.dry_run else None

    # -----------------------------------------------------------------------
    # Run 1 (always): Unweighted — Primary Outcome
    # -----------------------------------------------------------------------
    log.info("\n--- Run 1/2: UNWEIGHTED (Primary Outcome) ---")
    sql_unweighted = build_epoch_query_unweighted(
        hazard_types=hazard_types,
        magnitude_min=args.magnitude_min,
        window_days=args.window_days,
        walk_forward=args.walk_forward,
    )
    rows_unweighted = run_query(
        client, sql_unweighted, dry_run=args.dry_run,
        label="Unweighted epoch analysis"
    )
    if not args.dry_run and rows_unweighted:
        write_results(client, rows_unweighted, args.output_table,
                      scs_weighted=False, dry_run=args.dry_run)
        log.info(f"Unweighted: {len(rows_unweighted)} result rows written.")

    # -----------------------------------------------------------------------
    # Run 2 (conditional): SCS-Weighted — Secondary Exploratory Outcome
    # -----------------------------------------------------------------------
    if args.scs_weighted:
        log.info("\n--- Run 2/2: SCS-WEIGHTED (Secondary Exploratory Outcome — Amendment #3 §4.2) ---")

        # Pre-flight: verify weight table exists
        weights_ok = verify_scs_weights(client, dry_run=args.dry_run)
        if not weights_ok:
            log.error("Aborting SCS-weighted run due to missing/empty weight table.")
            sys.exit(1)

        sql_weighted = build_epoch_query_scs_weighted(
            hazard_types=hazard_types,
            magnitude_min=args.magnitude_min,
            window_days=args.window_days,
            walk_forward=args.walk_forward,
        )
        rows_weighted = run_query(
            client, sql_weighted, dry_run=args.dry_run,
            label="SCS-weighted epoch analysis"
        )
        if not args.dry_run and rows_weighted:
            write_results(client, rows_weighted, args.output_table,
                          scs_weighted=True, dry_run=args.dry_run)
            log.info(f"SCS-weighted: {len(rows_weighted)} result rows written.")
    else:
        log.info("\n[Skipped] SCS-weighted run not requested. "
                 "Add --scs-weighted flag to run secondary outcome.")

    log.info("\n=== Analysis complete ===")


if __name__ == "__main__":
    main()
