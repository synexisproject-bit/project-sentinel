-- H1-IQR: Moving Interquartile Range TEC Baseline
-- Amendment #9 v3 | osf.io/8hvf6 | Pre-registered before execution
--
-- Replaces 15-day running median with 27-day moving IQR baseline
-- Uses nighttime-only TEC per LAIC/INSPIRE field standard (Pulinets et al. 2021)
-- Space weather filter: exclude storm days (Kp>=5 OR Dst<=-50 nT)
-- F10.7 27-day mean included as solar cycle covariate
--
-- Note: Moving percentiles use self-join + APPROX_QUANTILES
-- (BigQuery does not support PERCENTILE_CONT with ROWS BETWEEN)
-- APPROX_QUANTILES accuracy is sufficient for anomaly detection
--
-- Output: sentinel_features.h1_iqr_features_daily

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h1_iqr_features_daily`

AS

WITH

-- Step 1: Join TEC and space weather, compute storm_day flag
tec_geo AS (
  SELECT
    t.fault_id,
    t.day                      AS date_val,
    t.tec_nighttime_mean,
    t.tec_delta_nighttime,
    t.n_maps_valid,
    g.kp_max,
    g.dst_min,
    g.f107,
    g.f107_27d_mean,
    g.storm_flag_kp5,
    g.storm_flag_dst50,
    CASE
      WHEN g.storm_flag_kp5 = 1 OR g.storm_flag_dst50 = 1 THEN 1
      ELSE 0
    END AS storm_day
  FROM `synexis-project-sentinel.sentinel_features.h3_features_daily` t
  LEFT JOIN `synexis-project-sentinel.sentinel_features.hgeo_features_final` g
    ON t.fault_id = g.fault_id AND t.day = g.date_val
  WHERE t.day BETWEEN '2001-01-01' AND '2025-12-31'
    AND t.tec_nighttime_mean IS NOT NULL
),

-- Step 2: Self-join to gather prior 27 clean days per (fault_id, date_val)
-- Excludes storm days from baseline computation
-- Lookback window: [date_val - 27d, date_val - 1d] — no future leakage
tec_window AS (
  SELECT
    a.fault_id,
    a.date_val,
    a.tec_nighttime_mean,
    a.tec_delta_nighttime,
    a.storm_day                AS current_storm_day,
    a.kp_max,
    a.dst_min,
    a.f107,
    a.f107_27d_mean,
    a.storm_flag_kp5,
    a.storm_flag_dst50,
    a.n_maps_valid,
    -- Historical clean-day values for IQR computation
    APPROX_QUANTILES(
      IF(b.storm_day = 0, b.tec_nighttime_mean, NULL), 4
    ) AS qtiles
  FROM tec_geo a
  LEFT JOIN tec_geo b
    ON  a.fault_id = b.fault_id
    AND b.date_val >= DATE_SUB(a.date_val, INTERVAL 27 DAY)
    AND b.date_val <  a.date_val
  GROUP BY
    a.fault_id, a.date_val, a.tec_nighttime_mean, a.tec_delta_nighttime,
    a.storm_day, a.kp_max, a.dst_min, a.f107, a.f107_27d_mean,
    a.storm_flag_kp5, a.storm_flag_dst50, a.n_maps_valid
),

-- Step 3: Extract percentiles and compute IQR anomaly score
tec_anomaly AS (
  SELECT
    fault_id,
    date_val,
    tec_nighttime_mean,
    tec_delta_nighttime,
    current_storm_day          AS storm_day,
    kp_max,
    dst_min,
    f107,
    f107_27d_mean,
    storm_flag_kp5,
    storm_flag_dst50,
    n_maps_valid,

    -- Extract percentile values from APPROX_QUANTILES array
    -- APPROX_QUANTILES(x, 4) returns [min, P25, P50, P75, max]
    qtiles[OFFSET(1)]          AS iqr_p25_27d,
    qtiles[OFFSET(2)]          AS iqr_median_27d,
    qtiles[OFFSET(3)]          AS iqr_p75_27d,
    qtiles[OFFSET(3)] - qtiles[OFFSET(1)] AS iqr_width_27d,

    -- Normalized anomaly score: deviation in IQR units
    CASE
      WHEN (qtiles[OFFSET(3)] - qtiles[OFFSET(1)]) > 0
      THEN (tec_nighttime_mean - qtiles[OFFSET(2)])
           / (qtiles[OFFSET(3)] - qtiles[OFFSET(1)])
      ELSE NULL
    END AS tec_iqr_anomaly,

    -- Binary anomaly flag: Tukey fence (1.5 * IQR), clean days only
    CASE
      WHEN (qtiles[OFFSET(3)] - qtiles[OFFSET(1)]) > 0
        AND current_storm_day = 0
        AND ABS(
              (tec_nighttime_mean - qtiles[OFFSET(2)])
              / (qtiles[OFFSET(3)] - qtiles[OFFSET(1)])
            ) > 1.5
      THEN 1
      ELSE 0
    END AS tec_iqr_anomaly_flag

  FROM tec_window
),

-- Step 4: Lag features on anomaly score and flag
tec_lagged AS (
  SELECT
    fault_id,
    date_val,
    tec_nighttime_mean,
    iqr_median_27d,
    iqr_p25_27d,
    iqr_p75_27d,
    iqr_width_27d,
    tec_iqr_anomaly,
    tec_iqr_anomaly_flag,
    storm_day,
    kp_max,
    dst_min,
    f107,
    f107_27d_mean,
    storm_flag_kp5,
    storm_flag_dst50,
    n_maps_valid,

    -- Lagged anomaly scores
    LAG(tec_iqr_anomaly, 1) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_anomaly_lag1d,
    LAG(tec_iqr_anomaly, 3) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_anomaly_lag3d,
    LAG(tec_iqr_anomaly, 5) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_anomaly_lag5d,
    LAG(tec_iqr_anomaly, 7) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_anomaly_lag7d,

    -- Lagged anomaly flags
    LAG(tec_iqr_anomaly_flag, 1) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_flag_lag1d,
    LAG(tec_iqr_anomaly_flag, 3) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_flag_lag3d,
    LAG(tec_iqr_anomaly_flag, 5) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_flag_lag5d,
    LAG(tec_iqr_anomaly_flag, 7) OVER (PARTITION BY fault_id ORDER BY date_val)
      AS tec_iqr_flag_lag7d,

    -- Rolling anomaly counts
    SUM(tec_iqr_anomaly_flag) OVER (
      PARTITION BY fault_id ORDER BY date_val
      ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS tec_iqr_anomaly_count_7d,

    SUM(tec_iqr_anomaly_flag) OVER (
      PARTITION BY fault_id ORDER BY date_val
      ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
    ) AS tec_iqr_anomaly_count_14d,

    -- Rolling max anomaly magnitude
    MAX(ABS(tec_iqr_anomaly)) OVER (
      PARTITION BY fault_id ORDER BY date_val
      ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS tec_iqr_anomaly_max_7d

  FROM tec_anomaly
),

-- Step 5: Join labels and walk-forward fold assignments
labeled AS (
  SELECT
    t.*,
    l.label_7d,
    l.label_7d_m60,
    CASE
      WHEN t.fault_id IN ('cascadia', 'north_anatolian') THEN l.label_7d_m60
      ELSE l.label_7d
    END AS label,
    l.max_upcoming_magnitude,
    l.data_split,
    h1.b_value_90d,
    h1.mean_mag_90d,
    h1.event_count_90d,
    h1.quiescence_z_stat,
    h1.baseline_365d_mean,
    h1.foreshock_rate_z,
    h1.event_count_7d,
    h1.baseline_30d_mean
  FROM tec_lagged t
  LEFT JOIN `synexis-project-sentinel.sentinel_features.h1_labels` l
    ON t.fault_id = l.fault_id AND t.date_val = l.date_val
  LEFT JOIN `synexis-project-sentinel.sentinel_features.h1_features_daily` h1
    ON t.fault_id = h1.fault_id AND t.date_val = h1.date_val
)

SELECT * FROM labeled
ORDER BY fault_id, date_val
