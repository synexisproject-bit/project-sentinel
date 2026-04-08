-- ============================================================
-- H1 STEP 3: Build binary target labels
-- Project Sentinel Phase 2
--
-- Label definition (pre-registered):
--   y = 1 if M≥6.5 event occurs within fault bounding box
--       within the NEXT 7 days (D+1 through D+7)
--   y = 0 otherwise
--
-- Strict forward label: features on date D use only data
-- available before D. Label looks forward from D.
-- ============================================================

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.h1_labels` AS

WITH

-- Get all target events (M≥6.5, depth ≤70km) per fault system
target_events AS (
  SELECT
    fault_id,
    event_date,
    magnitude,
    depth_km,
    latitude,
    longitude
  FROM `synexis-project-sentinel.sentinel_features.fault_events`
  WHERE magnitude >= 6.5
    AND depth_km <= 70.0  -- shallow events only (crustal coupling hypothesis)
),

-- For each (date, fault_id) in the spine, check if any target event
-- occurs in the next 1, 3, 5, or 7 days
labeled_spine AS (
  SELECT
    spine.date_val,
    spine.fault_id,

    -- Primary label: M≥6.5 in next 7 days (D+1 through D+7)
    MAX(CASE
      WHEN te.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                              AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
      THEN 1 ELSE 0
    END) AS label_7d,

    -- Additional lag window labels (for exploratory analysis)
    MAX(CASE
      WHEN te.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                              AND DATE_ADD(spine.date_val, INTERVAL 3 DAY)
      THEN 1 ELSE 0
    END) AS label_3d,

    MAX(CASE
      WHEN te.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                              AND DATE_ADD(spine.date_val, INTERVAL 5 DAY)
      THEN 1 ELSE 0
    END) AS label_5d,

    -- Count of target events in each window (for analysis)
    COUNTIF(
      te.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                        AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
    ) AS target_event_count_7d,

    -- Largest event in next 7 days
    MAX(CASE
      WHEN te.event_date BETWEEN DATE_ADD(spine.date_val, INTERVAL 1 DAY)
                              AND DATE_ADD(spine.date_val, INTERVAL 7 DAY)
      THEN te.magnitude ELSE NULL
    END) AS max_upcoming_magnitude

  FROM `synexis-project-sentinel.sentinel_features.fault_date_spine` spine
  LEFT JOIN target_events te
    ON spine.fault_id = te.fault_id
  GROUP BY spine.date_val, spine.fault_id
)

SELECT
  date_val,
  fault_id,
  label_7d,       -- PRIMARY LABEL for H1
  label_3d,
  label_5d,
  target_event_count_7d,
  max_upcoming_magnitude,
  CASE
    WHEN date_val <= '2018-12-31' THEN 'train'
    WHEN date_val <= '2022-12-31' THEN 'val'
    ELSE 'test'
  END AS data_split
FROM labeled_spine
WHERE date_val >= DATE_ADD('2001-01-01', INTERVAL 365 DAY)
ORDER BY fault_id, date_val;

-- ── Verify label rates ────────────────────────────────────────────────────
-- These should roughly match the pre-registered positive label rate (~4%)
-- Lower is expected for fault-specific vs global

SELECT
  fault_id,
  data_split,
  COUNT(*)                          AS total_days,
  SUM(label_7d)                     AS positive_labels,
  ROUND(AVG(label_7d) * 100, 2)    AS positive_rate_pct,
  SUM(label_3d)                     AS positive_labels_3d,
  SUM(label_5d)                     AS positive_labels_5d
FROM `synexis-project-sentinel.sentinel_features.h1_labels`
GROUP BY fault_id, data_split
ORDER BY fault_id, data_split;
