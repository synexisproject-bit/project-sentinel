#!/usr/bin/env python3
"""
H6a: Ephemeris as HAC Dream Signal Moderator — Project Sentinel
CORRECTED IMPLEMENTATION: Per-lunar-phase-bin superposed epoch analysis

For each lunar phase bin, runs a separate SEA using earthquakes
that occurred in that bin. Compares ionospheric window z-scores
across bins to test moderation.

Amendment #9 v3 | osf.io/8hvf6
Pre-registered before execution

Method:
  1. Load M6+ earthquakes with lunar phase bins (2010-2025)
  2. For each of 8 lunar phase bins, extract epoch around events
  3. Compute mean signal at days -1 to -5 (ionospheric window)
  4. Test: do ionospheric window means differ across bins?
  5. Bootstrap: shuffle bin assignments, recompute between-bin variance
  6. Benjamini-Hochberg FDR correction across moderators

Signal table: sentinel_features.hac_features_daily (fault_id=global)
Window: 2010-01-01 to 2025-12-31 (signal coverage)
"""

import json
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone
from scipy import stats
from google.cloud import bigquery

PROJECT      = "synexis-project-sentinel"
RESULT_TABLE = "sentinel_eval.h6a_hac_moderator_results_declustered_deduped"

SIGNAL_TABLE = "sentinel_features.hac_features_daily"
EQ_TABLE     = "sentinel_groundtruth.master_earthquakes_declustered"
EPH_TABLE    = "sentinel_features.h6_ephemeris_daily"

WINDOW          = 7    # days each side
IONO_DAYS       = [-5, -4, -3, -2, -1]  # ionospheric window
N_PERMUTATIONS  = 2000
MIN_EVENTS_BIN  = 5    # minimum events per bin to compute
SIGNIFICANCE    = 0.05

LUNAR_BIN_NAMES = [
    "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous",
    "full_moon", "waning_gibbous", "last_quarter", "waning_crescent"
]

METRICS = {
    "zscore":      "hac_count_zscore",
    "high_urgency":"hac_count_high_urgency",
    "high_emotion":"hac_count_high_emotion",
    "water":       "hac_count_water",
}


def load_signal(client) -> dict:
    """Load daily HAC signal for fault_id=global, 2010-2025."""
    query = f"""
    SELECT date_val,
           hac_count_zscore,
           hac_count_high_urgency,
           hac_count_high_emotion,
           hac_count_water,
           hac_365d_baseline_mean,
           hac_365d_baseline_std
    FROM `{PROJECT}.{SIGNAL_TABLE}`
    WHERE fault_id = 'global'
      AND date_val BETWEEN '2010-01-01' AND '2025-12-31'
    ORDER BY date_val
    """
    rows = list(client.query(query).result())
    signal = {}
    for r in rows:
        signal[r.date_val] = {
            "zscore":       r.hac_count_zscore,
            "high_urgency": r.hac_count_high_urgency,
            "high_emotion": r.hac_count_high_emotion,
            "water":        r.hac_count_water,
            "baseline_mean":r.hac_365d_baseline_mean,
            "baseline_std": r.hac_365d_baseline_std,
        }
    print(f"  Loaded {len(signal):,} signal days")
    return signal


def load_earthquakes(client) -> pd.DataFrame:
    """Load M6+ earthquakes with lunar phase, 2010-2025."""
    query = f"""
    SELECT
      DATE(e.time) as event_date,
      e.magnitude,
      h.lunar_phase_bin,
      h.lunar_phase_name,
      h.lunar_phase_deg,
      h.venus_elongation_deg,
      h.mars_elongation_deg,
      h.jupiter_dist_au
    FROM (
      SELECT DISTINCT e.id, e.time, e.latitude, e.longitude, e.magnitude
      FROM `{PROJECT}.{EQ_TABLE}` e
      INNER JOIN `{PROJECT}.sentinel_features.fault_events` f
        ON DATE(e.time) = DATE(f.time)
        AND ABS(e.latitude - f.latitude) < 0.1
        AND ABS(e.longitude - f.longitude) < 0.1
      WHERE e.magnitude >= 6.0
        AND e.is_mainshock = TRUE
        AND DATE(e.time) BETWEEN '2010-01-01' AND '2025-12-31'
    ) e
    LEFT JOIN `{PROJECT}.{EPH_TABLE}` h
      ON DATE(e.time) = h.date_val
    WHERE h.lunar_phase_bin IS NOT NULL
    ORDER BY e.time
    """
    df = client.query(query).to_dataframe()
    print(f"  Loaded {len(df):,} M6+ earthquakes (2010-2025 with ephemeris)")
    return df


def extract_epoch(event_dates: list, signal: dict, metric: str,
                  window: int = WINDOW) -> dict:
    """Extract signal around each event date. Returns {rel_day: [values]}."""
    epoch = defaultdict(list)
    for ev_date in event_dates:
        for rel_day in range(-window, window + 1):
            d = ev_date + timedelta(days=rel_day)
            if d in signal and signal[d][metric] is not None:
                epoch[rel_day].append(float(signal[d][metric]))
    return epoch


def epoch_mean(epoch: dict) -> dict:
    """Compute mean signal at each rel_day."""
    return {
        day: float(np.mean(vals))
        for day, vals in epoch.items() if vals
    }


def iono_window_mean(epoch_means: dict, days: list = IONO_DAYS) -> float:
    """Compute mean over the ionospheric window days."""
    vals = [epoch_means[d] for d in days if d in epoch_means]
    return float(np.mean(vals)) if vals else None


def between_bin_variance(bin_means: list) -> float:
    """Compute variance across bin means (test statistic)."""
    valid = [m for m in bin_means if m is not None]
    return float(np.var(valid)) if len(valid) >= 2 else 0.0


def run_bin_sea(event_dates: list, signal: dict, metric: str) -> float:
    """Run SEA for a bin, return ionospheric window mean."""
    if len(event_dates) < MIN_EVENTS_BIN:
        return None
    epoch = extract_epoch(event_dates, signal, metric)
    means = epoch_mean(epoch)
    return iono_window_mean(means)


def fdr_correct(p_values: list, alpha: float = SIGNIFICANCE) -> list:
    """Benjamini-Hochberg FDR correction. Returns list of booleans."""
    n = len(p_values)
    if n == 0: return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    rejected = [False] * n
    for rank, (orig_idx, p) in enumerate(indexed):
        if p <= (rank + 1) * alpha / n:
            rejected[orig_idx] = True
    return rejected


def test_lunar_moderation(df_eq: pd.DataFrame, signal: dict,
                          metric: str) -> dict:
    """
    Test lunar phase moderation of HAC signal.
    For each of 8 bins, compute ionospheric window mean.
    Test: between-bin variance vs bootstrap null.
    """
    bin_event_dates = {}
    for b in range(8):
        dates = df_eq[df_eq["lunar_phase_bin"] == b]["event_date"].tolist()
        bin_event_dates[b] = dates

    # Compute observed bin means
    bin_means = {}
    for b in range(8):
        bin_means[b] = run_bin_sea(bin_event_dates[b], signal, metric)

    obs_variance = between_bin_variance(list(bin_means.values()))

    # Print bin table
    print(f"\n  {metric} — ionospheric window mean per lunar phase bin:")
    print(f"    {'Bin':22s}  {'N':>4}  {'Iono mean':>10}  {'Ratio vs global':>15}")
    all_dates = df_eq["event_date"].tolist()
    global_mean = run_bin_sea(all_dates, signal, metric)
    global_str = f"{global_mean:.4f}" if global_mean is not None else "N/A"
    print(f"    {'GLOBAL':22s}  {len(all_dates):>4}  {global_str:>10}")
    print(f"    {'-'*60}")

    for b in range(8):
        n   = len(bin_event_dates[b])
        bm  = bin_means[b]
        bm_str = f"{bm:.4f}" if bm is not None else "N/A"
        if bm is not None and global_mean is not None and global_mean != 0:
            ratio_str = f"{bm/global_mean:.3f}"
        else:
            ratio_str = "N/A"
        print(f"    {LUNAR_BIN_NAMES[b]:22s}  {n:>4}  {bm_str:>10}  {ratio_str:>15}")

    # Bootstrap permutation test
    # Null: shuffle lunar phase bin assignments across earthquakes
    all_eq_dates = df_eq["event_date"].tolist()
    all_bins     = df_eq["lunar_phase_bin"].tolist()
    null_variances = []

    for _ in range(N_PERMUTATIONS):
        shuffled_bins = np.random.permutation(all_bins)
        perm_means = []
        for b in range(8):
            b_dates = [all_eq_dates[i] for i, sb in enumerate(shuffled_bins)
                       if sb == b]
            perm_means.append(run_bin_sea(b_dates, signal, metric))
        null_variances.append(between_bin_variance(perm_means))

    null_variances = np.array(null_variances)
    p_bootstrap = float(np.mean(null_variances >= obs_variance))

    print(f"\n  Between-bin variance: {obs_variance:.6f}")
    print(f"  Bootstrap p = {p_bootstrap:.4f} "
          f"{'SIGNIFICANT *' if p_bootstrap < SIGNIFICANCE else 'null'}")

    return {
        "metric":           metric,
        "moderator":        "lunar_phase_bin",
        "moderator_type":   "primary",
        "n_bins_valid":     sum(1 for m in bin_means.values() if m is not None),
        "global_iono_mean": global_mean,
        "bin_iono_means":   json.dumps({str(b): v for b, v in bin_means.items()}),
        "obs_variance":     obs_variance,
        "p_bootstrap":      p_bootstrap,
        "n_events_total":   len(all_eq_dates),
        "min_events_bin":   MIN_EVENTS_BIN,
        "iono_days":        json.dumps(IONO_DAYS),
        "amendment_commit": "c8cbf9c",
        "run_timestamp":    datetime.now(timezone.utc).isoformat(),
    }


def test_continuous_moderation(df_eq: pd.DataFrame, signal: dict,
                                metric: str, col: str,
                                mod_name: str, mod_type: str) -> dict:
    """Test tertile moderation for continuous moderators."""
    df = df_eq.copy()
    df["tertile"] = pd.qcut(df[col], 3, labels=[0, 1, 2],
                             duplicates='drop').astype(float)

    bin_means = {}
    for t in [0.0, 1.0, 2.0]:
        dates = df[df["tertile"] == t]["event_date"].tolist()
        bin_means[t] = run_bin_sea(dates, signal, metric)

    obs_variance = between_bin_variance(list(bin_means.values()))

    # Bootstrap
    all_dates  = df["event_date"].tolist()
    all_terts  = df["tertile"].tolist()
    null_vars  = []

    for _ in range(N_PERMUTATIONS):
        shuffled = np.random.permutation(all_terts)
        pm = []
        for t in [0.0, 1.0, 2.0]:
            b_dates = [all_dates[i] for i, st in enumerate(shuffled) if st == t]
            pm.append(run_bin_sea(b_dates, signal, metric))
        null_vars.append(between_bin_variance(pm))

    p_bootstrap = float(np.mean(np.array(null_vars) >= obs_variance))
    print(f"  {metric} x {mod_name}: p_bootstrap={p_bootstrap:.4f}")

    return {
        "metric":           metric,
        "moderator":        mod_name,
        "moderator_type":   mod_type,
        "n_bins_valid":     sum(1 for m in bin_means.values() if m is not None),
        "global_iono_mean": run_bin_sea(all_dates, signal, metric),
        "bin_iono_means":   json.dumps({str(k): v for k, v in bin_means.items()}),
        "obs_variance":     obs_variance,
        "p_bootstrap":      p_bootstrap,
        "n_events_total":   len(all_dates),
        "min_events_bin":   MIN_EVENTS_BIN,
        "iono_days":        json.dumps(IONO_DAYS),
        "amendment_commit": "c8cbf9c",
        "run_timestamp":    datetime.now(timezone.utc).isoformat(),
    }


def main():
    print("=" * 60)
    print("Project Sentinel H6a — HAC Moderator Analysis (v2)")
    print("Per-bin SEA implementation")
    print("Amendment #9 v3 | osf.io/8hvf6")
    print(f"Run: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    client = bigquery.Client(project=PROJECT)

    print("\nLoading signal and earthquake data...")
    signal = load_signal(client)
    df_eq  = load_earthquakes(client)

    if not signal or len(df_eq) == 0:
        print("ERROR: Missing data.")
        return

    print(f"\n  Earthquake sample: {len(df_eq)} events (2010-2025)")
    print(f"  Lunar bin distribution:")
    for b in range(8):
        n = int((df_eq["lunar_phase_bin"] == b).sum())
        print(f"    {LUNAR_BIN_NAMES[b]:22s}: {n}")

    all_results = []

    # PRIMARY: Lunar phase moderation
    print(f"\n{'='*60}")
    print("PRIMARY MODERATOR: Lunar Phase (8 bins)")
    print(f"Running {N_PERMUTATIONS} bootstrap permutations per metric...")
    print(f"{'='*60}")

    primary_metrics = ["zscore", "high_urgency", "high_emotion"]
    for metric in primary_metrics:
        print(f"\n--- {metric} ---")
        r = test_lunar_moderation(df_eq, signal, metric)
        all_results.append(r)

    # SECONDARY: Venus elongation
    print(f"\n{'='*60}")
    print("SECONDARY MODERATOR: Venus Elongation (tertile)")
    print(f"{'='*60}")
    for metric in ["zscore", "high_urgency"]:
        r = test_continuous_moderation(df_eq, signal, metric,
                                       "venus_elongation_deg",
                                       "venus_tertile", "secondary")
        all_results.append(r)

    # SECONDARY: Mars elongation
    print(f"\n{'='*60}")
    print("SECONDARY MODERATOR: Mars Elongation (tertile)")
    print(f"{'='*60}")
    for metric in ["zscore", "high_urgency"]:
        r = test_continuous_moderation(df_eq, signal, metric,
                                       "mars_elongation_deg",
                                       "mars_tertile", "secondary")
        all_results.append(r)

    # TERTIARY: Jupiter distance
    print(f"\n{'='*60}")
    print("TERTIARY (exploratory): Jupiter Distance (tertile)")
    print(f"{'='*60}")
    for metric in ["zscore", "high_urgency"]:
        r = test_continuous_moderation(df_eq, signal, metric,
                                       "jupiter_dist_au",
                                       "jupiter_tertile",
                                       "tertiary_exploratory")
        all_results.append(r)

    # FDR correction on primary + secondary
    print(f"\n{'='*60}")
    print("FDR CORRECTION (Benjamini-Hochberg)")
    print(f"{'='*60}")

    ps_results = [r for r in all_results
                  if r["moderator_type"] in ("primary", "secondary")]
    ps         = [r["p_bootstrap"] for r in ps_results]
    rejected   = fdr_correct(ps)

    print(f"\n  {'Metric':15s}  {'Moderator':20s}  {'p_bootstrap':>12}  {'FDR':>6}")
    print(f"  {'-'*60}")
    any_confirmed = False
    for r, rej in zip(ps_results, rejected):
        r["fdr_significant"] = 1 if rej else 0
        sig = "YES *" if rej else "no"
        if rej: any_confirmed = True
        print(f"  {r['metric']:15s}  {r['moderator']:20s}  "
              f"{r['p_bootstrap']:>12.4f}  {sig:>6}")

    for r in all_results:
        if "fdr_significant" not in r:
            r["fdr_significant"] = 0

    print(f"\n  H6a PRIMARY OUTCOME: {'CONFIRMED' if any_confirmed else 'NULL'}")

    # Save
    df_out = pd.DataFrame(all_results)
    try:
        job = client.load_table_from_dataframe(
            df_out, f"{PROJECT}.{RESULT_TABLE}",
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        )
        job.result()
        print(f"\nResults saved to {PROJECT}.{RESULT_TABLE}")
    except Exception as e:
        print(f"\nSave error: {e}")
        print("Run bq mk to create table first (see script header)")


if __name__ == "__main__":
    main()
