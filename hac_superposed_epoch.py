#!/usr/bin/env python3
"""
hac_superposed_epoch.py

Pre-registered superposed epoch analysis for the HAC stream.
Tests whether daily HAC count z-scores are elevated in the days before
M6+ earthquake events across the five Project Sentinel fault zones.

Pre-registration: Amendment #2, April 2026
GitHub: github.com/synexisproject-bit/project-sentinel

Analysis design:
  - Anchors on M6+ events in sentinel_groundtruth.master_earthquakes
  - Signal: hac_count_zscore from sentinel_features.hac_features_daily
  - Fault zones: cascadia, central_chile, japan_trench,
                 north_anatolian, sumatra_andaman + global
  - Primary windows: 3d, 5d, 7d pre-event
  - Secondary windows: 14d, 30d (exploratory)
  - Method: superposed epoch analysis, 2000 permutation null distribution
  - Output: writes to sentinel_analysis.hac_epoch_zscores

Usage:
  python3 hac_superposed_epoch.py
  python3 hac_superposed_epoch.py --mag 7.0        # M7+ threshold
  python3 hac_superposed_epoch.py --fault cascadia  # single fault
  python3 hac_superposed_epoch.py --iters 1000      # faster for testing
  python3 hac_superposed_epoch.py --dry-run         # no BQ write
"""

import argparse
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from datetime import datetime, timezone

import numpy as np
from google.cloud import bigquery

PROJECT      = "synexis-project-sentinel"
EQ_TABLE     = f"{PROJECT}.sentinel_groundtruth.master_earthquakes"
HAC_TABLE    = f"{PROJECT}.sentinel_features.hac_features_daily"
FAULT_TABLE  = f"{PROJECT}.sentinel_features.fault_systems"
OUTPUT_TABLE = f"{PROJECT}.sentinel_analysis.hac_epoch_zscores"

WINDOW       = 20     # ±20 days — extended for H5-Cascade-3
PRIMARY_WINDOWS = [3, 5, 7]
SECONDARY_WINDOWS = [14, 30]

bq = bigquery.Client(project=PROJECT)


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# ── Load fault zone definitions ───────────────────────────────────────────────

def load_fault_zones():
    query = f"SELECT fault_id, lat_min, lat_max, lon_min, lon_max FROM `{FAULT_TABLE}`"
    rows = list(bq.query(query).result())
    return {r.fault_id: r for r in rows}


# ── Load earthquake events ────────────────────────────────────────────────────

def load_events(mag_threshold, fault_zones, fault_filter=None):
    """
    Load M6+ events within fault zone bounding boxes.
    Returns dict: fault_id -> list of event dates.
    """
    log(f"Loading M{mag_threshold}+ events...")
    query = f"""
    SELECT event_id, DATE(time) AS event_date, latitude, longitude, magnitude, tsunami
    FROM `{EQ_TABLE}`
    WHERE magnitude >= @mag
      AND DATE(time) BETWEEN '2010-01-01' AND '2026-12-31'
    ORDER BY time
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("mag", "FLOAT64", mag_threshold)
    ])
    rows = list(bq.query(query, job_config=cfg).result())
    log(f"  Loaded {len(rows)} total M{mag_threshold}+ events")

    # Assign to fault zones
    events_by_fault = defaultdict(list)
    # Global = all events
    events_by_fault['global'] = [r.event_date for r in rows]

    for row in rows:
        for fault_id, fz in fault_zones.items():
            if fault_filter and fault_id != fault_filter:
                continue
            if (fz.lat_min <= row.latitude <= fz.lat_max and
                    fz.lon_min <= row.longitude <= fz.lon_max):
                events_by_fault[fault_id].append(row.event_date)

    for fid, evts in sorted(events_by_fault.items()):
        log(f"  {fid}: {len(evts)} events")

    return events_by_fault


# ── Load HAC daily signal ─────────────────────────────────────────────────────

def load_hac_signal(fault_id):
    """
    Load hac_count_zscore time series for a fault zone.
    Returns dict: date -> zscore (None where NULL).
    """
    query = f"""
    SELECT date_val, hac_count_zscore, hac_count,
           hac_count_high_urgency, hac_count_water,
           hac_count_high_emotion
    FROM `{HAC_TABLE}`
    WHERE fault_id = @fault_id
    ORDER BY date_val
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("fault_id", "STRING", fault_id)
    ])
    rows = list(bq.query(query, job_config=cfg).result())
    signal = {}
    for r in rows:
        signal[r.date_val] = {
            'zscore':      r.hac_count_zscore,
            'count':       r.hac_count,
            'high_urgency': r.hac_count_high_urgency,
            'water':       r.hac_count_water,
            'high_emotion': r.hac_count_high_emotion,
        }
    return signal


# ── Superposed epoch analysis ─────────────────────────────────────────────────

def extract_epoch(events, signal, metric='zscore', window=WINDOW):
    """
    For each event, extract signal values at rel_day = -window to +window.
    Returns dict: rel_day -> list of values (excluding NaN).
    """
    epoch = defaultdict(list)
    for event_date in events:
        for rel_day in range(-window, window + 1):
            d = event_date + timedelta(days=rel_day)
            if d in signal and signal[d][metric] is not None:
                epoch[rel_day].append(signal[d][metric])
    return epoch


def mean_epoch(epoch):
    """Compute mean signal at each rel_day."""
    return {
        rel_day: float(np.mean(vals)) if vals else None
        for rel_day, vals in epoch.items()
    }


def permutation_test(events, signal, metric='zscore', window=WINDOW,
                     iters=2000, seed=42):
    """
    Permutation null distribution.
    Randomly shift event dates (preserving year to control for seasonality)
    and recompute the mean epoch profile.
    Returns dict: rel_day -> list of permuted means.
    """
    rng = np.random.default_rng(seed)
    all_dates = sorted(signal.keys())
    date_array = np.array(all_dates)
    n_dates = len(date_array)

    perm_means = defaultdict(list)

    for _ in range(iters):
        # Random date offsets, preserving rough seasonality
        # by shifting each event by a random number of full years ±
        # a small random offset
        shuffled_events = []
        for event_date in events:
            # Random offset: ±365-730 days (1-2 years away)
            offset = int(rng.integers(365, 730)) * rng.choice([-1, 1])
            candidate = event_date + timedelta(days=int(offset))
            # Clamp to available signal range
            if candidate < all_dates[0]:
                candidate = all_dates[0] + timedelta(days=int(rng.integers(0, 30)))
            if candidate > all_dates[-1]:
                candidate = all_dates[-1] - timedelta(days=int(rng.integers(0, 30)))
            shuffled_events.append(candidate)

        perm_epoch = extract_epoch(shuffled_events, signal, metric, window)
        for rel_day in range(-window, window + 1):
            vals = perm_epoch.get(rel_day, [])
            if vals:
                perm_means[rel_day].append(float(np.mean(vals)))

    return perm_means


def compute_zscores(observed, perm_means):
    """
    Compute z-score of observed mean against permutation distribution.
    Returns dict: rel_day -> (obs, mean_perm, std_perm, zscore, p_value)
    """
    results = {}
    for rel_day in range(-WINDOW, WINDOW + 1):
        obs = observed.get(rel_day)
        perms = perm_means.get(rel_day, [])
        if obs is None or not perms:
            results[rel_day] = (obs, None, None, None, None)
            continue
        mean_p = float(np.mean(perms))
        std_p  = float(np.std(perms))
        z = (obs - mean_p) / std_p if std_p > 0 else None
        # One-tailed p-value (testing for elevation above baseline)
        p = float(np.mean([p >= obs for p in perms]))
        results[rel_day] = (obs, mean_p, std_p, z, p)
    return results


def window_summary(results, window_days):
    """
    Compute mean z-score and p-value for a pre-event window.
    Window: rel_day in [-window_days, -1]
    """
    pre_obs   = [results[d][0] for d in range(max(-WINDOW,-window_days), 0)
                 if d in results and results[d][0] is not None]
    pre_perms = []
    for d in range(max(-WINDOW,-window_days), 0):
        perms = results[d]
        if perms[1] is not None:
            pre_perms.append(perms[1])

    if not pre_obs:
        return None, None

    mean_obs  = float(np.mean(pre_obs))
    mean_perm = float(np.mean(pre_perms)) if pre_perms else None
    return mean_obs, mean_perm


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis(mag_threshold=6.0, fault_filter=None, iters=2000,
                 dry_run=False, metric='zscore'):

    log("=== HAC Superposed Epoch Analysis ===")
    log(f"Magnitude threshold : M{mag_threshold}+")
    log(f"Fault filter        : {fault_filter or 'all'}")
    log(f"Permutation iters   : {iters}")
    log(f"Metric              : {metric}")
    log(f"Dry run             : {dry_run}")

    fault_zones = load_fault_zones()
    events_by_fault = load_events(mag_threshold, fault_zones, fault_filter)

    all_results = []
    summary_rows = []

    faults_to_run = (
        [fault_filter] if fault_filter
        else list(fault_zones.keys()) + ['global']
    )

    for fault_id in faults_to_run:
        events = events_by_fault.get(fault_id, [])
        if len(events) < 3:
            log(f"\nSkipping {fault_id} — only {len(events)} events")
            continue

        log(f"\n--- Fault: {fault_id} ({len(events)} events) ---")

        # Load signal
        signal = load_hac_signal(fault_id)
        log(f"  Signal loaded: {len(signal)} days")

        # Run for multiple metrics
        metrics_to_run = [metric] if metric != 'all' else [
            'zscore', 'high_urgency', 'water', 'high_emotion'
        ]

        for m in metrics_to_run:
            log(f"  Running {m}...")

            # Observed epoch
            observed_epoch = extract_epoch(events, signal, m)
            observed_means = mean_epoch(observed_epoch)

            # Permutation null
            perm_means = permutation_test(
                events, signal, m, WINDOW, iters, seed=42
            )

            # Z-scores
            results = compute_zscores(observed_means, perm_means)

            # Log rel_day profile
            log(f"  rel_day profile ({m}):")
            for rd in range(-7, 8):
                obs, mp, sp, z, p = results.get(rd, (None,)*5)
                if obs is not None and z is not None:
                    marker = " ***" if p is not None and p < 0.05 else ""
                    log(f"    day {rd:+3d}: obs={obs:6.3f} "
                        f"perm_mean={mp:6.3f} z={z:6.3f} p={p:.3f}{marker}")

            # Window summaries
            log(f"\n  Window summaries ({m}):")
            for w in PRIMARY_WINDOWS + SECONDARY_WINDOWS:
                obs_w, perm_w = window_summary(results, w)
                label = "PRIMARY  " if w in PRIMARY_WINDOWS else "SECONDARY"
                if obs_w is not None:
                        perm_str = f"{perm_w:.3f}" if perm_w is not None else "N/A"
                        log(f"    {label} -{w}d window: mean_obs={obs_w:.3f} mean_perm={perm_str}")
            # Collect output rows
            n_events = len(events)
            for rd in range(-WINDOW, WINDOW + 1):
                obs, mp, sp, z, p = results.get(rd, (None,)*5)
                n_obs = len(observed_epoch.get(rd, []))
                all_results.append({
                    'fault_id':        fault_id,
                    'magnitude_threshold': mag_threshold,
                    'metric':          m,
                    'rel_day':         rd,
                    'n_events':        n_events,
                    'n_obs':           n_obs,
                    'obs_mean':        obs,
                    'perm_mean':       mp,
                    'perm_std':        sp,
                    'zscore':          z,
                    'p_value_onetail': p,
                    'run_at_utc':      datetime.now(timezone.utc).isoformat(),
                    'permutation_iters': iters,
                })

    # Print final summary
    log("\n=== FINAL SUMMARY ===")
    log(f"{'fault_id':<20} {'metric':<15} {'window':<8} "
        f"{'obs_mean':>10} {'p_value':>8}")
    log("-" * 65)
    for row in all_results:
        if row['rel_day'] == -1:  # Use day -1 as representative
            log(f"  {row['fault_id']:<20} {row['metric']:<15} "
                f"{'day-1':>8} {row['obs_mean'] or 0:>10.3f} "
                f"{row['p_value_onetail'] or 1.0:>8.3f}")

    if dry_run:
        log("\nDry run — results not written to BigQuery")
        return all_results

    # Write to BigQuery
    if all_results:
        log(f"\nWriting {len(all_results)} rows to {OUTPUT_TABLE}...")

        # Create or replace table
        schema = [
            bigquery.SchemaField("fault_id",              "STRING"),
            bigquery.SchemaField("magnitude_threshold",   "FLOAT64"),
            bigquery.SchemaField("metric",                "STRING"),
            bigquery.SchemaField("rel_day",               "INT64"),
            bigquery.SchemaField("n_events",              "INT64"),
            bigquery.SchemaField("n_obs",                 "INT64"),
            bigquery.SchemaField("obs_mean",              "FLOAT64"),
            bigquery.SchemaField("perm_mean",             "FLOAT64"),
            bigquery.SchemaField("perm_std",              "FLOAT64"),
            bigquery.SchemaField("zscore",                "FLOAT64"),
            bigquery.SchemaField("p_value_onetail",       "FLOAT64"),
            bigquery.SchemaField("run_at_utc",            "STRING"),
            bigquery.SchemaField("permutation_iters",     "INT64"),
        ]

        table_ref = bq.dataset("sentinel_analysis").table("hac_epoch_zscores")
        table = bigquery.Table(table_ref, schema=schema)
        table = bq.create_table(table, exists_ok=True)

        errors = bq.insert_rows_json(OUTPUT_TABLE, all_results)
        if errors:
            log(f"  Write errors: {errors[:3]}")
        else:
            log(f"  Written successfully to {OUTPUT_TABLE}")

    log("=== Analysis complete ===")
    return all_results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('--mag',     type=float, default=6.0,
                    help='Magnitude threshold (default 6.0)')
    ap.add_argument('--fault',   type=str,   default=None,
                    help='Single fault_id to run (default: all)')
    ap.add_argument('--iters',   type=int,   default=2000,
                    help='Permutation iterations (default 2000)')
    ap.add_argument('--metric',  type=str,   default='zscore',
                    choices=['zscore','high_urgency','water',
                             'high_emotion','all'],
                    help='HAC metric to analyze (default: zscore)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Run analysis but do not write to BigQuery')
    args = ap.parse_args()

    run_analysis(
        mag_threshold=args.mag,
        fault_filter=args.fault,
        iters=args.iters,
        dry_run=args.dry_run,
        metric=args.metric,
    )
