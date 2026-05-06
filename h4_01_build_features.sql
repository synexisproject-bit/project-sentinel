-- H4-01: Build multi-stream convergence feature table
-- Joins H1 (seismic), H2 (GPS), H3 (TEC), Geo (geomagnetic) streams
-- Output: sentinel_features.h4_features_final
--
-- Pre-registered fault zones (5): japan_trench, cascadia, central_chile,
--   north_anatolian, sumatra_andaman
-- Exploratory fault zone (1): hayward — advisory input from Clive Cook
--   (Precursor SPC, April 29 2026). Designated exploratory BEFORE results
--   known. Commit ca051fb. No pass/fail threshold applies.
--
-- Pre-registration: f172953 | Amendment #1: 496ebf1
-- Exploratory note: ca051fb (Hayward pre-H4)

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h4_features_final`
OPTIONS (require_partition_filter = false)
AS
WITH

h1 AS (
  SELECT
    fault_id, date_val,
    b_value_90d, mean_mag_90d, event_count_90d, quiescence_z_stat,
    baseline_365d_mean, foreshock_rate_z, event_count_7d, baseline_30d_mean
  FROM `synexis-project-sentinel.sentinel_features.h1_features_daily`
  WHERE date_val >= '2001-01-01'
),

h2 AS (
  SELECT
    fault_id, date_val,
    z_fp, z_east, z_north, z_up, z_fp_std,
    z_fp_3d_mean, z_fp_7d_mean, z_fp_14d_mean, z_fp_30d_mean,
    z_fp_7d_std, z_fp_14d_std, z_fp_30d_std,
    z_fp_7d_max_abs, z_fp_14d_max_abs, z_fp_30d_max_abs,
    z_fp_delta_3d, z_fp_delta_7d, z_fp_delta_14d,
    z_up_7d_mean, z_up_14d_mean, z_up_30d_mean,
    z_fp_std_7d_mean, z_fp_std_14d_mean,
    n_stations_7d_mean, n_stations_30d_mean
  FROM `synexis-project-sentinel.sentinel_features.h2_features_final`
  WHERE date_val >= '2001-01-01'
    AND split_type != 'burn_in'
),

h3 AS (
  SELECT
    fault_id, day AS date_val,
    tec_delta_fullday, tec_delta_nighttime, tec_lssi,
    tec_delta_lag1d, tec_delta_lag3d, tec_delta_lag5d,
    tec_delta_lag7d, tec_nighttime_lag5d
  FROM `synexis-project-sentinel.sentinel_features.h3_features_daily`
  WHERE day >= '2001-01-01'
),

geo AS (
  SELECT
    fault_id, date_val,
    kp_max, kp_mean, ap_daily, f107, dst_min, dst_mean,
    z_kp_max, z_kp_mean, z_ap, z_dst_min,
    storm_flag_kp5, storm_flag_dst50,
    kp_storm_days_7d, kp_max_7d_mean, dst_min_7d_mean,
    dst_recovery_7d, f107_27d_mean,
    h_z_score, h_z_lag1d, h_z_lag3d, h_z_lag5d, h_z_lag7d,
    h_z_3d_mean, h_z_7d_mean, h_z_7d_max
  FROM `synexis-project-sentinel.sentinel_features.hgeo_features_final`
  WHERE date_val >= '2001-01-01'
),

labels AS (
  SELECT
    fault_id, date_val,
    label_7d,
    CASE
      WHEN fault_id IN ('cascadia', 'north_anatolian') THEN label_7d_m60
      ELSE label_7d
    END AS label_primary,
    max_upcoming_magnitude
  FROM `synexis-project-sentinel.sentinel_features.h1_labels`
  WHERE date_val >= '2001-01-01'
),

joined AS (
  SELECT
    h1.fault_id,
    h1.date_val,
    CASE WHEN h2.fault_id IS NOT NULL THEN 1 ELSE 0 END AS has_h2,
    CASE WHEN h3.fault_id IS NOT NULL THEN 1 ELSE 0 END AS has_h3,
    CASE WHEN geo.fault_id IS NOT NULL THEN 1 ELSE 0 END AS has_geo,
    CASE WHEN h1.fault_id = 'hayward' THEN 1 ELSE 0 END AS is_exploratory,
    -- H1
    h1.b_value_90d, h1.mean_mag_90d, h1.event_count_90d, h1.quiescence_z_stat,
    h1.baseline_365d_mean, h1.foreshock_rate_z, h1.event_count_7d, h1.baseline_30d_mean,
    -- H2
    h2.z_fp, h2.z_east, h2.z_north, h2.z_up, h2.z_fp_std,
    h2.z_fp_3d_mean, h2.z_fp_7d_mean, h2.z_fp_14d_mean, h2.z_fp_30d_mean,
    h2.z_fp_7d_std, h2.z_fp_14d_std, h2.z_fp_30d_std,
    h2.z_fp_7d_max_abs, h2.z_fp_14d_max_abs, h2.z_fp_30d_max_abs,
    h2.z_fp_delta_3d, h2.z_fp_delta_7d, h2.z_fp_delta_14d,
    h2.z_up_7d_mean, h2.z_up_14d_mean, h2.z_up_30d_mean,
    h2.z_fp_std_7d_mean, h2.z_fp_std_14d_mean,
    h2.n_stations_7d_mean, h2.n_stations_30d_mean,
    -- H3
    h3.tec_delta_fullday, h3.tec_delta_nighttime, h3.tec_lssi,
    h3.tec_delta_lag1d, h3.tec_delta_lag3d, h3.tec_delta_lag5d,
    h3.tec_delta_lag7d, h3.tec_nighttime_lag5d,
    -- Geo
    geo.kp_max, geo.kp_mean, geo.ap_daily, geo.f107, geo.dst_min, geo.dst_mean,
    geo.z_kp_max, geo.z_kp_mean, geo.z_ap, geo.z_dst_min,
    geo.storm_flag_kp5, geo.storm_flag_dst50,
    geo.kp_storm_days_7d, geo.kp_max_7d_mean, geo.dst_min_7d_mean,
    geo.dst_recovery_7d, geo.f107_27d_mean,
    geo.h_z_score, geo.h_z_lag1d, geo.h_z_lag3d, geo.h_z_lag5d, geo.h_z_lag7d,
    geo.h_z_3d_mean, geo.h_z_7d_mean, geo.h_z_7d_max,
    -- Labels
    lbl.label_7d,
    lbl.label_primary AS label,
    lbl.max_upcoming_magnitude,
    -- Walk-forward folds
    CASE
      WHEN h1.date_val < '2001-01-01'  THEN -1
      WHEN h1.date_val <= '2015-12-31' THEN 0
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2016 THEN 1
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2017 THEN 2
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2018 THEN 3
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2019 THEN 4
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2020 THEN 5
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2021 THEN 6
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2022 THEN 7
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2023 THEN 8
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2024 THEN 9
      WHEN EXTRACT(YEAR FROM h1.date_val) = 2025 THEN 10
      ELSE -99
    END AS wf_fold,
    CASE
      WHEN h1.date_val < '2001-01-01'  THEN 'burn_in'
      WHEN h1.date_val <= '2015-12-31' THEN 'train'
      WHEN EXTRACT(YEAR FROM h1.date_val) BETWEEN 2016 AND 2025 THEN 'test'
      ELSE 'future'
    END AS split_type
  FROM h1
  LEFT JOIN h2  ON h1.fault_id = h2.fault_id  AND h1.date_val = h2.date_val
  LEFT JOIN h3  ON h1.fault_id = h3.fault_id  AND h1.date_val = h3.date_val
  LEFT JOIN geo ON h1.fault_id = geo.fault_id AND h1.date_val = geo.date_val
  INNER JOIN labels lbl ON h1.fault_id = lbl.fault_id AND h1.date_val = lbl.date_val
)

SELECT * FROM joined
WHERE label IS NOT NULL
ORDER BY fault_id, date_val;
