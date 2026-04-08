-- ============================================================
-- H1 STEP 1: Create fault system bounding box reference table
-- Project Sentinel Phase 2
-- Run in: BigQuery console or bq CLI
-- Dataset: sentinel_features
-- ============================================================
-- NOTE: If sentinel_features dataset doesn't exist yet, create it first:
-- CREATE SCHEMA IF NOT EXISTS `synexis-project-sentinel.sentinel_features`;
-- ============================================================

CREATE OR REPLACE TABLE `synexis-project-sentinel.sentinel_features.fault_systems` AS

SELECT * FROM UNNEST([
  STRUCT(
    'japan_trench'    AS fault_id,
    'Japan Trench'    AS fault_name,
    35.0              AS lat_min,
    45.0              AS lat_max,
    140.0             AS lon_min,
    145.0             AS lon_max,
    1                 AS priority,
    'subduction'      AS tectonic_setting,
    'M9.1 Tohoku 2011; densest GPS + ionosonde network globally' AS notes
  ),
  STRUCT(
    'cascadia',
    'Cascadia Subduction Zone',
    40.0, 50.0,
    -125.0, -110.0,  -- lon in degrees (-180 to 180)
    1,
    'subduction',
    'PBO GPS network; ~14-month slow-slip cycle documented'
  ),
  STRUCT(
    'central_chile',
    'Central Chile',
    -40.0, -30.0,
    -75.0, -65.0,
    2,
    'subduction',
    'M8.8 Maule 2010; rich catalog'
  ),
  STRUCT(
    'north_anatolian',
    'North Anatolian Fault',
    38.0, 42.0,
    28.0, 42.0,
    2,
    'strike_slip',
    'M7.6 Izmit 1999; different tectonic setting from subduction faults'
  ),
  STRUCT(
    'sumatra_andaman',
    'Sumatra-Andaman',
    0.0, 15.0,
    92.0, 100.0,
    2,
    'subduction',
    'M9.1 Indian Ocean 2004; key for H5 large event set'
  )
]);

-- Verify
SELECT fault_id, fault_name, lat_min, lat_max, lon_min, lon_max
FROM `synexis-project-sentinel.sentinel_features.fault_systems`
ORDER BY priority, fault_id;
