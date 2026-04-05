-- ============================================================
-- H3 STEP 2: Feature Engineering
-- INSPIRE methodology (Pulinets et al. 2021, Front. Earth Sci. 9:610193)
--
-- Applies to: sentinel_features.h3_tec_raw (built by h3_01_backfill)
-- Produces:   sentinel_features.h3_features_daily
--
-- Pre-registered features (commit f172953, Amendment #1 496ebf1):
--   tec_delta_fullday:   DELTA_TEC full-day (INSPIRE formula)
--   tec_delta_nighttime: DELTA_TEC nighttime only (INSPIRE key finding)
--   tec_lssi:            Local Spatial Scintillation Index proxy
--   tec_delta_lag1d:     1-day lagged full-day DELTA_TEC
--   tec_delta_lag3d:     3-day lagged full-day DELTA_TEC
--   tec_delta_lag5d:     5-day lagged full-day DELTA_TEC (INSPIRE peak)
--   tec_delta_lag7d:     7-day lagged full-day DELTA_TEC
--   tec_nighttime_lag5d: 5-day lagged nighttime DELTA_TEC
--
-- INSPIRE DELTA_TEC formula:
--   DELTA_TEC = 100 * (TEC - TECa) / TECa
--   where TECa = 15-day running median of same parameter
-- ============================================================

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h3_features_daily` AS

WITH

-- ── Step 1: Compute 15-day running median baseline (INSPIRE TECa) ──────────
tec_with_baseline AS (
  SELECT
    day,
    fault_id,
    tec_fullday_mean,
    tec_nighttime_mean,
    n_cells,
    n_maps_valid,

    -- 15-day running baseline for full-day TEC (TECa per INSPIRE)
    -- PERCENTILE_CONT not supported in window context in BigQuery
    -- Using AVG as baseline (robust for TEC which is ~normally distributed)
    AVG(tec_fullday_mean) OVER (
      PARTITION BY fault_id
      ORDER BY day
      ROWS BETWEEN 15 PRECEDING AND 1 PRECEDING
    ) AS tec_fullday_median_15d,

    -- 15-day running baseline for nighttime TEC
    AVG(tec_nighttime_mean) OVER (
      PARTITION BY fault_id
      ORDER BY day
      ROWS BETWEEN 15 PRECEDING AND 1 PRECEDING
    ) AS tec_nighttime_median_15d,

    -- For LSSI proxy: rolling std of fullday TEC (spatial variability proxy)
    STDDEV(tec_fullday_mean) OVER (
      PARTITION BY fault_id
      ORDER BY day
      ROWS BETWEEN 14 PRECEDING AND CURRENT ROW
    ) AS tec_fullday_std_15d

  FROM `synexis-project-sentinel.sentinel_features.h3_tec_raw`
  WHERE tec_fullday_mean IS NOT NULL
),

-- ── Step 2: Apply INSPIRE DELTA_TEC formula ────────────────────────────────
-- DELTA_TEC = 100 * (TEC - TECa) / TECa
tec_with_delta AS (
  SELECT
    day,
    fault_id,
    tec_fullday_mean,
    tec_nighttime_mean,
    n_cells,
    n_maps_valid,
    tec_fullday_median_15d,
    tec_nighttime_median_15d,
    tec_fullday_std_15d,

    -- Full-day DELTA_TEC (primary INSPIRE feature)
    CASE
      WHEN tec_fullday_median_15d IS NOT NULL
        AND tec_fullday_median_15d > 0
      THEN ROUND(100.0 * (tec_fullday_mean - tec_fullday_median_15d)
                 / tec_fullday_median_15d, 4)
      ELSE NULL
    END AS tec_delta_fullday,

    -- Nighttime DELTA_TEC (INSPIRE key finding: pre-seismic coupling at night)
    CASE
      WHEN tec_nighttime_median_15d IS NOT NULL
        AND tec_nighttime_median_15d > 0
        AND tec_nighttime_mean IS NOT NULL
      THEN ROUND(100.0 * (tec_nighttime_mean - tec_nighttime_median_15d)
                 / tec_nighttime_median_15d, 4)
      ELSE NULL
    END AS tec_delta_nighttime,

    -- LSSI proxy: normalized std (spatial scintillation index)
    CASE
      WHEN tec_fullday_median_15d IS NOT NULL AND tec_fullday_median_15d > 0
      THEN ROUND(tec_fullday_std_15d / tec_fullday_median_15d, 4)
      ELSE NULL
    END AS tec_lssi

  FROM tec_with_baseline
  WHERE tec_fullday_median_15d IS NOT NULL  -- exclude first 14 days (insufficient window)
),

-- ── Step 3: Add lag window features ────────────────────────────────────────
-- Pre-registered lag windows: 1, 3, 5, 7 days
-- For each day D, lag features use values from D-N days ago
-- This represents: "was there a TEC anomaly N days before this event?"
tec_with_lags AS (
  SELECT
    base.day,
    base.fault_id,
    base.tec_fullday_mean,
    base.tec_nighttime_mean,
    base.tec_delta_fullday,
    base.tec_delta_nighttime,
    base.tec_lssi,
    base.n_cells,
    base.n_maps_valid,
    base.tec_fullday_median_15d,

    -- Lag features: TEC anomaly from N days ago
    -- (joined back to same table offset by N days)
    lag1.tec_delta_fullday   AS tec_delta_lag1d,
    lag3.tec_delta_fullday   AS tec_delta_lag3d,
    lag5.tec_delta_fullday   AS tec_delta_lag5d,   -- PRIMARY: INSPIRE 5-day peak
    lag7.tec_delta_fullday   AS tec_delta_lag7d,
    lag5.tec_delta_nighttime AS tec_nighttime_lag5d, -- nighttime 5-day lag

    -- Data split assignment (same as H1)
    CASE
      WHEN base.day <= '2018-12-31' THEN 'train'
      WHEN base.day <= '2022-12-31' THEN 'val'
      ELSE 'test'
    END AS data_split

  FROM tec_with_delta base
  LEFT JOIN tec_with_delta lag1
    ON base.fault_id = lag1.fault_id
    AND lag1.day = DATE_SUB(base.day, INTERVAL 1 DAY)
  LEFT JOIN tec_with_delta lag3
    ON base.fault_id = lag3.fault_id
    AND lag3.day = DATE_SUB(base.day, INTERVAL 3 DAY)
  LEFT JOIN tec_with_delta lag5
    ON base.fault_id = lag5.fault_id
    AND lag5.day = DATE_SUB(base.day, INTERVAL 5 DAY)
  LEFT JOIN tec_with_delta lag7
    ON base.fault_id = lag7.fault_id
    AND lag7.day = DATE_SUB(base.day, INTERVAL 7 DAY)
)

SELECT * FROM tec_with_lags
ORDER BY fault_id, day;

-- ── Verification ─────────────────────────────────────────────────────────────
SELECT
  fault_id,
  data_split,
  COUNT(*)                              AS row_count,
  COUNTIF(tec_delta_fullday IS NOT NULL) AS rows_with_delta_tec,
  COUNTIF(tec_delta_nighttime IS NOT NULL) AS rows_with_nighttime,
  ROUND(AVG(tec_delta_fullday), 4)      AS avg_delta_tec,
  ROUND(AVG(tec_delta_nighttime), 4)    AS avg_delta_nighttime,
  ROUND(AVG(tec_delta_lag5d), 4)        AS avg_lag5d,
  ROUND(STDDEV(tec_delta_fullday), 4)   AS std_delta_tec
FROM `synexis-project-sentinel.sentinel_features.h3_features_daily`
GROUP BY fault_id, data_split
ORDER BY fault_id, data_split;
