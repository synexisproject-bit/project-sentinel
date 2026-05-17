#!/usr/bin/env python3
"""
H5-Cascade: LAIC Temporal Cascade Ordering Test — Project Sentinel
Tests whether pre-event HAC signal timing is consistent with LAIC
ionospheric cascade window prediction.

Amendment #9 v3 | osf.io/8hvf6
Pre-registered before execution

Pre-specified hypotheses:
  H5-Cascade-1 (primary): Centroid of pre-event HAC signal elevation falls
    within ionospheric LAIC window (day -1 to -5), not thermal (-12 to -20)
    or atmospheric (-5 to -10).
  H5-Cascade-2 (secondary): Day -1 z-score exceeds day -5 z-score for
    urgency and emotion, consistent with intensification approaching mainshock.
  H5-Cascade-3 (secondary): No significant elevation in thermal window
    (day -12 to -20). NOTE: Current data window only reaches day -7.
    H5-Cascade-3 is DEFERRED pending extended SEA re-run to day -20.

LAIC windows:
  Thermal:      day -12 to -20
  Atmospheric:  day -5  to -10
  Ionospheric:  day -1  to -5

Data source: sentinel_analysis.hac_epoch_zscores
  Round 3 (clean deduplicated corpus, commit a50515b) identified by
  run_at_utc >= '2026-04-13' (hac_epoch_round3.log, April 13 2026)
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT      = "synexis-project-sentinel"
SOURCE_TABLE = "sentinel_analysis.hac_epoch_zscores"
RESULT_TABLE = "sentinel_eval.h5_cascade_results"

# LAIC window definitions (pre-registered)
LAIC_WINDOWS = {
    "ionospheric": (-5, -1),    # primary prediction window
    "atmospheric": (-10, -5),   # intermediate window
    "thermal":     (-20, -12),  # earliest window — data not available
}

# Primary features (pre-registered)
PRIMARY_METRICS   = ["high_emotion", "high_urgency"]
SECONDARY_METRICS = ["water"]

# Round 3 filter
ROUND3_CUTOFF = "2026-04-13"

# Bootstrap parameters
N_PERMUTATIONS = 2000
SIGNIFICANCE   = 0.05


def load_round3_zscores(client):
    """Load Round 3 global SEA z-scores from BQ."""
    query = f"""
    SELECT rel_day, metric, zscore, p_value_onetail, n_events, n_obs
    FROM `{PROJECT}.{SOURCE_TABLE}`
    WHERE fault_id = 'global'
      AND run_at_utc >= '{ROUND3_CUTOFF}'
      AND zscore IS NOT NULL
    ORDER BY metric, rel_day
    """
    df = client.query(query).to_dataframe()
    print(f"  Loaded {len(df):,} Round 3 rows")
    print(f"  Metrics: {sorted(df['metric'].unique())}")
    print(f"  Day range: {df['rel_day'].min()} to {df['rel_day'].max()}")
    return df


def compute_weighted_centroid(df, metric, pre_window=(-7, -1)):
    """
    Compute z-score-weighted mean epoch day over pre-event window.
    Returns centroid day and bootstrap CI.
    """
    subset = df[
        (df["metric"] == metric) &
        (df["rel_day"] >= pre_window[0]) &
        (df["rel_day"] <= pre_window[1]) &
        (df["zscore"] > 0)  # only positive z-scores contribute
    ].copy()

    if len(subset) == 0:
        return None, None, None, "NO_POSITIVE_DAYS"

    days    = subset["rel_day"].values.astype(float)
    weights = np.maximum(subset["zscore"].values, 0)

    if weights.sum() == 0:
        return None, None, None, "ZERO_WEIGHTS"

    centroid = float(np.average(days, weights=weights))

    # Bootstrap CI on centroid
    centroids = []
    for _ in range(N_PERMUTATIONS):
        idx = np.random.choice(len(days), len(days), replace=True)
        w   = weights[idx]
        if w.sum() > 0:
            centroids.append(np.average(days[idx], weights=w))

    ci_lower = float(np.percentile(centroids, 2.5))
    ci_upper = float(np.percentile(centroids, 97.5))

    return centroid, ci_lower, ci_upper, "OK"


def classify_centroid(centroid):
    """Classify centroid into LAIC window."""
    if centroid is None:
        return "UNKNOWN"
    low_iono, high_iono = LAIC_WINDOWS["ionospheric"]
    low_atm,  high_atm  = LAIC_WINDOWS["atmospheric"]
    low_thm,  high_thm  = LAIC_WINDOWS["thermal"]

    if low_iono <= centroid <= high_iono:
        return "IONOSPHERIC"
    elif low_atm <= centroid <= high_atm:
        return "ATMOSPHERIC"
    elif low_thm <= centroid <= high_thm:
        return "THERMAL"
    else:
        return f"OUTSIDE_WINDOWS ({centroid:.2f})"


def test_cascade_1(df, metrics):
    """
    H5-Cascade-1: Centroid falls in ionospheric window (-1 to -5).
    """
    print(f"\n{'='*60}")
    print("H5-CASCADE-1: Centroid Window Classification")
    print(f"{'='*60}")
    results = {}

    for metric in metrics:
        centroid, ci_lo, ci_hi, status = compute_weighted_centroid(
            df, metric, pre_window=(-7, -1)
        )
        window = classify_centroid(centroid)
        confirmed = window == "IONOSPHERIC"

        print(f"\n  {metric}:")
        if centroid is not None:
            print(f"    Centroid: day {centroid:.3f}  CI:[{ci_lo:.3f}, {ci_hi:.3f}]")
            print(f"    Window classification: {window}")
            print(f"    H5-Cascade-1 for {metric}: {'CONFIRMED' if confirmed else 'NULL'}")
        else:
            print(f"    Status: {status}")

        results[metric] = {
            "centroid": centroid,
            "ci_lower": ci_lo,
            "ci_upper": ci_hi,
            "window_classification": window,
            "confirmed": confirmed,
            "status": status
        }

    # Primary outcome: both primary metrics confirmed
    primary_confirmed = all(
        results[m]["confirmed"] for m in PRIMARY_METRICS if m in results
    )
    print(f"\n  H5-Cascade-1 PRIMARY OUTCOME: "
          f"{'CONFIRMED' if primary_confirmed else 'NULL'}")
    print(f"  (Requires both high_emotion and high_urgency centroid in ionospheric window)")

    return results, primary_confirmed


def test_cascade_2(df):
    """
    H5-Cascade-2: Day -1 z-score > day -5 z-score (intensification pattern).
    """
    print(f"\n{'='*60}")
    print("H5-CASCADE-2: Day -1 > Day -5 Intensification Pattern")
    print(f"{'='*60}")
    results = {}

    for metric in PRIMARY_METRICS + SECONDARY_METRICS:
        day_neg1 = df[(df["metric"] == metric) & (df["rel_day"] == -1)]["zscore"]
        day_neg5 = df[(df["metric"] == metric) & (df["rel_day"] == -5)]["zscore"]

        if len(day_neg1) == 0 or len(day_neg5) == 0:
            print(f"\n  {metric}: MISSING DATA")
            results[metric] = {"confirmed": None, "status": "MISSING_DATA"}
            continue

        z_neg1 = float(day_neg1.mean())
        z_neg5 = float(day_neg5.mean())
        confirmed = z_neg1 > z_neg5

        print(f"\n  {metric}:")
        print(f"    Day -1 z-score: {z_neg1:.4f}")
        print(f"    Day -5 z-score: {z_neg5:.4f}")
        print(f"    Day -1 > Day -5: {confirmed}")
        print(f"    H5-Cascade-2 for {metric}: {'CONFIRMED' if confirmed else 'NULL'}")

        results[metric] = {
            "z_neg1": z_neg1,
            "z_neg5": z_neg5,
            "confirmed": confirmed,
            "status": "OK"
        }

    primary_confirmed = all(
        results.get(m, {}).get("confirmed", False) for m in PRIMARY_METRICS
    )
    print(f"\n  H5-Cascade-2 PRIMARY OUTCOME: "
          f"{'CONFIRMED' if primary_confirmed else 'NULL'}")

    return results, primary_confirmed


def print_day_by_day(df):
    """Print day-by-day z-score profile for primary metrics."""
    print(f"\n{'='*60}")
    print("Pre-event z-score profile (Round 3 global, pre-window)")
    print(f"{'='*60}")

    for metric in PRIMARY_METRICS + SECONDARY_METRICS:
        subset = df[
            (df["metric"] == metric) &
            (df["rel_day"] >= -7) &
            (df["rel_day"] <= 0)
        ].sort_values("rel_day")

        if len(subset) == 0:
            continue

        print(f"\n  {metric}:")
        print(f"    {'Day':>5}  {'Z-score':>8}  {'p (one-tail)':>12}  Window")
        print(f"    {'-'*45}")

        for _, row in subset.iterrows():
            day  = int(row["rel_day"])
            z    = row["zscore"]
            p    = row["p_value_onetail"]
            sig  = "*" if p <= SIGNIFICANCE else " "

            # Classify day into LAIC window
            if -5 <= day <= -1:
                win = "IONOSPHERIC"
            elif -10 <= day <= -5:
                win = "ATMOSPHERIC"
            else:
                win = ""

            print(f"    {day:>5}  {z:>8.4f}  {p:>12.4f} {sig} {win}")


def save_results(client, cascade1_results, cascade1_confirmed,
                 cascade2_results, cascade2_confirmed, df):
    """Save cascade results to BQ."""
    # Build summary record
    rows = []
    for metric in PRIMARY_METRICS + SECONDARY_METRICS:
        c1 = cascade1_results.get(metric, {})
        c2 = cascade2_results.get(metric, {})

        # Get day -1 and day -5 z-scores
        z_neg1_vals = df[(df["metric"] == metric) & (df["rel_day"] == -1)]["zscore"]
        z_neg5_vals = df[(df["metric"] == metric) & (df["rel_day"] == -5)]["zscore"]
        z_neg7_vals = df[(df["metric"] == metric) & (df["rel_day"] == -7)]["zscore"]

        rows.append({
            "metric":                  metric,
            "is_primary":             1 if metric in PRIMARY_METRICS else 0,
            "centroid_day":            c1.get("centroid"),
            "centroid_ci_lower":       c1.get("ci_lower"),
            "centroid_ci_upper":       c1.get("ci_upper"),
            "window_classification":   c1.get("window_classification"),
            "cascade1_confirmed":      1 if c1.get("confirmed") else 0,
            "z_day_neg1":             float(z_neg1_vals.mean()) if len(z_neg1_vals) > 0 else None,
            "z_day_neg5":             float(z_neg5_vals.mean()) if len(z_neg5_vals) > 0 else None,
            "z_day_neg7":             float(z_neg7_vals.mean()) if len(z_neg7_vals) > 0 else None,
            "cascade2_confirmed":      1 if c2.get("confirmed") else 0,
            "cascade3_status":         "DEFERRED_WINDOW_EXTENSION_REQUIRED",
            "run_timestamp":           datetime.now(timezone.utc).isoformat(),
            "data_source":             "hac_epoch_zscores Round3 (run_at_utc>=2026-04-13)",
            "amendment_commit":        "c8cbf9c",
            "permutation_iters":       N_PERMUTATIONS,
            "cascade1_primary_verdict":"CONFIRMED" if cascade1_confirmed else "NULL",
            "cascade2_primary_verdict":"CONFIRMED" if cascade2_confirmed else "NULL",
        })

    bq_df = pd.DataFrame(rows)
    job = client.load_table_from_dataframe(
        bq_df, f"{PROJECT}.{RESULT_TABLE}",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    )
    job.result()
    print(f"\nResults saved to {PROJECT}.{RESULT_TABLE}")


def main():
    print(f"{'='*60}")
    print(f"Project Sentinel H5-Cascade Analysis")
    print(f"LAIC Temporal Cascade Ordering Test")
    print(f"Amendment #9 v3 | osf.io/8hvf6")
    print(f"Run: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")

    client = bigquery.Client(project=PROJECT)

    # Load Round 3 data
    print("\nLoading Round 3 z-scores...")
    df = load_round3_zscores(client)

    if len(df) == 0:
        print("ERROR: No data found for Round 3")
        return

    # Print day-by-day profile
    print_day_by_day(df)

    # H5-Cascade-1
    c1_results, c1_confirmed = test_cascade_1(
        df, PRIMARY_METRICS + SECONDARY_METRICS
    )

    # H5-Cascade-2
    c2_results, c2_confirmed = test_cascade_2(df)

    # H5-Cascade-3 — deferred
    print(f"\n{'='*60}")
    print("H5-CASCADE-3: Thermal Window (-12 to -20 days)")
    print(f"{'='*60}")
    print("  STATUS: DEFERRED")
    print("  Current data window: day -7 to day +7")
    print("  Required window: day -20 to day +7")
    print("  Action required: re-run hac_superposed_epoch.py with")
    print("  epoch_window=(-20, 7) to extend the pre-event window")
    print("  to capture the LAIC thermal anomaly zone.")

    # Overall summary
    print(f"\n{'='*60}")
    print("H5-CASCADE SUMMARY")
    print(f"{'='*60}")
    print(f"  H5-Cascade-1 (centroid in ionospheric window): "
          f"{'CONFIRMED' if c1_confirmed else 'NULL'}")
    print(f"  H5-Cascade-2 (day -1 > day -5 intensification): "
          f"{'CONFIRMED' if c2_confirmed else 'NULL'}")
    print(f"  H5-Cascade-3 (no thermal elevation):             DEFERRED")

    # Create results table if needed, then save
    try:
        save_results(client, c1_results, c1_confirmed,
                     c2_results, c2_confirmed, df)
    except Exception as e:
        print(f"\nNote: Results table may need creation: {e}")
        print("Run:")
        print(f"  bq mk --table {PROJECT}:{RESULT_TABLE} \\")
        print("  metric:STRING,is_primary:INTEGER,centroid_day:FLOAT,")
        print("  centroid_ci_lower:FLOAT,centroid_ci_upper:FLOAT,")
        print("  window_classification:STRING,cascade1_confirmed:INTEGER,")
        print("  z_day_neg1:FLOAT,z_day_neg5:FLOAT,z_day_neg7:FLOAT,")
        print("  cascade2_confirmed:INTEGER,cascade3_status:STRING,")
        print("  run_timestamp:STRING,data_source:STRING,")
        print("  amendment_commit:STRING,permutation_iters:INTEGER,")
        print("  cascade1_primary_verdict:STRING,cascade2_primary_verdict:STRING")


if __name__ == "__main__":
    main()
