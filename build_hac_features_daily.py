#!/usr/bin/env python3
"""
build_hac_features_daily.py

Builds sentinel_features.hac_features_daily — one row per fault zone per day
spanning the HAC corpus date range, with daily HAC signal counts and intensity
metrics computed from hac_normalized + hac_enrichment.

This table mirrors h1_features_daily in structure and is designed to slot
directly into the existing Sentinel analytical framework.

Spatial assignment:
  - Records with referred_lat/lon coordinates are assigned to a fault zone
    if they fall within that fault's bounding box (from fault_systems).
  - Records without coordinates are assigned fault_id = 'global' only.
  - A record can match multiple fault zones if its coordinates fall in
    overlapping bounding boxes (unlikely given the fault definitions).

Usage:
  python3 build_hac_features_daily.py
  python3 build_hac_features_daily.py --rebuild   # drop and recreate
"""

import sys
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT_ID   = "synexis-project-sentinel"
NORMALIZED   = f"{PROJECT_ID}.hac_intake.hac_normalized"
ENRICHMENT   = f"{PROJECT_ID}.hac_intake.hac_enrichment"
FAULT_SYSTEMS = f"{PROJECT_ID}.sentinel_features.fault_systems"
H1_LABELS    = f"{PROJECT_ID}.sentinel_features.h1_labels"
OUTPUT_TABLE = f"{PROJECT_ID}.sentinel_features.hac_features_daily"

REBUILD = "--rebuild" in sys.argv

bq = bigquery.Client(project=PROJECT_ID)


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def drop_if_rebuild():
    if not REBUILD:
        return
    log("Dropping existing hac_features_daily...")
    try:
        bq.delete_table(OUTPUT_TABLE)
        log("  Dropped.")
    except Exception:
        log("  Table did not exist, continuing.")


def build_hac_features_daily():
    """
    Build hac_features_daily using a single BigQuery SQL job.

    Strategy:
      1. Generate a date spine from MIN to MAX experience_date in hac_normalized
      2. Cross join with fault_systems (plus a 'global' pseudo-fault)
      3. For each (date, fault) pair, count and aggregate HAC records that:
         a. Have referred coordinates within the fault bounding box (fault-specific)
         b. Have no coordinates (global only)
      4. Compute rolling 7d and 30d aggregates as window functions
      5. Compute z-score against 365d baseline
      6. Attach data_split from h1_labels for consistency
    """
    log("Building hac_features_daily...")

    query = f"""
    CREATE OR REPLACE TABLE `{OUTPUT_TABLE}`
    OPTIONS (description = 'Daily HAC signal features per fault zone, mirroring h1_features_daily structure. Built from hac_normalized + hac_enrichment.')
    AS

    WITH

    -- ── Date spine: all dates in HAC corpus ──────────────────────────────────
    date_spine AS (
      SELECT date_val
      FROM UNNEST(
        GENERATE_DATE_ARRAY(
          DATE '2010-01-01',
          DATE '2026-12-31'
        )
      ) AS date_val
    ),

    -- ── Fault zones including a global pseudo-zone ───────────────────────────
    fault_zones AS (
      SELECT fault_id, lat_min, lat_max, lon_min, lon_max
      FROM `{FAULT_SYSTEMS}`
      UNION ALL
      SELECT 'global' AS fault_id,
             -90.0 AS lat_min, 90.0 AS lat_max,
             -180.0 AS lon_min, 180.0 AS lon_max
    ),

    -- ── Spine x faults ───────────────────────────────────────────────────────
    spine AS (
      SELECT d.date_val, f.fault_id, f.lat_min, f.lat_max, f.lon_min, f.lon_max
      FROM date_spine d
      CROSS JOIN fault_zones f
    ),

    -- ── Enriched HAC records with spatial assignment ─────────────────────────
    hac_records AS (
      SELECT
        n.submission_id,
        n.experience_date,
        n.referred_lat_approx,
        n.referred_lon_approx,
        n.is_geophysical,
        n.llm_extracted_emotion,
        e.urgency_level,
        e.water_imagery,
        e.destruction_imagery,
        e.geophysical_imagery,
        e.scale_impression,
        -- Has valid coordinates
        (n.referred_lat_approx IS NOT NULL
         AND n.referred_lon_approx IS NOT NULL) AS has_location
      FROM `{NORMALIZED}` n
      INNER JOIN `{ENRICHMENT}` e USING (submission_id)
      WHERE n.is_geophysical = TRUE
        AND n.experience_date IS NOT NULL
        AND n.normalized_status IN ('enriched', 'fusion_ready', 'date_reliable', 'date_extracted')
      AND (n.is_duplicate IS NULL OR n.is_duplicate = FALSE)
    ),

    -- ── Assign records to fault zones ────────────────────────────────────────
    -- A located record is assigned to a specific fault if coords are in bounds.
    -- An unlocated record is assigned to 'global' only.
    -- A located record is ALSO assigned to 'global' (global = all records).
    hac_assigned AS (
      SELECT
        r.*,
        f.fault_id
      FROM hac_records r
      CROSS JOIN fault_zones f
      WHERE (
        -- Located record: assign to matching fault zones + global
        r.has_location = TRUE
        AND r.referred_lat_approx BETWEEN f.lat_min AND f.lat_max
        AND r.referred_lon_approx BETWEEN f.lon_min AND f.lon_max
      ) OR (
        -- Unlocated record: assign to global only
        r.has_location = FALSE
        AND f.fault_id = 'global'
      )
    ),

    -- ── Daily aggregates per fault ────────────────────────────────────────────
    daily_raw AS (
      SELECT
        experience_date AS date_val,
        fault_id,
        COUNT(*)                                    AS hac_count,
        COUNTIF(urgency_level = 'high')             AS hac_count_high_urgency,
        COUNTIF(urgency_level = 'medium')           AS hac_count_medium_urgency,
        COUNTIF(water_imagery = TRUE)               AS hac_count_water,
        COUNTIF(destruction_imagery = TRUE)         AS hac_count_destruction,
        COUNTIF(llm_extracted_emotion IN (
          'terror','dread','panic','horror','anguish')) AS hac_count_high_emotion,
        COUNTIF(llm_extracted_emotion IN (
          'fear','anxiety','distress','urgency'))    AS hac_count_fear_anxiety,
        COUNTIF(scale_impression IN (
          'regional','continental','global'))        AS hac_count_large_scale,
        COUNTIF(has_location = TRUE)                AS hac_count_located,
        -- Composite intensity score per record, averaged across day
        AVG(
          (CASE WHEN urgency_level = 'high'   THEN 3
                WHEN urgency_level = 'medium' THEN 2
                WHEN urgency_level = 'low'    THEN 1
                ELSE 0 END)
          + (CASE WHEN water_imagery       THEN 1 ELSE 0 END)
          + (CASE WHEN destruction_imagery THEN 1 ELSE 0 END)
          + (CASE WHEN llm_extracted_emotion IN (
              'terror','dread','panic') THEN 2
                  WHEN llm_extracted_emotion IN (
              'fear','anxiety','distress') THEN 1
                  ELSE 0 END)
        )                                           AS hac_intensity_mean
      FROM hac_assigned
      GROUP BY experience_date, fault_id
    ),

    -- ── Fill spine with zeros for days with no records ───────────────────────
    daily_filled AS (
      SELECT
        s.date_val,
        s.fault_id,
        COALESCE(d.hac_count, 0)                AS hac_count,
        COALESCE(d.hac_count_high_urgency, 0)   AS hac_count_high_urgency,
        COALESCE(d.hac_count_medium_urgency, 0) AS hac_count_medium_urgency,
        COALESCE(d.hac_count_water, 0)          AS hac_count_water,
        COALESCE(d.hac_count_destruction, 0)    AS hac_count_destruction,
        COALESCE(d.hac_count_high_emotion, 0)   AS hac_count_high_emotion,
        COALESCE(d.hac_count_fear_anxiety, 0)   AS hac_count_fear_anxiety,
        COALESCE(d.hac_count_large_scale, 0)    AS hac_count_large_scale,
        COALESCE(d.hac_count_located, 0)        AS hac_count_located,
        COALESCE(d.hac_intensity_mean, 0.0)     AS hac_intensity_mean
      FROM spine s
      LEFT JOIN daily_raw d
        ON s.date_val = d.date_val
       AND s.fault_id = d.fault_id
    ),

    -- ── Rolling windows ───────────────────────────────────────────────────────
    daily_windowed AS (
      SELECT
        *,
        -- 7-day rolling sum
        SUM(hac_count) OVER (
          PARTITION BY fault_id
          ORDER BY date_val
          ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS hac_7d_count,
        -- 30-day rolling sum
        SUM(hac_count) OVER (
          PARTITION BY fault_id
          ORDER BY date_val
          ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) AS hac_30d_count,
        -- 365-day baseline mean and std for z-scoring
        AVG(hac_count) OVER (
          PARTITION BY fault_id
          ORDER BY date_val
          ROWS BETWEEN 365 PRECEDING AND 1 PRECEDING
        ) AS hac_365d_baseline_mean,
        STDDEV(hac_count) OVER (
          PARTITION BY fault_id
          ORDER BY date_val
          ROWS BETWEEN 365 PRECEDING AND 1 PRECEDING
        ) AS hac_365d_baseline_std
      FROM daily_filled
    ),

    -- ── Z-score ───────────────────────────────────────────────────────────────
    daily_zscored AS (
      SELECT
        *,
        CASE
          WHEN hac_365d_baseline_std > 0
          THEN (hac_count - hac_365d_baseline_mean) / hac_365d_baseline_std
          ELSE NULL
        END AS hac_count_zscore
      FROM daily_windowed
    )

    -- ── Final select with data_split from h1_labels ───────────────────────────
    -- Use h1_labels data_split for fault-specific rows; NULL for global
    SELECT
      z.date_val,
      z.fault_id,
      z.hac_count,
      z.hac_count_high_urgency,
      z.hac_count_medium_urgency,
      z.hac_count_water,
      z.hac_count_destruction,
      z.hac_count_high_emotion,
      z.hac_count_fear_anxiety,
      z.hac_count_large_scale,
      z.hac_count_located,
      z.hac_intensity_mean,
      z.hac_7d_count,
      z.hac_30d_count,
      z.hac_365d_baseline_mean,
      z.hac_365d_baseline_std,
      z.hac_count_zscore,
      l.data_split
    FROM daily_zscored z
    LEFT JOIN `{H1_LABELS}` l
      ON z.date_val = l.date_val
     AND z.fault_id = l.fault_id
    ORDER BY z.fault_id, z.date_val
    """

    log("Submitting BigQuery job (this may take 1-2 minutes)...")
    job = bq.query(query)
    job.result()
    log(f"  Job complete: {job.job_id}")


def validate():
    """Quick validation of the output table."""
    log("Validating output...")

    query = f"""
    SELECT
      fault_id,
      COUNT(*) AS total_days,
      SUM(hac_count) AS total_records,
      COUNTIF(hac_count > 0) AS days_with_signal,
      MAX(hac_count) AS max_daily_count,
      MAX(hac_count_zscore) AS max_zscore,
      ROUND(AVG(hac_intensity_mean), 3) AS avg_intensity
    FROM `{OUTPUT_TABLE}`
    GROUP BY fault_id
    ORDER BY fault_id
    """
    rows = list(bq.query(query).result())
    log(f"\n=== hac_features_daily validation ===")
    log(f"  {'fault_id':<20} {'days':>6} {'records':>8} "
        f"{'active_days':>12} {'max_daily':>10} "
        f"{'max_z':>8} {'avg_intensity':>14}")
    log(f"  {'-'*80}")
    for r in rows:
        max_z = f"{r.max_zscore:.2f}" if r.max_zscore else "N/A"
        log(f"  {r.fault_id:<20} {r.total_days:>6} {r.total_records:>8} "
            f"{r.days_with_signal:>12} {r.max_daily_count:>10} "
            f"{max_z:>8} {r.avg_intensity:>14.3f}")

    # Check top z-score days
    query2 = f"""
    SELECT fault_id, date_val, hac_count, hac_count_zscore,
           hac_count_high_urgency, hac_count_water
    FROM `{OUTPUT_TABLE}`
    WHERE hac_count_zscore IS NOT NULL
    ORDER BY hac_count_zscore DESC
    LIMIT 10
    """
    top_rows = list(bq.query(query2).result())
    log(f"\n  Top 10 days by z-score:")
    for r in top_rows:
        log(f"    {r.fault_id:<20} {r.date_val} "
            f"count={r.hac_count:3d} z={r.hac_count_zscore:6.2f} "
            f"high_urg={r.hac_count_high_urgency} water={r.hac_count_water}")


def main():
    log("=== build_hac_features_daily starting ===")
    drop_if_rebuild()
    build_hac_features_daily()
    validate()
    log("=== build_hac_features_daily complete ===")


if __name__ == "__main__":
    main()
