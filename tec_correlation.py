#!/usr/bin/env python3
"""Project Sentinel — TEC Correlation Analysis"""

import json
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
PHASE1  = f"`{PROJECT}.sentinel_eval.phase1_dataset`"
client  = bigquery.Client(project=PROJECT)

def run(sql, label=""):
    print(f"  Running: {label}...")
    return [dict(row) for row in client.query(sql).result()]

def to_float(v):
    if v is None or isinstance(v, str):
        return v
    return float(v)

def clean(row):
    return {k: to_float(v) for k, v in row.items()}

results = {}

# 1. Global correlations
print("\n[1] Global correlations (train set)")
rows = run(f"""
SELECT
    CORR(tec_global_mean,    CAST(y_m60_next7d AS FLOAT64)) AS r_tec_mean,
    CORR(tec_anomaly_zscore, CAST(y_m60_next7d AS FLOAT64)) AS r_tec_anomaly,
    COUNT(*) AS n,
    COUNTIF(tec_global_mean IS NOT NULL) AS n_tec_mean,
    COUNTIF(tec_anomaly_zscore IS NOT NULL) AS n_tec_anomaly
FROM {PHASE1} WHERE split = 'train'
""", "global")
results["global"] = clean(rows[0])
g = results["global"]
print(f"  r(tec_mean)={g['r_tec_mean']:.4f}  r(tec_anomaly)={g['r_tec_anomaly']:.4f}  N={int(g['n'])}")

# 2. Solar cycle stratification
print("\n[2] Solar cycle stratification (train set)")
rows = run(f"""
SELECT
    CASE
        WHEN day BETWEEN '2001-01-01' AND '2008-12-31' THEN 'solar_max_23'
        WHEN day BETWEEN '2009-01-01' AND '2011-12-31' THEN 'solar_min_23_24'
        WHEN day BETWEEN '2012-01-01' AND '2015-12-31' THEN 'solar_max_24'
        WHEN day BETWEEN '2016-01-01' AND '2018-12-31' THEN 'solar_min_24_25'
    END AS phase,
    CORR(tec_global_mean,    CAST(y_m60_next7d AS FLOAT64)) AS r_tec_mean,
    CORR(tec_anomaly_zscore, CAST(y_m60_next7d AS FLOAT64)) AS r_tec_anomaly,
    COUNT(*) AS n,
    AVG(CAST(y_m60_next7d AS FLOAT64)) AS pos_rate
FROM {PHASE1} WHERE split = 'train'
GROUP BY phase ORDER BY phase
""", "solar cycle")
results["solar_cycle"] = [clean(r) for r in rows]
for r in results["solar_cycle"]:
    print(f"  {r['phase']}: r_mean={r['r_tec_mean']:.4f}  r_anomaly={r['r_tec_anomaly']:.4f}  N={int(r['n'])}")

# 3. Tectonic stratification
print("\n[3] Tectonic stratification (train set)")
rows = run(f"""
SELECT
    CASE WHEN region_key IN (
        'R_-10_100','R_-10_110','R_-10_120','R_-10_125','R_-10_130',
        'R_-10_140','R_-10_145','R_-10_150','R_-10_155','R_-10_160',
        'R_-10_165','R_-10_95','R_-20_165','R_-20_170','R_-20_175',
        'R_-20_180','R_-20_185','R_-30_175','R_-30_180','R_-30_185',
        'R_-30_190','R_-40_175','R_-40_180','R_-40_185','R_-40_190',
        'R_-40_285','R_-40_290','R_-50_285','R_-50_290','R_-50_295',
        'R_0_100','R_0_120','R_0_125','R_0_130','R_0_140',
        'R_10_120','R_10_125','R_10_130','R_20_120','R_20_125',
        'R_30_130','R_30_135','R_30_140','R_35_135','R_35_140',
        'R_40_130','R_40_135','R_40_140','R_45_145','R_45_150',
        'R_50_150','R_50_155','R_50_160','R_55_160','R_55_165',
        'R_60_165','R_0_275','R_-10_285','R_-10_290','R_-20_285'
    ) THEN 'subduction' ELSE 'other' END AS tectonic,
    CORR(tec_global_mean,    CAST(y_m60_next7d AS FLOAT64)) AS r_tec_mean,
    CORR(tec_anomaly_zscore, CAST(y_m60_next7d AS FLOAT64)) AS r_tec_anomaly,
    COUNT(*) AS n,
    AVG(CAST(y_m60_next7d AS FLOAT64)) AS pos_rate
FROM {PHASE1} WHERE split = 'train'
GROUP BY tectonic ORDER BY tectonic
""", "tectonic")
results["tectonic"] = [clean(r) for r in rows]
for r in results["tectonic"]:
    print(f"  {r['tectonic']}: r_mean={r['r_tec_mean']:.4f}  r_anomaly={r['r_tec_anomaly']:.4f}  N={int(r['n'])}")

# 4. Lag decomposition
print("\n[4] Lag decomposition (train set)")
lag_results = []
for lag in range(1, 8):
    rows = run(f"""
    WITH daily AS (
        SELECT day,
            MAX(tec_global_mean) AS tec_mean,
            MAX(tec_anomaly_zscore) AS tec_anomaly,
            MAX(CAST(y_m60_next7d AS INT64)) AS has_m6
        FROM {PHASE1} WHERE split = 'train' GROUP BY day
    ),
    lagged AS (
        SELECT a.tec_mean, a.tec_anomaly, b.has_m6
        FROM daily a
        JOIN daily b ON DATE_ADD(a.day, INTERVAL {lag} DAY) = b.day
    )
    SELECT {lag} AS lag_day,
        CORR(tec_mean,    CAST(has_m6 AS FLOAT64)) AS r_tec_mean,
        CORR(tec_anomaly, CAST(has_m6 AS FLOAT64)) AS r_tec_anomaly,
        COUNT(*) AS n
    FROM lagged
    """, f"lag D+{lag}")
    d = clean(rows[0])
    lag_results.append(d)
    print(f"  D+{lag}: r_mean={d['r_tec_mean']:.4f}  r_anomaly={d['r_tec_anomaly']:.4f}")
results["lag_decomposition"] = lag_results

# 5. Anomaly threshold analysis
print("\n[5] Anomaly threshold analysis (train set)")
rows = run(f"""
WITH daily AS (
    SELECT day,
        MAX(tec_anomaly_zscore) AS tec_z,
        MAX(CAST(y_m60_next7d AS INT64)) AS has_m6
    FROM {PHASE1}
    WHERE split = 'train' AND tec_anomaly_zscore IS NOT NULL
    GROUP BY day
)
SELECT
    CASE
        WHEN tec_z >= 2.0  THEN 'high_pos (z>=2)'
        WHEN tec_z >= 1.0  THEN 'mod_pos (1<=z<2)'
        WHEN tec_z >= -1.0 THEN 'neutral (-1<=z<1)'
        WHEN tec_z >= -2.0 THEN 'mod_neg (-2<=z<-1)'
        ELSE                    'high_neg (z<-2)'
    END AS tec_anomaly_bin,
    COUNT(*) AS n_days,
    AVG(CAST(has_m6 AS FLOAT64)) AS m6_rate,
    SUM(has_m6) AS n_m6_days
FROM daily
GROUP BY tec_anomaly_bin ORDER BY tec_anomaly_bin
""", "anomaly thresholds")
results["anomaly_thresholds"] = [clean(r) for r in rows]
for r in results["anomaly_thresholds"]:
    print(f"  {r['tec_anomaly_bin']}: N={int(r['n_days'])}  rate={r['m6_rate']:.4f}  M6_days={int(r['n_m6_days'])}")

# Save
with open("tec_correlation_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print("\nSaved to tec_correlation_results.json")
print("\n── SUMMARY ──────────────────────────────────")
print(f"r(tec_mean):    {results['global']['r_tec_mean']:.4f}")
print(f"r(tec_anomaly): {results['global']['r_tec_anomaly']:.4f}")
print(f"Solar/geo max was: r=0.0054 (has_sep)")
