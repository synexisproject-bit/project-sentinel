-- ============================================================
-- H1 STEP 2: Extract fault-specific events and compute
--            daily seismic features per fault system
-- Project Sentinel Phase 2
--
-- VERIFY BEFORE RUNNING: Check column names in master_earthquakes
-- by running:
--   SELECT column_name FROM
--   synexis-project-sentinel.sentinel_groundtruth.INFORMATION_SCHEMA.COLUMNS
--   WHERE table_name = 'master_earthquakes';
--
-- This script assumes columns: time, latitude, longitude, depth, magnitude
-- Adjust if your schema uses different names (e.g. 'mag' vs 'magnitude')
-- ============================================================

-- ── STEP 2A: Fault-specific event catalog ─────────────────────────────────
-- Tag each event with the fault system(s) it falls within
-- An event can belong to multiple fault systems if bounding boxes overlap

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.fault_events` AS

SELECT
  eq.time,
  DATE(eq.time)        AS event_date,
  eq.latitude,
  eq.longitude,
  eq.depth_km,
  eq.magnitude,
  fs.fault_id,
  fs.fault_name,
  fs.tectonic_setting
FROM `synexis-project-sentinel.sentinel_groundtruth.master_earthquakes` eq
JOIN `synexis-project-sentinel.sentinel_features.fault_systems` fs
  ON eq.latitude  BETWEEN fs.lat_min AND fs.lat_max
  AND eq.longitude BETWEEN fs.lon_min AND fs.lon_max
WHERE eq.magnitude >= 2.0  -- Include M2.0+ for b-value and quiescence computation
  AND eq.depth_km <= 200.0    -- Exclude very deep events (not crustal)
  AND DATE(eq.time) BETWEEN '2001-01-01' AND '2025-12-31';

-- Quick check: event counts per fault system
SELECT
  fault_id,
  COUNT(*) AS total_events,
  COUNTIF(magnitude >= 6.5) AS target_events,
  MIN(event_date) AS earliest,
  MAX(event_date) AS latest
FROM `synexis-project-sentinel.sentinel_features.fault_events`
GROUP BY fault_id
ORDER BY fault_id;


-- ── STEP 2B: Generate spine of all dates × fault systems ──────────────────
-- We need one row per (date, fault_id) for the full study period
-- even on days with zero events

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.fault_date_spine` AS

SELECT
  date_val,
  fault_id
FROM
  UNNEST(GENERATE_DATE_ARRAY('2001-01-01', '2025-12-31')) AS date_val
CROSS JOIN (
  SELECT fault_id FROM `synexis-project-sentinel.sentinel_features.fault_systems`
);

-- ── STEP 2C: Compute daily H1 features ────────────────────────────────────
-- For each (date, fault_id):
--   Feature 1: b-value over rolling 90-day window
--   Feature 2: quiescence Z-stat vs 365-day rolling mean
--   Feature 3: foreshock rate (M2.0+ count, 0-7 days, vs 30-day baseline)

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h1_features_daily` AS

WITH

-- Daily event counts and magnitude stats per fault system
daily_counts AS (
  SELECT
    spine.date_val,
    spine.fault_id,
    COUNT(eq.time)                              AS event_count,
    COUNTIF(eq.magnitude >= 2.0)               AS count_m2plus,
    COUNTIF(eq.magnitude >= 4.0)               AS count_m4plus,
    COUNTIF(eq.magnitude >= 6.5)               AS count_m65plus,  -- target label events
    MAX(eq.magnitude)                           AS max_magnitude,
    AVG(eq.magnitude)                           AS avg_magnitude,
    -- For b-value: need log10(N) vs magnitude — computed in rolling window below
    ARRAY_AGG(eq.magnitude IGNORE NULLS
      ORDER BY eq.magnitude)                    AS magnitude_array
  FROM `synexis-project-sentinel.sentinel_features.fault_date_spine` spine
  LEFT JOIN `synexis-project-sentinel.sentinel_features.fault_events` eq
    ON DATE(eq.time) = spine.date_val
    AND eq.fault_id  = spine.fault_id
    AND eq.magnitude >= 2.0
  GROUP BY spine.date_val, spine.fault_id
),

-- Rolling 90-day event count for b-value window
-- Rolling 365-day mean + stddev for quiescence
-- Rolling 30-day mean for foreshock baseline
rolling_stats AS (
  SELECT
    date_val,
    fault_id,
    event_count,
    count_m2plus,
    count_m4plus,
    count_m65plus,
    max_magnitude,
    avg_magnitude,

    -- 90-day rolling sum (for b-value denominator)
    SUM(count_m2plus) OVER (
      PARTITION BY fault_id
      ORDER BY date_val
      ROWS BETWEEN 89 PRECEDING AND CURRENT ROW
    ) AS rolling_90d_count,

    -- 365-day rolling mean (quiescence baseline)
    AVG(count_m2plus) OVER (
      PARTITION BY fault_id
      ORDER BY date_val
      ROWS BETWEEN 364 PRECEDING AND CURRENT ROW
    ) AS rolling_365d_mean,

    -- 365-day rolling stddev (quiescence normalization)
    STDDEV(count_m2plus) OVER (
      PARTITION BY fault_id
      ORDER BY date_val
      ROWS BETWEEN 364 PRECEDING AND CURRENT ROW
    ) AS rolling_365d_std,

    -- 7-day rolling sum (foreshock window)
    SUM(count_m2plus) OVER (
      PARTITION BY fault_id
      ORDER BY date_val
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7d_count,

    -- 30-day rolling mean (foreshock baseline)
    AVG(count_m2plus) OVER (
      PARTITION BY fault_id
      ORDER BY date_val
      ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS rolling_30d_mean,

    -- 30-day rolling stddev
    STDDEV(count_m2plus) OVER (
      PARTITION BY fault_id
      ORDER BY date_val
      ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS rolling_30d_std,

    -- 90-day mean magnitude (b-value proxy numerator)
    AVG(avg_magnitude) OVER (
      PARTITION BY fault_id
      ORDER BY date_val
      ROWS BETWEEN 89 PRECEDING AND CURRENT ROW
    ) AS rolling_90d_avg_mag

  FROM daily_counts
)

-- Final feature computation
SELECT
  date_val,
  fault_id,
  event_count,
  count_m2plus,
  count_m4plus,
  count_m65plus,
  max_magnitude,

  -- ── Feature 1: b-value proxy ──────────────────────────────────────────
  -- Simplified b-value: b ≈ log10(e) / (mean_mag - Mmin)
  -- where Mmin = 2.0 (our catalog threshold)
  -- Full Aki maximum likelihood estimator
  -- b = log10(e) / (mean_mag - Mmin) = 0.4343 / (mean_mag - 2.0)
  CASE
    WHEN rolling_90d_avg_mag > 2.0
    THEN 0.4343 / (rolling_90d_avg_mag - 2.0)
    ELSE NULL
  END AS b_value_90d,

  -- b-value anomaly: z-score vs fault-system population mean
  -- (computed as raw value here; normalized in Python model)
  rolling_90d_avg_mag AS mean_mag_90d,
  rolling_90d_count   AS event_count_90d,

  -- ── Feature 2: Quiescence Z-stat ──────────────────────────────────────
  -- Z = (current_count - 365d_mean) / 365d_std
  -- Negative Z = unusual quiet = potential quiescence signal
  CASE
    WHEN rolling_365d_std > 0
    THEN (count_m2plus - rolling_365d_mean) / rolling_365d_std
    ELSE 0.0
  END AS quiescence_z_stat,

  rolling_365d_mean AS baseline_365d_mean,
  rolling_365d_std  AS baseline_365d_std,

  -- ── Feature 3: Foreshock rate anomaly ─────────────────────────────────
  -- Z = (7d_count - 30d_mean) / 30d_std
  -- Positive Z = elevated short-term activity above baseline
  CASE
    WHEN rolling_30d_std > 0
    THEN (rolling_7d_count - rolling_30d_mean) / rolling_30d_std
    ELSE 0.0
  END AS foreshock_rate_z,

  rolling_7d_count  AS event_count_7d,
  rolling_30d_mean  AS baseline_30d_mean,

  -- ── Lag window flags ──────────────────────────────────────────────────
  -- Pre-compute whether this row is 1, 3, 5, 7 days before a target event
  -- Target events loaded in Step 3 (labels) and joined in Python

  -- Data split assignment (time-based, no leakage)
  CASE
    WHEN date_val <= '2018-12-31' THEN 'train'
    WHEN date_val <= '2022-12-31' THEN 'val'
    ELSE 'test'
  END AS data_split

FROM rolling_stats
-- Exclude first 365 days per fault system (insufficient rolling window)
WHERE date_val >= DATE_ADD('2001-01-01', INTERVAL 365 DAY)
ORDER BY fault_id, date_val;

-- Verify feature counts per fault system and split
SELECT
  fault_id,
  data_split,
  COUNT(*) AS row_count,
  ROUND(AVG(b_value_90d), 4)        AS avg_b_value,
  ROUND(AVG(quiescence_z_stat), 4)  AS avg_quiescence_z,
  ROUND(AVG(foreshock_rate_z), 4)   AS avg_foreshock_z,
  COUNTIF(count_m65plus > 0)        AS days_with_target_event
FROM `synexis-project-sentinel.sentinel_features.h1_features_daily`
GROUP BY fault_id, data_split
ORDER BY fault_id, data_split;
