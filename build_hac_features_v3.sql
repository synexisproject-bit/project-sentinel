
CREATE OR REPLACE TABLE `synexis-project-sentinel.hac_intake.hac_features_daily`
AS

WITH base AS (
  SELECT
    n.submission_id,
    n.experience_date                                     AS feature_date,
    n.source_name,
    COALESCE(e.water_imagery,       FALSE)                AS water_imagery,
    COALESCE(e.geophysical_imagery, FALSE)                AS geophysical_imagery,
    COALESCE(e.destruction_imagery, FALSE)                AS destruction_imagery,
    CASE WHEN e.urgency_level IN ("high","critical")
         THEN TRUE ELSE FALSE END                         AS high_urgency,
    CASE WHEN n.emotional_intensity >= 7
         THEN TRUE ELSE FALSE END                         AS high_emotion
  FROM `synexis-project-sentinel.hac_intake.hac_normalized` n
  LEFT JOIN `synexis-project-sentinel.hac_intake.hac_enrichment` e
    ON n.submission_id = e.submission_id
  WHERE n.is_sentinel_eligible = TRUE
    AND n.experience_date IS NOT NULL
    AND n.is_duplicate = FALSE
),

daily_counts AS (
  SELECT
    source_name,
    feature_date,
    COUNT(*)                     AS n_total,
    COUNTIF(water_imagery)       AS n_water,
    COUNTIF(high_urgency)        AS n_urgency,
    COUNTIF(high_emotion)        AS n_emotion,
    COUNTIF(destruction_imagery) AS n_destruction
  FROM base
  GROUP BY source_name, feature_date
),

source_stats AS (
  SELECT
    source_name,
    AVG(n_water / NULLIF(n_total,0))          AS mu_water,
    STDDEV(n_water / NULLIF(n_total,0))       AS sd_water,
    AVG(n_urgency / NULLIF(n_total,0))        AS mu_urgency,
    STDDEV(n_urgency / NULLIF(n_total,0))     AS sd_urgency,
    AVG(n_emotion / NULLIF(n_total,0))        AS mu_emotion,
    STDDEV(n_emotion / NULLIF(n_total,0))     AS sd_emotion,
    AVG(n_destruction / NULLIF(n_total,0))    AS mu_destruction,
    STDDEV(n_destruction / NULLIF(n_total,0)) AS sd_destruction
  FROM daily_counts
  GROUP BY source_name
),

record_features AS (
  SELECT b.submission_id, b.feature_date, b.source_name,
    "water_imagery" AS feature_name,
    CAST(b.water_imagery AS INT64) AS feature_value,
    SAFE_DIVIDE(d.n_water/NULLIF(d.n_total,0) - s.mu_water, s.sd_water) AS z_score
  FROM base b
  JOIN daily_counts d ON b.source_name = d.source_name AND b.feature_date = d.feature_date
  JOIN source_stats s ON b.source_name = s.source_name
  UNION ALL
  SELECT b.submission_id, b.feature_date, b.source_name,
    "high_urgency",
    CAST(b.high_urgency AS INT64),
    SAFE_DIVIDE(d.n_urgency/NULLIF(d.n_total,0) - s.mu_urgency, s.sd_urgency)
  FROM base b
  JOIN daily_counts d ON b.source_name = d.source_name AND b.feature_date = d.feature_date
  JOIN source_stats s ON b.source_name = s.source_name
  UNION ALL
  SELECT b.submission_id, b.feature_date, b.source_name,
    "high_emotion",
    CAST(b.high_emotion AS INT64),
    SAFE_DIVIDE(d.n_emotion/NULLIF(d.n_total,0) - s.mu_emotion, s.sd_emotion)
  FROM base b
  JOIN daily_counts d ON b.source_name = d.source_name AND b.feature_date = d.feature_date
  JOIN source_stats s ON b.source_name = s.source_name
  UNION ALL
  SELECT b.submission_id, b.feature_date, b.source_name,
    "destruction_imagery",
    CAST(b.destruction_imagery AS INT64),
    SAFE_DIVIDE(d.n_destruction/NULLIF(d.n_total,0) - s.mu_destruction, s.sd_destruction)
  FROM base b
  JOIN daily_counts d ON b.source_name = d.source_name AND b.feature_date = d.feature_date
  JOIN source_stats s ON b.source_name = s.source_name
)

SELECT
  submission_id,
  feature_date,
  source_name,
  feature_name,
  feature_value,
  z_score,
  CURRENT_TIMESTAMP() AS computed_at
FROM record_features
WHERE z_score IS NOT NULL
ORDER BY feature_date, source_name, feature_name, submission_id;
