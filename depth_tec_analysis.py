#!/usr/bin/env python3
"""
Phase 2 prep — Depth-stratified TEC correlation analysis
Tests whether tec_anomaly_zscore correlates differently with
shallow vs intermediate vs deep M6+ events, with finer depth bins.
"""
import json
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
client  = bigquery.Client(project=PROJECT)
P1 = f"`{PROJECT}.sentinel_eval.phase1_dataset`"
EQ = f"`{PROJECT}.sentinel_groundtruth.master_earthquakes`"

def run(sql, label=""):
    print(f"  Running: {label}...")
    return [dict(row) for row in client.query(sql).result()]

def clean(row):
    return {k: (float(v) if v is not None and not isinstance(v, str) else v)
            for k, v in row.items()}

BASE_CTE = f"""
WITH eq_train AS (
    SELECT
        DATE(time) AS eq_day,
        CONCAT(
            CAST(CAST(FLOOR(latitude  / 10) * 10 AS INT64) AS STRING), '_',
            CAST(CAST(FLOOR(longitude / 10) * 10 AS INT64) AS STRING)
        ) AS eq_region,
        depth_km,
        CASE
            WHEN depth_km <  20 THEN 'very_shallow (0-20km)'
            WHEN depth_km <  70 THEN 'shallow (20-70km)'
            WHEN depth_km < 150 THEN 'intermediate_upper (70-150km)'
            WHEN depth_km < 300 THEN 'intermediate_lower (150-300km)'
            ELSE                     'deep (300km+)'
        END AS depth_band
    FROM {EQ}
    WHERE magnitude >= 6.0
      AND DATE(time) BETWEEN '2001-01-01' AND '2018-12-31'
      AND depth_km IS NOT NULL
      AND latitude IS NOT NULL AND longitude IS NOT NULL
),
depth_labels AS (
    SELECT
        p.day, p.region_key,
        p.tec_anomaly_zscore,
        p.tec_global_mean,
        p.kp_max,
        MAX(CASE WHEN q.depth_band = 'very_shallow (0-20km)'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_vshallow,
        MAX(CASE WHEN q.depth_band = 'shallow (20-70km)'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_shallow,
        MAX(CASE WHEN q.depth_band = 'intermediate_upper (70-150km)'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_inter_upper,
        MAX(CASE WHEN q.depth_band = 'intermediate_lower (150-300km)'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_inter_lower,
        MAX(CASE WHEN q.depth_band = 'deep (300km+)'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_deep
    FROM {P1} p
    LEFT JOIN eq_train q ON q.eq_region = p.region_key
    WHERE p.split = 'train'
    GROUP BY p.day, p.region_key, p.tec_anomaly_zscore,
             p.tec_global_mean, p.kp_max
)
"""

results = {}

# 1. Event counts and positive rates by fine depth band
print("\n[1] Event distribution — fine depth bands (train set)")
rows = run(f"""
SELECT
    CASE
        WHEN depth_km <  20 THEN 'very_shallow (0-20km)'
        WHEN depth_km <  70 THEN 'shallow (20-70km)'
        WHEN depth_km < 150 THEN 'intermediate_upper (70-150km)'
        WHEN depth_km < 300 THEN 'intermediate_lower (150-300km)'
        ELSE                     'deep (300km+)'
    END AS depth_band,
    COUNT(*) AS n_events,
    ROUND(AVG(depth_km), 1) AS avg_depth_km
FROM {EQ}
WHERE magnitude >= 6.0
  AND DATE(time) BETWEEN '2001-01-01' AND '2018-12-31'
  AND depth_km IS NOT NULL
GROUP BY depth_band ORDER BY MIN(depth_km)
""", "event distribution")
results["event_distribution"] = [clean(r) for r in rows]
for r in results["event_distribution"]:
    print(f"  {r['depth_band']:<32}: {int(r['n_events'])} events  avg={r['avg_depth_km']:.1f}km")

# 2. TEC anomaly correlations by fine depth band
print("\n[2] TEC anomaly correlations — fine depth bands")
rows = run(BASE_CTE + """
SELECT
    CORR(tec_anomaly_zscore, CAST(y_vshallow     AS FLOAT64)) AS r_vshallow,
    CORR(tec_anomaly_zscore, CAST(y_shallow       AS FLOAT64)) AS r_shallow,
    CORR(tec_anomaly_zscore, CAST(y_inter_upper   AS FLOAT64)) AS r_inter_upper,
    CORR(tec_anomaly_zscore, CAST(y_inter_lower   AS FLOAT64)) AS r_inter_lower,
    CORR(tec_anomaly_zscore, CAST(y_deep          AS FLOAT64)) AS r_deep,
    CORR(kp_max,             CAST(y_vshallow      AS FLOAT64)) AS kp_vshallow,
    CORR(kp_max,             CAST(y_shallow        AS FLOAT64)) AS kp_shallow,
    CORR(kp_max,             CAST(y_inter_upper    AS FLOAT64)) AS kp_inter_upper,
    CORR(kp_max,             CAST(y_inter_lower    AS FLOAT64)) AS kp_inter_lower,
    CORR(kp_max,             CAST(y_deep           AS FLOAT64)) AS kp_deep,
    AVG(CAST(y_vshallow     AS FLOAT64)) AS rate_vshallow,
    AVG(CAST(y_shallow       AS FLOAT64)) AS rate_shallow,
    AVG(CAST(y_inter_upper   AS FLOAT64)) AS rate_inter_upper,
    AVG(CAST(y_inter_lower   AS FLOAT64)) AS rate_inter_lower,
    AVG(CAST(y_deep          AS FLOAT64)) AS rate_deep,
    COUNT(*) AS n
FROM depth_labels
""", "TEC x fine depth")
results["fine_depth_corr"] = clean(rows[0])
r = results["fine_depth_corr"]
print(f"\n  {'Depth Band':<32} {'r(tec_anom)':>12} {'r(kp_max)':>10} {'pos_rate':>10}")
print(f"  {'-'*66}")
bands = [
    ("very_shallow (0-20km)",          "r_vshallow",    "kp_vshallow",    "rate_vshallow"),
    ("shallow (20-70km)",              "r_shallow",     "kp_shallow",     "rate_shallow"),
    ("intermediate_upper (70-150km)",  "r_inter_upper", "kp_inter_upper", "rate_inter_upper"),
    ("intermediate_lower (150-300km)", "r_inter_lower", "kp_inter_lower", "rate_inter_lower"),
    ("deep (300km+)",                  "r_deep",        "kp_deep",        "rate_deep"),
]
for label, rt, rk, rr in bands:
    print(f"  {label:<32} {r[rt]:>+12.4f} {r[rk]:>+10.4f} {r[rr]:>10.4f}")

# 3. TEC anomaly vs shallow events — by magnitude threshold
print("\n[3] TEC anomaly vs shallow events — magnitude thresholds")
rows = run(f"""
WITH eq_train AS (
    SELECT DATE(time) AS eq_day,
        CONCAT(
            CAST(CAST(FLOOR(latitude  / 10) * 10 AS INT64) AS STRING), '_',
            CAST(CAST(FLOOR(longitude / 10) * 10 AS INT64) AS STRING)
        ) AS eq_region,
        magnitude
    FROM {EQ}
    WHERE depth_km < 70
      AND DATE(time) BETWEEN '2001-01-01' AND '2018-12-31'
      AND depth_km IS NOT NULL
      AND latitude IS NOT NULL AND longitude IS NOT NULL
),
mag_labels AS (
    SELECT p.day, p.region_key, p.tec_anomaly_zscore,
        MAX(CASE WHEN q.magnitude >= 6.0 AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY) AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_m60,
        MAX(CASE WHEN q.magnitude >= 6.5 AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY) AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_m65,
        MAX(CASE WHEN q.magnitude >= 7.0 AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY) AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_m70
    FROM {P1} p
    LEFT JOIN eq_train q ON q.eq_region = p.region_key
    WHERE p.split = 'train'
    GROUP BY p.day, p.region_key, p.tec_anomaly_zscore
)
SELECT
    CORR(tec_anomaly_zscore, CAST(y_m60 AS FLOAT64)) AS r_m60_shallow,
    CORR(tec_anomaly_zscore, CAST(y_m65 AS FLOAT64)) AS r_m65_shallow,
    CORR(tec_anomaly_zscore, CAST(y_m70 AS FLOAT64)) AS r_m70_shallow,
    AVG(CAST(y_m60 AS FLOAT64)) AS rate_m60,
    AVG(CAST(y_m65 AS FLOAT64)) AS rate_m65,
    AVG(CAST(y_m70 AS FLOAT64)) AS rate_m70,
    COUNT(*) AS n
FROM mag_labels
""", "magnitude thresholds")
results["magnitude_thresholds"] = clean(rows[0])
r = results["magnitude_thresholds"]
print(f"  M6.0+ shallow:  r={r['r_m60_shallow']:+.4f}  rate={r['rate_m60']:.4f}")
print(f"  M6.5+ shallow:  r={r['r_m65_shallow']:+.4f}  rate={r['rate_m65']:.4f}")
print(f"  M7.0+ shallow:  r={r['r_m70_shallow']:+.4f}  rate={r['rate_m70']:.4f}")

with open("depth_tec_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print("\nSaved: depth_tec_results.json")
