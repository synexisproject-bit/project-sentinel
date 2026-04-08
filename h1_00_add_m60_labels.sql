-- ============================================================
-- Amendment #1: Add M≥6.0 label column for Cascadia and
-- North Anatolian fault systems
-- Project Sentinel Phase 2
-- Commit: 496ebf1
-- ============================================================
-- This adds label_7d_m60 to h1_labels table — same structure
-- as label_7d but using M≥6.0 threshold instead of M≥6.5
-- ============================================================

-- Step 1: Create M≥6.0 target events table
CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.fault_events_m60` AS

SELECT
  fault_id,
  event_date,
  magnitude,
  depth_km,
  latitude,
  longitude
FROM `synexis-project-sentinel.sentinel_features.fault_events`
WHERE magnitude >= 6.0
  AND depth_km <= 70.0;

-- Verify counts
SELECT
  fault_id,
  COUNT(*) AS events_m60,
  COUNTIF(magnitude >= 6.5) AS events_m65
FROM `synexis-project-sentinel.sentinel_features.fault_events_m60`
GROUP BY fault_id
ORDER BY fault_id;

-- Step 2: Rebuild h1_labels with additional label_7d_m60 column
CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h1_labels` AS

WITH

-- Original M≥6.5 target events
target_m65 AS (
  SELECT fault_id, event_date, magnitude
  FROM `synexis-project-sentinel.sentinel_features.fault_events`
  WHERE magnitude >= 6.5 AND depth_km <= 70.0
),

-- New M≥6.0 target events
target_m60 AS (
  SELECT fault_id, event_date, magnitude
  FROM `synexis-project-sentinel.sentinel_features.fault_events`
  WHERE magnitude >= 6.0 AND depth_km <= 70.0
),

labeled_spine AS (
  SELECT
    spine.date_val,
    spine.fault_id,

    -- Original M≥6.5 labels (unchanged)
    MAX(CASE
      WHEN t65.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                               AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
      THEN 1 ELSE 0
    END) AS label_7d,

    MAX(CASE
      WHEN t65.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                               AND DATE_ADD(spine.date_val, INTERVAL 3 DAY)
      THEN 1 ELSE 0
    END) AS label_3d,

    MAX(CASE
      WHEN t65.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                               AND DATE_ADD(spine.date_val, INTERVAL 5 DAY)
      THEN 1 ELSE 0
    END) AS label_5d,

    COUNTIF(
      t65.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                         AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
    ) AS target_event_count_7d,

    MAX(CASE
      WHEN t65.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                               AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
      THEN t65.magnitude ELSE NULL
    END) AS max_upcoming_magnitude,

    -- NEW: M≥6.0 label for Cascadia and North Anatolian (Amendment #1)
    MAX(CASE
      WHEN t60.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                               AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
      THEN 1 ELSE 0
    END) AS label_7d_m60,

    MAX(CASE
      WHEN t60.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                               AND DATE_ADD(spine.date_val, INTERVAL 5 DAY)
      THEN 1 ELSE 0
    END) AS label_5d_m60,

    COUNTIF(
      t60.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                         AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
    ) AS target_event_count_7d_m60

  FROM `synexis-project-sentinel.sentinel_features.fault_date_spine` spine
  LEFT JOIN target_m65 t65
    ON spine.fault_id = t65.fault_id
  LEFT JOIN target_m60 t60
    ON spine.fault_id = t60.fault_id
  GROUP BY spine.date_val, spine.fault_id
)

SELECT
  date_val,
  fault_id,
  label_7d,
  label_3d,
  label_5d,
  label_7d_m60,
  label_5d_m60,
  target_event_count_7d,
  target_event_count_7d_m60,
  max_upcoming_magnitude,
  CASE
    WHEN date_val <= '2018-12-31' THEN 'train'
    WHEN date_val <= '2022-12-31' THEN 'val'
    ELSE 'test'
  END AS data_split
FROM labeled_spine
WHERE date_val >= DATE_ADD('2001-01-01', INTERVAL 365 DAY)
ORDER BY fault_id, date_val;

-- Verify — compare M≥6.5 vs M≥6.0 event counts per fault system
SELECT
  fault_id,
  SUM(label_7d)     AS total_positive_m65,
  SUM(label_7d_m60) AS total_positive_m60,
  ROUND(SUM(label_7d_m60) / NULLIF(SUM(label_7d), 0), 2) AS m60_multiplier
FROM `synexis-project-sentinel.sentinel_features.h1_labels`
GROUP BY fault_id
ORDER BY fault_id;
