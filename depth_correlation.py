#!/usr/bin/env python3
"""Project Sentinel — Depth-Stratified Correlation Analysis"""

import json
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
client  = bigquery.Client(project=PROJECT)

P1   = f"`{PROJECT}.sentinel_eval.phase1_dataset`"
EQ   = f"`{PROJECT}.sentinel_groundtruth.master_earthquakes`"

SUBDUCTION_KEYS = "'-10_100','-10_110','-10_120','-10_125','-10_130','-10_140','-10_145','-10_150','-10_155','-10_160','-10_165','-10_95','-20_165','-20_170','-20_175','-20_180','-20_185','-30_175','-30_180','-30_185','-30_190','-40_175','-40_180','-40_185','-40_190','-40_285','-40_290','-50_285','-50_290','-50_295','0_100','0_120','0_125','0_130','0_140','10_120','10_125','10_130','20_120','20_125','30_130','30_135','30_140','35_135','35_140','40_130','40_135','40_140','45_145','45_150','50_150','50_155','50_160','55_160','55_165','60_165','0_275','-10_285','-10_290','-20_285'"

def run(sql, label=""):
    print(f"  Running: {label}...")
    return [dict(row) for row in client.query(sql).result()]

def clean(row):
    return {k: (float(v) if v is not None and not isinstance(v, str) else v)
            for k, v in row.items()}

# eq_train: one row per M6+ event with depth band and region_key
# Join to phase1_dataset (which already has region_key + env features)
# to build depth-stratified labels per region-day
BASE_CTE = f"""
WITH eq_train AS (
    SELECT
        DATE(time) AS eq_day,
        CONCAT(
            CAST(CAST(FLOOR(latitude  / 10) * 10 AS INT64) AS STRING), '_',
            CAST(CAST(FLOOR(longitude / 10) * 10 AS INT64) AS STRING)
        ) AS eq_region,
        CASE
            WHEN depth_km < 70  THEN 'shallow'
            WHEN depth_km < 300 THEN 'intermediate'
            ELSE                     'deep'
        END AS depth_band
    FROM {EQ}
    WHERE magnitude >= 6.0
      AND DATE(time) BETWEEN '2001-01-01' AND '2018-12-31'
      AND depth_km IS NOT NULL
      AND latitude IS NOT NULL AND longitude IS NOT NULL
),
depth_labels AS (
    SELECT
        p.day,
        p.region_key,
        p.kp_max,
        p.sw_bz_min,
        p.sw_speed_mean,
        p.tec_global_mean,
        p.tec_anomaly_zscore,
        MAX(CASE WHEN q.depth_band = 'shallow'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_shallow,
        MAX(CASE WHEN q.depth_band = 'intermediate'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_intermediate,
        MAX(CASE WHEN q.depth_band = 'deep'
            AND q.eq_day BETWEEN p.day AND DATE_ADD(p.day, INTERVAL 6 DAY)
            AND q.eq_region = p.region_key THEN 1 ELSE 0 END) AS y_deep
    FROM {P1} p
    LEFT JOIN eq_train q ON q.eq_region = p.region_key
    WHERE p.split = 'train'
    GROUP BY p.day, p.region_key, p.kp_max, p.sw_bz_min, p.sw_speed_mean,
             p.tec_global_mean, p.tec_anomaly_zscore
)
"""

results = {}

# 1. Positive rates
print("\n[1] Positive rates by depth band (train set)")
rows = run(BASE_CTE + """
SELECT 'shallow'      AS band, COUNT(*) AS n, SUM(y_shallow)      AS pos, AVG(CAST(y_shallow      AS FLOAT64)) AS rate FROM depth_labels UNION ALL
SELECT 'intermediate' AS band, COUNT(*) AS n, SUM(y_intermediate) AS pos, AVG(CAST(y_intermediate AS FLOAT64)) AS rate FROM depth_labels UNION ALL
SELECT 'deep'         AS band, COUNT(*) AS n, SUM(y_deep)         AS pos, AVG(CAST(y_deep         AS FLOAT64)) AS rate FROM depth_labels
ORDER BY band
""", "positive rates")
results["pos_rates"] = [clean(r) for r in rows]
for r in results["pos_rates"]:
    print(f"  {r['band']:<14}: N={int(r['n'])}  positives={int(r['pos'])}  rate={r['rate']*100:.2f}%")

# 2. Correlations by depth band
print("\n[2] Correlations by depth band (train set)")
rows = run(BASE_CTE + """
SELECT
    CORR(kp_max,             CAST(y_shallow      AS FLOAT64)) AS kp_shallow,
    CORR(kp_max,             CAST(y_intermediate AS FLOAT64)) AS kp_inter,
    CORR(kp_max,             CAST(y_deep         AS FLOAT64)) AS kp_deep,
    CORR(sw_bz_min,          CAST(y_shallow      AS FLOAT64)) AS bz_shallow,
    CORR(sw_bz_min,          CAST(y_intermediate AS FLOAT64)) AS bz_inter,
    CORR(sw_bz_min,          CAST(y_deep         AS FLOAT64)) AS bz_deep,
    CORR(sw_speed_mean,      CAST(y_shallow      AS FLOAT64)) AS spd_shallow,
    CORR(sw_speed_mean,      CAST(y_intermediate AS FLOAT64)) AS spd_inter,
    CORR(sw_speed_mean,      CAST(y_deep         AS FLOAT64)) AS spd_deep,
    CORR(tec_global_mean,    CAST(y_shallow      AS FLOAT64)) AS tec_mean_shallow,
    CORR(tec_global_mean,    CAST(y_intermediate AS FLOAT64)) AS tec_mean_inter,
    CORR(tec_global_mean,    CAST(y_deep         AS FLOAT64)) AS tec_mean_deep,
    CORR(tec_anomaly_zscore, CAST(y_shallow      AS FLOAT64)) AS tec_anom_shallow,
    CORR(tec_anomaly_zscore, CAST(y_intermediate AS FLOAT64)) AS tec_anom_inter,
    CORR(tec_anomaly_zscore, CAST(y_deep         AS FLOAT64)) AS tec_anom_deep,
    COUNT(*) AS n
FROM depth_labels
""", "depth correlations")
results["depth_correlations"] = clean(rows[0])
r = results["depth_correlations"]
print(f"\n  {'Feature':<22} {'Shallow':>10} {'Intermediate':>14} {'Deep':>10}")
print(f"  {'-'*58}")
for feat, s, i, d in [
    ("kp_max",             "kp_shallow",       "kp_inter",       "kp_deep"),
    ("sw_bz_min",          "bz_shallow",       "bz_inter",       "bz_deep"),
    ("sw_speed_mean",      "spd_shallow",      "spd_inter",      "spd_deep"),
    ("tec_global_mean",    "tec_mean_shallow", "tec_mean_inter", "tec_mean_deep"),
    ("tec_anomaly_zscore", "tec_anom_shallow", "tec_anom_inter", "tec_anom_deep"),
]:
    print(f"  {feat:<22} {r[s]:>+10.4f} {r[i]:>+14.4f} {r[d]:>+10.4f}")

# 3. Subduction zones x depth
print("\n[3] Subduction zones — tec_anomaly x depth (train set)")
rows = run(BASE_CTE + f"""
SELECT
    CORR(tec_anomaly_zscore, CAST(y_shallow      AS FLOAT64)) AS tec_shallow,
    CORR(tec_anomaly_zscore, CAST(y_intermediate AS FLOAT64)) AS tec_inter,
    CORR(tec_anomaly_zscore, CAST(y_deep         AS FLOAT64)) AS tec_deep,
    AVG(CAST(y_shallow      AS FLOAT64)) AS rate_shallow,
    AVG(CAST(y_intermediate AS FLOAT64)) AS rate_inter,
    AVG(CAST(y_deep         AS FLOAT64)) AS rate_deep,
    COUNT(*) AS n
FROM depth_labels
WHERE region_key IN ({SUBDUCTION_KEYS})
""", "subduction x depth")
results["subduction_depth"] = clean(rows[0])
r = results["subduction_depth"]
print(f"  N={int(r['n'])} region-days in subduction zones")
print(f"  tec_anomaly vs shallow:       r={r['tec_shallow']:+.4f}  pos_rate={r['rate_shallow']:.4f}")
print(f"  tec_anomaly vs intermediate:  r={r['tec_inter']:+.4f}  pos_rate={r['rate_inter']:.4f}")
print(f"  tec_anomaly vs deep:          r={r['tec_deep']:+.4f}  pos_rate={r['rate_deep']:.4f}")

with open("depth_correlation_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print("\nSaved: depth_correlation_results.json")
