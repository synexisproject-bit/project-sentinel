-- HGEO-04: Feature engineering for geomagnetic stream
-- Reads hgeo_features_daily, adds Z-score normalization,
-- lag windows, geomagnetic storm flags, walk-forward splits.
-- Output: sentinel_features.hgeo_features_final
--
-- Features fed into H4 convergence model:
--   Global: kp_max, kp_mean, ap_daily, f107, dst_min, dst_mean
--   Local H: h_z_score, h_z_lag1d/3d/5d/7d, h_z_3d/7d_mean, h_z_7d_max
--   Derived: storm_flag, kp_storm_days_7d, dst_recovery_slope

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 1: Normalize global indices + add storm flags
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.hgeo_features_final` AS
WITH

-- Global normalization statistics (computed over full training period)
global_stats AS (
  SELECT
    AVG(kp_max)   AS mean_kp_max,   STDDEV(kp_max)   AS std_kp_max,
    AVG(kp_mean)  AS mean_kp_mean,  STDDEV(kp_mean)  AS std_kp_mean,
    AVG(ap_daily) AS mean_ap,       STDDEV(ap_daily) AS std_ap,
    AVG(f107)     AS mean_f107,     STDDEV(f107)     AS std_f107,
    AVG(dst_min)  AS mean_dst_min,  STDDEV(dst_min)  AS std_dst_min,
    AVG(dst_mean) AS mean_dst_mean, STDDEV(dst_mean) AS std_dst_mean
  FROM `synexis-project-sentinel.sentinel_features.hgeo_features_daily`
  WHERE date_val BETWEEN '2001-01-01' AND '2015-12-31'
    AND kp_max IS NOT NULL
),

-- Per-fault-zone H-component normalization
local_stats AS (
  SELECT
    fault_id,
    AVG(h_z_score)  AS mean_hz,  STDDEV(h_z_score)  AS std_hz,
    AVG(h_range)    AS mean_hr,  STDDEV(h_range)     AS std_hr
  FROM `synexis-project-sentinel.sentinel_features.hgeo_features_daily`
  WHERE date_val BETWEEN '2001-01-01' AND '2015-12-31'
    AND h_z_score IS NOT NULL
  GROUP BY fault_id
),

base AS (
  SELECT
    g.fault_id,
    g.date_val,
    g.obs_code,

    -- Raw global indices
    g.kp_max, g.kp_mean, g.ap_daily, g.f107,
    g.dst_min, g.dst_mean,

    -- Z-scored global indices
    SAFE_DIVIDE(g.kp_max   - s.mean_kp_max,   s.std_kp_max)   AS z_kp_max,
    SAFE_DIVIDE(g.kp_mean  - s.mean_kp_mean,  s.std_kp_mean)  AS z_kp_mean,
    SAFE_DIVIDE(g.ap_daily - s.mean_ap,        s.std_ap)       AS z_ap,
    SAFE_DIVIDE(g.f107     - s.mean_f107,      s.std_f107)     AS z_f107,
    SAFE_DIVIDE(g.dst_min  - s.mean_dst_min,   s.std_dst_min)  AS z_dst_min,
    SAFE_DIVIDE(g.dst_mean - s.mean_dst_mean,  s.std_dst_mean) AS z_dst_mean,

    -- Geomagnetic storm flags
    -- Kp >= 5 = moderate storm, >= 7 = severe
    CASE WHEN g.kp_max >= 5.0 THEN 1 ELSE 0 END AS storm_flag_kp5,
    CASE WHEN g.kp_max >= 7.0 THEN 1 ELSE 0 END AS storm_flag_kp7,
    -- Dst <= -50 = moderate storm, <= -100 = intense
    CASE WHEN g.dst_min <= -50  THEN 1 ELSE 0 END AS storm_flag_dst50,
    CASE WHEN g.dst_min <= -100 THEN 1 ELSE 0 END AS storm_flag_dst100,

    -- Local H anomaly features (already z-scored relative to local baseline)
    g.h_z_score,
    g.h_z_lag1d, g.h_z_lag3d, g.h_z_lag5d, g.h_z_lag7d,
    g.h_z_3d_mean, g.h_z_7d_mean, g.h_z_7d_max,
    g.h_range, g.h_range_7d_mean

  FROM `synexis-project-sentinel.sentinel_features.hgeo_features_daily` g
  CROSS JOIN global_stats s
  WHERE g.kp_max IS NOT NULL
),

windowed AS (
  SELECT
    b.*,

    -- Kp rolling windows (storm persistence)
    AVG(b.kp_max)  OVER w7  AS kp_max_7d_mean,
    AVG(b.kp_max)  OVER w14 AS kp_max_14d_mean,
    SUM(CAST(b.storm_flag_kp5 AS INT64)) OVER w7  AS kp_storm_days_7d,
    SUM(CAST(b.storm_flag_kp5 AS INT64)) OVER w14 AS kp_storm_days_14d,

    -- Dst rolling windows (recovery tracking)
    AVG(b.dst_min) OVER w7  AS dst_min_7d_mean,
    AVG(b.dst_min) OVER w14 AS dst_min_14d_mean,
    -- Dst recovery slope: current vs 7 days ago (positive = recovering)
    b.dst_min - LAG(b.dst_min, 7) OVER (PARTITION BY b.fault_id ORDER BY b.date_val)
      AS dst_recovery_7d,

    -- F10.7 rolling (solar flux trend)
    AVG(b.f107) OVER w27 AS f107_27d_mean,  -- ~solar rotation period
    b.f107 - LAG(b.f107, 27) OVER (PARTITION BY b.fault_id ORDER BY b.date_val)
      AS f107_delta_27d,

    -- Walk-forward fold assignment
    CASE
      WHEN b.date_val < '2001-01-01' THEN -1
      WHEN b.date_val <= '2015-12-31' THEN 0
      WHEN EXTRACT(YEAR FROM b.date_val) = 2016 THEN 1
      WHEN EXTRACT(YEAR FROM b.date_val) = 2017 THEN 2
      WHEN EXTRACT(YEAR FROM b.date_val) = 2018 THEN 3
      WHEN EXTRACT(YEAR FROM b.date_val) = 2019 THEN 4
      WHEN EXTRACT(YEAR FROM b.date_val) = 2020 THEN 5
      WHEN EXTRACT(YEAR FROM b.date_val) = 2021 THEN 6
      WHEN EXTRACT(YEAR FROM b.date_val) = 2022 THEN 7
      WHEN EXTRACT(YEAR FROM b.date_val) = 2023 THEN 8
      WHEN EXTRACT(YEAR FROM b.date_val) = 2024 THEN 9
      WHEN EXTRACT(YEAR FROM b.date_val) = 2025 THEN 10
      ELSE -99
    END AS wf_fold,

    CASE
      WHEN b.date_val < '2001-01-01'  THEN 'burn_in'
      WHEN b.date_val <= '2015-12-31' THEN 'train'
      WHEN EXTRACT(YEAR FROM b.date_val) BETWEEN 2016 AND 2025 THEN 'test'
      ELSE 'future'
    END AS split_type

  FROM base b
  WINDOW
    w7  AS (PARTITION BY b.fault_id ORDER BY b.date_val ROWS BETWEEN 6  PRECEDING AND CURRENT ROW),
    w14 AS (PARTITION BY b.fault_id ORDER BY b.date_val ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
    w27 AS (PARTITION BY b.fault_id ORDER BY b.date_val ROWS BETWEEN 26 PRECEDING AND CURRENT ROW)
)

SELECT * FROM windowed
ORDER BY fault_id, date_val;


-- ─────────────────────────────────────────────────────────────────────────────
-- VALIDATION
-- ─────────────────────────────────────────────────────────────────────────────
/*
SELECT fault_id, split_type, COUNT(*) as n_rows,
       COUNTIF(h_z_score IS NOT NULL) as n_local_h,
       ROUND(AVG(kp_max), 2) as avg_kp,
       ROUND(AVG(dst_min), 1) as avg_dst_min
FROM `synexis-project-sentinel.sentinel_features.hgeo_features_final`
GROUP BY 1,2 ORDER BY 1,2;
*/
