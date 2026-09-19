
WITH qualifying_events AS (
  SELECT
    event_id,
    hazard,
    DATE(start_ts) AS event_date,
    mag,
    lat,
    lon
  FROM `synexis-project-sentinel.sentinel_groundtruth.events`
  WHERE mag >= 6.0
    AND hazard = 'earthquake'
),
epoch_pairs AS (
  SELECT
    e.event_id,
    e.hazard,
    f.feature_date,
    DATE_DIFF(f.feature_date, e.event_date, DAY) AS day_lag,
    f.feature_name,
    f.z_score
  FROM qualifying_events e
  CROSS JOIN `synexis-project-sentinel.hac_intake.hac_features_daily` f
  WHERE DATE_DIFF(f.feature_date, e.event_date, DAY) BETWEEN -7 AND 7
),
aggregated AS (
  SELECT
    hazard AS hazard_type,
    feature_name,
    day_lag,
    COUNT(*) AS n_obs,
    AVG(z_score) AS mean_z,
    STDDEV(z_score) AS std_z,
    AVG(z_score) / NULLIF(STDDEV(z_score) / SQRT(COUNT(*)), 0) AS t_stat
  FROM epoch_pairs
  GROUP BY hazard_type, feature_name, day_lag
)
SELECT * FROM aggregated
ORDER BY ABS(t_stat) DESC
LIMIT 20
