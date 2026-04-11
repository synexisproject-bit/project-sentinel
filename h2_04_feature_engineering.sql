-- H2-04: Feature engineering for GPS deformation stream
-- Reads h2_features_daily, builds lag windows, Z-scores,
-- joins earthquake labels, assigns walk-forward splits.
-- Output: sentinel_features.h2_features_final
--
-- Magnitude thresholds per Amendment #1:
--   cascadia, north_anatolian → M≥6.0
--   all others                → M≥6.5
-- Walk-forward: 10 folds, initial training 2001-2015, expanding window
-- Pre-registered threshold: AUROC ≥ 0.58 at Japan Trench AND Cascadia

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 1: Z-score normalization + lag windows per fault zone
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h2_features_lagged`
OPTIONS (require_partition_filter = false)
AS
WITH

stats AS (
  SELECT
    fault_zone,
    AVG(stack_fp_mm)         AS mean_fp,
    STDDEV(stack_fp_mm)      AS std_fp,
    AVG(mean_east_resid_mm)  AS mean_e,
    STDDEV(mean_east_resid_mm) AS std_e,
    AVG(mean_north_resid_mm) AS mean_n,
    STDDEV(mean_north_resid_mm) AS std_n,
    AVG(mean_up_resid_mm)    AS mean_u,
    STDDEV(mean_up_resid_mm) AS std_u,
    AVG(stack_fp_std)        AS mean_fp_std,
    STDDEV(stack_fp_std)     AS std_fp_std
  FROM `synexis-project-sentinel.sentinel_features.h2_features_daily`
  WHERE stack_fp_mm IS NOT NULL
    AND n_stations >= 3
  GROUP BY fault_zone
),

normalized AS (
  SELECT
    d.fault_zone,
    d.date_val,
    d.n_stations,
    SAFE_DIVIDE(d.stack_fp_mm        - s.mean_fp,   s.std_fp)   AS z_fp,
    SAFE_DIVIDE(d.mean_east_resid_mm - s.mean_e,    s.std_e)    AS z_east,
    SAFE_DIVIDE(d.mean_north_resid_mm- s.mean_n,    s.std_n)    AS z_north,
    SAFE_DIVIDE(d.mean_up_resid_mm   - s.mean_u,    s.std_u)    AS z_up,
    SAFE_DIVIDE(d.stack_fp_std       - s.mean_fp_std, s.std_fp_std) AS z_fp_std,
    d.stack_fp_mm,
    d.mean_east_resid_mm,
    d.mean_north_resid_mm,
    d.mean_up_resid_mm,
    d.stack_fp_std
  FROM `synexis-project-sentinel.sentinel_features.h2_features_daily` d
  JOIN stats s USING (fault_zone)
  WHERE d.stack_fp_mm IS NOT NULL
    AND d.n_stations >= 3
),

lagged AS (
  SELECT
    fault_zone,
    date_val,
    n_stations,

    -- Raw features
    stack_fp_mm,
    mean_east_resid_mm,
    mean_north_resid_mm,
    mean_up_resid_mm,
    stack_fp_std,

    -- Z-scored current
    z_fp,
    z_east,
    z_north,
    z_up,
    z_fp_std,

    -- Lag windows: 3, 7, 14, 30 days
    AVG(z_fp)   OVER w3   AS z_fp_3d_mean,
    AVG(z_fp)   OVER w7   AS z_fp_7d_mean,
    AVG(z_fp)   OVER w14  AS z_fp_14d_mean,
    AVG(z_fp)   OVER w30  AS z_fp_30d_mean,

    STDDEV(z_fp) OVER w7  AS z_fp_7d_std,
    STDDEV(z_fp) OVER w14 AS z_fp_14d_std,
    STDDEV(z_fp) OVER w30 AS z_fp_30d_std,

    MAX(ABS(z_fp)) OVER w7  AS z_fp_7d_max_abs,
    MAX(ABS(z_fp)) OVER w14 AS z_fp_14d_max_abs,
    MAX(ABS(z_fp)) OVER w30 AS z_fp_30d_max_abs,

    -- Velocity proxy: difference from N-day ago
    z_fp - LAG(z_fp, 3)  OVER wfull AS z_fp_delta_3d,
    z_fp - LAG(z_fp, 7)  OVER wfull AS z_fp_delta_7d,
    z_fp - LAG(z_fp, 14) OVER wfull AS z_fp_delta_14d,

    -- Up component lags (vertical deformation)
    AVG(z_up) OVER w7   AS z_up_7d_mean,
    AVG(z_up) OVER w14  AS z_up_14d_mean,
    AVG(z_up) OVER w30  AS z_up_30d_mean,

    -- Network coherence proxy (lower std = more coherent)
    AVG(z_fp_std) OVER w7  AS z_fp_std_7d_mean,
    AVG(z_fp_std) OVER w14 AS z_fp_std_14d_mean,

    -- Station count trend
    AVG(n_stations) OVER w7  AS n_stations_7d_mean,
    AVG(n_stations) OVER w30 AS n_stations_30d_mean

  FROM normalized
  WINDOW
    wfull AS (PARTITION BY fault_zone ORDER BY date_val
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
    w3    AS (PARTITION BY fault_zone ORDER BY date_val
              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
    w7    AS (PARTITION BY fault_zone ORDER BY date_val
              ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
    w14   AS (PARTITION BY fault_zone ORDER BY date_val
              ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
    w30   AS (PARTITION BY fault_zone ORDER BY date_val
              ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
)

SELECT * FROM lagged;


-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 2: Join earthquake labels (M≥6.0 / M≥6.5 per Amendment #1)
-- Labels from sentinel_features.earthquake_catalog (same as H1/H3)
-- label_7d = 1 if M-threshold quake occurs within fault zone within 7 days
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h2_features_labeled`
OPTIONS (require_partition_filter = false)
AS
WITH

-- Magnitude threshold per fault zone (Amendment #1)
mag_thresholds AS (
  SELECT 'japan_trench'    AS fault_zone, 6.5 AS mag_threshold UNION ALL
  SELECT 'cascadia',                      6.0 UNION ALL
  SELECT 'central_chile',                 6.5 UNION ALL
  SELECT 'north_anatolian',               6.0 UNION ALL
  SELECT 'sumatra_andaman',               6.5
),

quakes AS (
  SELECT
    eq.fault_zone,
    eq.event_date,
    eq.magnitude
  FROM `synexis-project-sentinel.sentinel_features.earthquake_catalog` eq
  JOIN mag_thresholds mt USING (fault_zone)
  WHERE eq.magnitude >= mt.mag_threshold
),

-- For each (fault_zone, date_val), label = 1 if qualifying quake in [date+1, date+7]
labeled AS (
  SELECT
    f.*,
    CASE
      WHEN EXISTS (
        SELECT 1 FROM quakes q
        WHERE q.fault_zone = f.fault_zone
          AND q.event_date > f.date_val
          AND q.event_date <= DATE_ADD(f.date_val, INTERVAL 7 DAY)
      ) THEN 1
      ELSE 0
    END AS label_7d,
    CASE
      WHEN EXISTS (
        SELECT 1 FROM quakes q
        WHERE q.fault_zone = f.fault_zone
          AND q.event_date > f.date_val
          AND q.event_date <= DATE_ADD(f.date_val, INTERVAL 14 DAY)
      ) THEN 1
      ELSE 0
    END AS label_14d
  FROM `synexis-project-sentinel.sentinel_features.h2_features_lagged` f
)

SELECT * FROM labeled;


-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 3: Walk-forward split assignment
-- 10 annual folds, initial training window: 2001-01-01 → 2015-12-31
-- Fold k test year = 2016 + (k-1)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h2_features_final`
OPTIONS (require_partition_filter = false)
AS
WITH

fold_assignments AS (
  SELECT
    fault_zone,
    date_val,
    CASE
      -- Burn-in / pre-training: exclude from walk-forward (used only as training context)
      WHEN date_val < '2001-01-01' THEN -1

      -- Training-only rows for all folds (before test period begins)
      WHEN date_val <= '2015-12-31' THEN 0

      -- Walk-forward test folds: fold k tests on year 2015+k
      WHEN EXTRACT(YEAR FROM date_val) = 2016 THEN 1
      WHEN EXTRACT(YEAR FROM date_val) = 2017 THEN 2
      WHEN EXTRACT(YEAR FROM date_val) = 2018 THEN 3
      WHEN EXTRACT(YEAR FROM date_val) = 2019 THEN 4
      WHEN EXTRACT(YEAR FROM date_val) = 2020 THEN 5
      WHEN EXTRACT(YEAR FROM date_val) = 2021 THEN 6
      WHEN EXTRACT(YEAR FROM date_val) = 2022 THEN 7
      WHEN EXTRACT(YEAR FROM date_val) = 2023 THEN 8
      WHEN EXTRACT(YEAR FROM date_val) = 2024 THEN 9
      WHEN EXTRACT(YEAR FROM date_val) = 2025 THEN 10

      ELSE -99  -- future / out of range
    END AS wf_fold,

    -- split_type for quick filtering
    CASE
      WHEN date_val < '2001-01-01'  THEN 'burn_in'
      WHEN date_val <= '2015-12-31' THEN 'train'
      WHEN EXTRACT(YEAR FROM date_val) BETWEEN 2016 AND 2025 THEN 'test'
      ELSE 'future'
    END AS split_type

  FROM `synexis-project-sentinel.sentinel_features.h2_features_labeled`
)

SELECT
  l.*,
  fa.wf_fold,
  fa.split_type
FROM `synexis-project-sentinel.sentinel_features.h2_features_labeled` l
JOIN fold_assignments fa USING (fault_zone, date_val)
-- Drop rows with insufficient lag data (first 30 days of each fault zone)
WHERE l.z_fp_30d_mean IS NOT NULL
ORDER BY fault_zone, date_val;


-- ─────────────────────────────────────────────────────────────────────────────
-- VALIDATION QUERIES — run after table creation to verify
-- ─────────────────────────────────────────────────────────────────────────────

-- Row counts per fault zone and split type
/*
SELECT fault_zone, split_type, COUNT(*) AS n_rows,
       SUM(label_7d) AS n_positive, AVG(label_7d) AS base_rate
FROM `synexis-project-sentinel.sentinel_features.h2_features_final`
GROUP BY 1,2 ORDER BY 1,2;
*/

-- Fold coverage check
/*
SELECT fault_zone, wf_fold, split_type,
       MIN(date_val) AS date_min, MAX(date_val) AS date_max,
       COUNT(*) AS n_rows
FROM `synexis-project-sentinel.sentinel_features.h2_features_final`
GROUP BY 1,2,3 ORDER BY 1,2;
*/

-- Feature completeness
/*
SELECT fault_zone,
       COUNTIF(z_fp IS NULL) AS null_z_fp,
       COUNTIF(z_fp_7d_mean IS NULL) AS null_z_fp_7d,
       COUNTIF(z_fp_30d_mean IS NULL) AS null_z_fp_30d,
       COUNTIF(label_7d IS NULL) AS null_label
FROM `synexis-project-sentinel.sentinel_features.h2_features_final`
GROUP BY 1;
*/
