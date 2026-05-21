#!/usr/bin/env python3
"""
H6b: Seismic-Lunar Tidal Forcing Test — Project Sentinel
Tests whether M6+ earthquake occurrence correlates non-randomly
with lunar phase across the five pre-registered fault zones.

Pre-registered in Amendment #9 v3 | osf.io/8hvf6
Benchmark: Ide, Yabe & Tanaka 2016, Nature Geoscience

Primary variable:  Lunar phase (8 bins × 45 degrees)
Secondary variable: Lunar distance (perigee/apogee, tertile split)
Tertiary (exploratory): Solar elongation of Venus, Mars; Jupiter distance

Pass criteria: Significant non-uniform distribution (p<0.05) in primary
  lunar phase bin test, pooled across all five fault zones.
"""

import json
import numpy as np
from datetime import datetime, timezone
from scipy import stats
from google.cloud import bigquery
import pandas as pd

PROJECT      = "synexis-project-sentinel"
RESULT_TABLE = "sentinel_eval.h6b_seismic_lunar_results_declustered"

PREREGISTERED_FAULTS = [
    "japan_trench", "cascadia", "central_chile",
    "north_anatolian", "sumatra_andaman"
]

N_PERMUTATIONS  = 2000
SIGNIFICANCE    = 0.05
N_LUNAR_BINS    = 8
BIN_WIDTH       = 45.0  # degrees

LUNAR_BIN_NAMES = [
    "new_moon (0-45)",
    "waxing_crescent (45-90)",
    "first_quarter (90-135)",
    "waxing_gibbous (135-180)",
    "full_moon (180-225)",
    "waning_gibbous (225-270)",
    "last_quarter (270-315)",
    "waning_crescent (315-360)",
]


def load_earthquake_ephemeris(client) -> pd.DataFrame:
    """Load M6+ earthquakes joined to ephemeris data."""
    query = """
    SELECT
      e.fault_id,
      DATE(e.event_date) as event_date,
      e.magnitude,
      h.lunar_phase_deg,
      h.lunar_phase_bin,
      h.lunar_phase_name,
      h.lunar_illumination,
      h.lunar_dist_au,
      h.venus_elongation_deg,
      h.mars_elongation_deg,
      h.jupiter_dist_au
    FROM `synexis-project-sentinel.sentinel_features.fault_events` e
    INNER JOIN `synexis-project-sentinel.sentinel_groundtruth.master_earthquakes_declustered` d
      ON DATE(e.time) = DATE(d.time)
      AND ABS(e.latitude - d.latitude) < 0.1
      AND ABS(e.longitude - d.longitude) < 0.1
    LEFT JOIN `synexis-project-sentinel.sentinel_features.h6_ephemeris_daily` h
      ON DATE(e.event_date) = h.date_val
    WHERE e.magnitude >= 6.5
      AND d.is_mainshock = TRUE
      AND DATE(e.event_date) BETWEEN '2001-01-01' AND '2025-12-31'
      AND h.lunar_phase_deg IS NOT NULL
    ORDER BY e.fault_id, e.event_date
    """
    df = client.query(query).to_dataframe()
    print(f"  Loaded {len(df):,} M6+ events with ephemeris data")
    return df


def chi_square_lunar(phase_bins: np.ndarray, n_bins: int = N_LUNAR_BINS) -> tuple:
    """Chi-square test for uniform distribution across lunar phase bins."""
    observed = np.bincount(phase_bins, minlength=n_bins)
    expected = np.full(n_bins, len(phase_bins) / n_bins)
    chi2, p = stats.chisquare(observed, expected)
    return float(chi2), float(p), observed.tolist()


def bootstrap_null(phase_bins: np.ndarray, n_perm: int = N_PERMUTATIONS,
                   n_bins: int = N_LUNAR_BINS) -> tuple:
    """Bootstrap null distribution by shuffling phase bins."""
    n = len(phase_bins)
    all_bins = np.arange(n_bins)
    chi2_null = []

    for _ in range(n_perm):
        shuffled = np.random.choice(all_bins, size=n, replace=True)
        obs = np.bincount(shuffled, minlength=n_bins)
        exp = np.full(n_bins, n / n_bins)
        chi2_s, _ = stats.chisquare(obs, exp)
        chi2_null.append(chi2_s)

    chi2_null = np.array(chi2_null)
    return chi2_null


def lunar_distance_tertile(dist_au: pd.Series) -> pd.Series:
    """Assign lunar distance to tertile (0=near/perigee, 1=mid, 2=far/apogee)."""
    return pd.qcut(dist_au, 3, labels=[0, 1, 2]).astype(int)


def print_bin_table(observed: list, n_events: int):
    """Print lunar phase bin distribution."""
    expected = n_events / N_LUNAR_BINS
    print(f"\n    {'Bin':30s} {'Obs':>5}  {'Exp':>5}  {'Ratio':>6}")
    print(f"    {'-'*55}")
    for i, (name, obs) in enumerate(zip(LUNAR_BIN_NAMES, observed)):
        ratio = obs / expected if expected > 0 else 0
        marker = " *" if ratio > 1.2 or ratio < 0.8 else ""
        print(f"    {name:30s} {obs:>5}  {expected:>5.1f}  {ratio:>6.3f}{marker}")


def analyze_fault(df_fault: pd.DataFrame, fault_id: str) -> dict:
    """Run H6b analysis for a single fault zone."""
    print(f"\n{'='*60}")
    print(f"Fault: {fault_id}  [{len(df_fault)} events]")
    print(f"{'='*60}")

    if len(df_fault) < 10:
        print("  INSUFFICIENT DATA (<10 events)")
        return {"fault_id": fault_id, "verdict": "INSUFFICIENT_DATA",
                "n_events": len(df_fault)}

    phase_bins = df_fault["lunar_phase_bin"].values.astype(int)

    # Primary test: chi-square on 8 lunar phase bins
    chi2_obs, p_chisq, observed = chi_square_lunar(phase_bins)
    print(f"\n  Primary: Chi-square test across 8 lunar phase bins")
    print(f"    Chi2 = {chi2_obs:.4f}  p = {p_chisq:.4f}  "
          f"{'SIGNIFICANT *' if p_chisq < SIGNIFICANCE else 'null'}")
    print_bin_table(observed, len(df_fault))

    # Bootstrap null
    print(f"\n  Computing bootstrap null ({N_PERMUTATIONS} permutations)...")
    chi2_null = bootstrap_null(phase_bins)
    p_bootstrap = float(np.mean(chi2_null >= chi2_obs))
    print(f"    Bootstrap p = {p_bootstrap:.4f}")

    # Secondary: lunar distance (perigee vs apogee)
    if "lunar_dist_au" in df_fault.columns and df_fault["lunar_dist_au"].notna().sum() > 9:
        tertiles = lunar_distance_tertile(df_fault["lunar_dist_au"])
        near_rate  = (tertiles == 0).sum() / len(tertiles)
        far_rate   = (tertiles == 2).sum() / len(tertiles)
        print(f"\n  Secondary: Lunar distance tertiles")
        print(f"    Near (perigee): {near_rate:.3f} vs expected 0.333")
        print(f"    Far (apogee):   {far_rate:.3f} vs expected 0.333")
    else:
        near_rate = far_rate = None

    # Peak bin identification
    peak_bin = int(np.argmax(observed))
    peak_name = LUNAR_BIN_NAMES[peak_bin]
    print(f"\n  Peak lunar phase bin: {peak_name} ({observed[peak_bin]} events)")

    # Ide et al. 2016 benchmark comparison
    print(f"\n  Ide et al. 2016 benchmark: significant lunar modulation")
    print(f"  particularly around new moon and full moon phases.")
    new_full = observed[0] + observed[4]  # bins 0 and 4
    expected_new_full = len(df_fault) * 2 / 8
    new_full_ratio = new_full / expected_new_full if expected_new_full > 0 else 0
    print(f"  New+Full moon combined: {new_full} obs vs {expected_new_full:.1f} expected "
          f"(ratio={new_full_ratio:.3f})")

    confirmed = p_chisq < SIGNIFICANCE or p_bootstrap < SIGNIFICANCE

    return {
        "fault_id":           fault_id,
        "n_events":           len(df_fault),
        "chi2_observed":      chi2_obs,
        "p_chisquare":        p_chisq,
        "p_bootstrap":        p_bootstrap,
        "peak_bin":           peak_bin,
        "peak_bin_name":      peak_name,
        "observed_counts":    json.dumps(observed),
        "expected_per_bin":   len(df_fault) / N_LUNAR_BINS,
        "new_full_count":     int(new_full),
        "new_full_ratio":     new_full_ratio,
        "near_perigee_rate":  near_rate,
        "far_apogee_rate":    far_rate,
        "verdict":            "CONFIRMED" if confirmed else "NULL",
        "amendment_commit":   "c8cbf9c",
        "benchmark":          "Ide_Yabe_Tanaka_2016_NatureGeoscience",
        "run_timestamp":      datetime.now(timezone.utc).isoformat(),
    }


def save_results(client, results: list):
    df  = pd.DataFrame(results)
    job = client.load_table_from_dataframe(
        df, f"{PROJECT}.{RESULT_TABLE}",
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    )
    job.result()
    print(f"\nResults saved to {PROJECT}.{RESULT_TABLE}")


def main():
    print("=" * 60)
    print("Project Sentinel H6b — Seismic-Lunar Tidal Forcing Test")
    print("Amendment #9 v3 | osf.io/8hvf6")
    print(f"Run: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    client = bigquery.Client(project=PROJECT)

    print("\nLoading earthquake-ephemeris data...")
    df = load_earthquake_ephemeris(client)

    if len(df) == 0:
        print("ERROR: No data returned. Check that h6_ephemeris_daily is populated.")
        return

    results = []

    # Analyze each pre-registered fault zone
    for fault_id in PREREGISTERED_FAULTS:
        df_fault = df[df["fault_id"] == fault_id].copy()
        r = analyze_fault(df_fault, fault_id)
        results.append(r)

    # Global pooled analysis (all fault zones combined)
    print(f"\n{'='*60}")
    print("GLOBAL POOLED ANALYSIS (all 5 pre-registered zones)")
    print(f"{'='*60}")
    df_pooled = df[df["fault_id"].isin(PREREGISTERED_FAULTS)].copy()
    r_pooled  = analyze_fault(df_pooled, "global_pooled")
    results.append(r_pooled)

    # Tertiary exploratory: Venus and Mars elongation
    print(f"\n{'='*60}")
    print("TERTIARY EXPLORATORY: Planetary Elongation")
    print("(hypothesis-generating only, no pass/fail threshold)")
    print(f"{'='*60}")
    for planet, col in [("Venus", "venus_elongation_deg"),
                         ("Mars", "mars_elongation_deg")]:
        if col in df_pooled.columns and df_pooled[col].notna().sum() > 0:
            corr = df_pooled["lunar_phase_deg"].corr(df_pooled[col])
            print(f"  {planet} elongation vs lunar phase: r = {corr:.4f}")

    # Summary
    print(f"\n{'='*60}")
    print("H6b SUMMARY")
    print(f"{'='*60}")
    n_confirmed = sum(1 for r in results
                      if r.get("verdict") == "CONFIRMED"
                      and r["fault_id"] != "global_pooled")
    for r in results:
        fid = r["fault_id"]
        v   = r.get("verdict", "N/A")
        n   = r.get("n_events", 0)
        p   = r.get("p_chisquare", None)
        p_s = f"{p:.4f}" if p is not None else "N/A"
        print(f"  {fid:25s}  n={n:>4}  p={p_s}  [{v}]")

    pooled = next((r for r in results if r["fault_id"] == "global_pooled"), None)
    if pooled:
        print(f"\n  Global pooled p-value: {pooled.get('p_chisquare', 'N/A'):.4f}")
        print(f"  H6b PRIMARY OUTCOME: "
              f"{'CONFIRMED' if pooled.get('verdict') == 'CONFIRMED' else 'NULL'}")
        print(f"  (Pass criteria: pooled p<{SIGNIFICANCE})")

    try:
        save_results(client, results)
    except Exception as e:
        print(f"\nNote: Create results table first:\n  {e}")
        print(f"\nbq mk --table {PROJECT}:{RESULT_TABLE} \\")
        print("  fault_id:STRING,n_events:INTEGER,chi2_observed:FLOAT,")
        print("  p_chisquare:FLOAT,p_bootstrap:FLOAT,peak_bin:INTEGER,")
        print("  peak_bin_name:STRING,observed_counts:STRING,")
        print("  expected_per_bin:FLOAT,new_full_count:INTEGER,")
        print("  new_full_ratio:FLOAT,near_perigee_rate:FLOAT,")
        print("  far_apogee_rate:FLOAT,verdict:STRING,amendment_commit:STRING,")
        print("  benchmark:STRING,run_timestamp:STRING")


if __name__ == "__main__":
    main()
