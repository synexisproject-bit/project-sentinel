#!/usr/bin/env python3
"""
hac_superposed_epoch_stratified.py

Pre-registered stratified superposed epoch analysis for the HAC stream.
Tests whether daily HAC content is elevated before events across all six
Project Sentinel hazard types, with hazard-type matching per Amendment #3.

Pre-registration: Amendment #3, April 2026
GitHub: github.com/synexisproject-bit/project-sentinel

Analysis design:
  - Anchors on events in sentinel_groundtruth.events by hazard type
  - Signal: hac_features_daily stratified by hazard_type field
  - HAC records matched by hazard_type to event catalog
  - Primary windows: 3d, 5d, 7d pre-event
  - Secondary windows: 14d, 30d (exploratory)
  - Method: superposed epoch analysis, 2000 permutation null distribution
  - Multiple comparisons: Bonferroni correction across hazard types
  - Output: writes to sentinel_analysis.hac_epoch_zscores_stratified

Hazard types: earthquake, tsunami, flood, volcanic, avalanche, landslide

Usage:
  # Run single hazard
  python3 hac_superposed_epoch_stratified.py --hazard earthquake

  # Run all hazards
  python3 hac_superposed_epoch_stratified.py --hazard all

  # Run with options
  python3 hac_superposed_epoch_stratified.py --hazard tsunami --iters 1000 --dry-run

  # Run without hazard-type matching (include all geophysical records)
  python3 hac_superposed_epoch_stratified.py --hazard earthquake --no-hazard-filter
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone

import numpy as np
from google.cloud import bigquery

PROJECT      = "synexis-project-sentinel"
EVENTS_TABLE = f"{PROJECT}.sentinel_groundtruth.events"
HAC_TABLE    = f"{PROJECT}.hac_intake.hac_normalized"
ENRICH_TABLE = f"{PROJECT}.hac_intake.hac_enrichment"
OUTPUT_TABLE = f"{PROJECT}.sentinel_analysis.hac_epoch_zscores_stratified"

WINDOW           = 7
PRIMARY_WINDOWS  = [3, 5, 7]
SECONDARY_WINDOWS = [14, 30]

# Bonferroni correction: 5 hazard types tested (avalanche pending)
N_HAZARD_TYPES    = 5
BONFERRONI_ALPHA  = 0.05 / N_HAZARD_TYPES  # 0.01

# Minimum events required for permutation test (per Amendment #3 Section 3.3)
MIN_EVENTS = 50

# HAC hazard_type values that map to each event catalog
HAZARD_HAC_MAP = {
    'earthquake': ['earthquake'],
    'tsunami':    ['tsunami'],
    'flood':      ['flood'],
    'volcanic':   ['volcanic'],
    'landslide':  ['landslide'],
    'avalanche':  ['avalanche'],
    # 'multiple' records are evaluated against all hazard types
}

bq = bigquery.Client(project=PROJECT)


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# ── Load events from unified catalog ─────────────────────────────────────────

def load_events(hazard, min_mag=None, exclude_source=None):
    """
    Load events for a given hazard type from sentinel_groundtruth.events.
    Returns list of (event_date, lat, lon, mag) tuples.
    """
    source_filter = ""
    if exclude_source:
        source_filter = f"AND source NOT LIKE '%{exclude_source}%'"

    mag_filter = ""
    if min_mag is not None:
        mag_filter = f"AND (mag IS NULL OR mag >= {min_mag})"

    query = f"""
    SELECT DATE(start_ts) AS event_date, lat, lon, mag, region, source
    FROM `{EVENTS_TABLE}`
    WHERE hazard = @hazard
      AND DATE(start_ts) BETWEEN '2000-01-01' AND '2026-12-31'
      {source_filter}
      {mag_filter}
    ORDER BY start_ts
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("hazard", "STRING", hazard)
    ])
    rows = list(bq.query(query, job_config=cfg).result())
    log(f"  Loaded {len(rows)} {hazard} events")
    return rows


# ── Load HAC daily signal stratified by hazard type ──────────────────────────

def load_hac_signal_stratified(hazard, use_hazard_filter=True):
    """
    Load daily HAC signal for a specific hazard type.

    If use_hazard_filter=True: only include records where
    hac_enrichment.hazard_type matches the target hazard (or 'multiple').
    This is the pre-registered primary analysis per Amendment #3.

    If use_hazard_filter=False: include all geophysical records regardless
    of hazard_type. This matches the original Amendment #2 analysis.

    Returns dict: date -> {count, high_urgency, water, high_emotion, zscore}
    """
    if use_hazard_filter:
        hazard_clause = f"""
        AND (
            e.hazard_type = @hazard
            OR e.hazard_type = 'multiple'
        )
        """
    else:
        hazard_clause = "AND n.is_geophysical = TRUE"

    query = f"""
    WITH daily AS (
        SELECT
            n.experience_date AS date_val,
            COUNT(*) AS hac_count,
            COUNTIF(e.urgency_level = 'high') AS hac_count_high_urgency,
            COUNTIF(e.water_imagery = TRUE) AS hac_count_water,
            COUNTIF(
                e.llm_extracted_emotion IN (
                    'fear','terror','dread','panic','horror',
                    'anxiety','distress','despair','urgency'
                )
            ) AS hac_count_high_emotion
        FROM `{HAC_TABLE}` n
        JOIN `{ENRICH_TABLE}` e USING (submission_id)
        WHERE n.normalized_status NOT IN ('date_unreliable')
            AND (n.is_duplicate IS NULL OR n.is_duplicate = FALSE)
            AND n.experience_date IS NOT NULL
            {hazard_clause}
        GROUP BY date_val
    ),
    stats AS (
        SELECT
            AVG(hac_count) AS mean_count,
            STDDEV(hac_count) AS std_count
        FROM daily
        WHERE hac_count > 0
    )
    SELECT
        d.date_val,
        d.hac_count,
        d.hac_count_high_urgency,
        d.hac_count_water,
        d.hac_count_high_emotion,
        SAFE_DIVIDE(d.hac_count - s.mean_count, s.std_count) AS hac_count_zscore
    FROM daily d
    CROSS JOIN stats s
    ORDER BY d.date_val
    """
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("hazard", "STRING", hazard)
    ])
    rows = list(bq.query(query, job_config=cfg).result())

    signal = {}
    for r in rows:
        signal[r.date_val] = {
            'zscore':       r.hac_count_zscore,
            'count':        r.hac_count,
            'high_urgency': r.hac_count_high_urgency,
            'water':        r.hac_count_water,
            'high_emotion': r.hac_count_high_emotion,
        }
    log(f"  Signal loaded: {len(signal)} days with {hazard} HAC records")
    return signal


# ── Superposed epoch analysis (same as Amendment #2 version) ─────────────────

def extract_epoch(events, signal, metric='zscore', window=WINDOW):
    epoch = defaultdict(list)
    for row in events:
        event_date = row.event_date
        for rel_day in range(-window, window + 1):
            d = event_date + timedelta(days=rel_day)
            if d in signal and signal[d][metric] is not None:
                epoch[rel_day].append(signal[d][metric])
    return epoch


def mean_epoch(epoch):
    return {
        rel_day: float(np.mean(vals)) if vals else None
        for rel_day, vals in epoch.items()
    }


def permutation_test(events, signal, metric='zscore', window=WINDOW,
                     iters=2000, seed=42):
    rng = np.random.default_rng(seed)
    all_dates = sorted(signal.keys())

    perm_means = defaultdict(list)
    for _ in range(iters):
        shuffled = []
        for row in events:
            offset = int(rng.integers(365, 730)) * int(rng.choice([-1, 1]))
            candidate = row.event_date + timedelta(days=offset)
            if candidate < all_dates[0]:
                candidate = all_dates[0] + timedelta(days=int(rng.integers(0, 30)))
            if candidate > all_dates[-1]:
                candidate = all_dates[-1] - timedelta(days=int(rng.integers(0, 30)))

            class FakeRow:
                def __init__(self, d): self.event_date = d
            shuffled.append(FakeRow(candidate))

        perm_epoch = extract_epoch(shuffled, signal, metric, window)
        for rel_day in range(-window, window + 1):
            vals = perm_epoch.get(rel_day, [])
            if vals:
                perm_means[rel_day].append(float(np.mean(vals)))

    return perm_means


def compute_zscores(observed, perm_means):
    results = {}
    for rel_day in range(-WINDOW, WINDOW + 1):
        obs   = observed.get(rel_day)
        perms = perm_means.get(rel_day, [])
        if obs is None or not perms:
            results[rel_day] = (obs, None, None, None, None)
            continue
        mean_p = float(np.mean(perms))
        std_p  = float(np.std(perms))
        z = (obs - mean_p) / std_p if std_p > 0 else None
        p = float(np.mean([p >= obs for p in perms]))
        results[rel_day] = (obs, mean_p, std_p, z, p)
    return results


def window_summary(results, window_days):
    pre_obs = [results[d][0] for d in range(max(-WINDOW, -window_days), 0)
               if d in results and results[d][0] is not None]
    if not pre_obs:
        return None, None
    pre_perm = [results[d][1] for d in range(max(-WINDOW, -window_days), 0)
                if d in results and results[d][1] is not None]
    return float(np.mean(pre_obs)), float(np.mean(pre_perm)) if pre_perm else None


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_hazard(hazard, iters=2000, dry_run=False,
               use_hazard_filter=True, min_mag=None):
    """Run superposed epoch analysis for a single hazard type."""
    log(f"\n{'='*60}")
    log(f"HAZARD: {hazard.upper()}")
    log(f"{'='*60}")

    # Load events
    events = load_events(hazard, min_mag=min_mag)

    if len(events) < MIN_EVENTS:
        log(f"  SKIP: only {len(events)} events (minimum {MIN_EVENTS} required)")
        return []

    # Load HAC signal
    signal = load_hac_signal_stratified(hazard, use_hazard_filter)

    if len(signal) < 30:
        log(f"  SKIP: only {len(signal)} days of HAC signal for {hazard}")
        return []

    metrics = ['zscore', 'high_urgency', 'water', 'high_emotion']
    all_results = []

    for metric in metrics:
        log(f"\n  --- Metric: {metric} ---")

        observed_epoch = extract_epoch(events, signal, metric)
        observed_means = mean_epoch(observed_epoch)

        perm_means = permutation_test(events, signal, metric, WINDOW, iters)
        results    = compute_zscores(observed_means, perm_means)

        # Log rel_day profile
        log(f"  rel_day profile ({metric}):")
        for rd in range(-7, 8):
            obs, mp, sp, z, p = results.get(rd, (None,)*5)
            if obs is not None and z is not None:
                sig = ""
                if p is not None:
                    if p < BONFERRONI_ALPHA:
                        sig = " *** (Bonferroni)"
                    elif p < 0.05:
                        sig = " *"
                log(f"    day {rd:+3d}: obs={obs:7.3f} z={z:6.3f} p={p:.3f}{sig}")

        # Window summaries
        log(f"\n  Window summaries ({metric}):")
        for w in PRIMARY_WINDOWS:
            obs_w, perm_w = window_summary(results, w)
            if obs_w is not None:
                log(f"    PRIMARY   -{w}d: mean_obs={obs_w:.4f} mean_perm={perm_w:.4f}")
        for w in SECONDARY_WINDOWS:
            obs_w, perm_w = window_summary(results, w)
            if obs_w is not None:
                log(f"    SECONDARY -{w}d: mean_obs={obs_w:.4f} mean_perm={perm_w:.4f}")

        # Collect output rows
        for rd in range(-WINDOW, WINDOW + 1):
            obs, mp, sp, z, p = results.get(rd, (None,)*5)
            n_obs = len(observed_epoch.get(rd, []))
            all_results.append({
                'hazard_type':          hazard,
                'metric':               metric,
                'use_hazard_filter':    use_hazard_filter,
                'rel_day':              rd,
                'n_events':             len(events),
                'n_obs':                n_obs,
                'obs_mean':             obs,
                'perm_mean':            mp,
                'perm_std':             sp,
                'zscore':               z,
                'p_value_onetail':      p,
                'bonferroni_threshold': BONFERRONI_ALPHA,
                'significant_bonferroni': (p is not None and p < BONFERRONI_ALPHA),
                'run_at_utc':           datetime.now(timezone.utc).isoformat(),
                'permutation_iters':    iters,
            })

    return all_results


def write_results(rows, dry_run=False):
    if not rows:
        log("No results to write")
        return

    if dry_run:
        log(f"DRY RUN — would write {len(rows)} rows to {OUTPUT_TABLE}")
        return

    schema = [
        bigquery.SchemaField("hazard_type",             "STRING"),
        bigquery.SchemaField("metric",                  "STRING"),
        bigquery.SchemaField("use_hazard_filter",       "BOOL"),
        bigquery.SchemaField("rel_day",                 "INT64"),
        bigquery.SchemaField("n_events",                "INT64"),
        bigquery.SchemaField("n_obs",                   "INT64"),
        bigquery.SchemaField("obs_mean",                "FLOAT64"),
        bigquery.SchemaField("perm_mean",               "FLOAT64"),
        bigquery.SchemaField("perm_std",                "FLOAT64"),
        bigquery.SchemaField("zscore",                  "FLOAT64"),
        bigquery.SchemaField("p_value_onetail",         "FLOAT64"),
        bigquery.SchemaField("bonferroni_threshold",    "FLOAT64"),
        bigquery.SchemaField("significant_bonferroni",  "BOOL"),
        bigquery.SchemaField("run_at_utc",              "STRING"),
        bigquery.SchemaField("permutation_iters",       "INT64"),
    ]

    table_ref = bq.dataset("sentinel_analysis").table("hac_epoch_zscores_stratified")
    table = bigquery.Table(table_ref, schema=schema)
    table = bq.create_table(table, exists_ok=True)

    # Write in batches
    batch_size = 500
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        errors = bq.insert_rows_json(OUTPUT_TABLE, batch)
        if errors:
            log(f"  Write errors: {errors[:2]}")
        else:
            total += len(batch)

    log(f"Written {total} rows to {OUTPUT_TABLE}")


def main():
    ap = argparse.ArgumentParser(
        description="Stratified HAC superposed epoch analysis per Amendment #3"
    )
    ap.add_argument('--hazard', default='earthquake',
                    choices=['earthquake','tsunami','flood','volcanic',
                             'landslide','avalanche','all'],
                    help='Hazard type to analyze (default: earthquake)')
    ap.add_argument('--iters',   type=int,   default=2000,
                    help='Permutation iterations (default: 2000)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Run analysis but do not write to BigQuery')
    ap.add_argument('--no-hazard-filter', action='store_true',
                    help='Include all geophysical HAC records regardless of hazard_type')
    ap.add_argument('--min-mag', type=float, default=None,
                    help='Minimum magnitude filter for events')
    args = ap.parse_args()

    use_hazard_filter = not args.no_hazard_filter

    log("=== HAC Stratified Superposed Epoch Analysis ===")
    log(f"Hazard filter    : {use_hazard_filter} (Amendment #3 matching)")
    log(f"Permutation iters: {args.iters}")
    log(f"Bonferroni alpha : {BONFERRONI_ALPHA:.4f} ({N_HAZARD_TYPES} hazard types)")
    log(f"Dry run          : {args.dry_run}")

    hazards = (
        ['earthquake','tsunami','flood','volcanic','landslide']
        if args.hazard == 'all'
        else [args.hazard]
    )

    all_results = []
    for hazard in hazards:
        rows = run_hazard(
            hazard,
            iters=args.iters,
            dry_run=False,  # collect results regardless, write at end
            use_hazard_filter=use_hazard_filter,
            min_mag=args.min_mag,
        )
        all_results.extend(rows)

    # Final summary table
    log("\n=== FINAL SUMMARY ===")
    log(f"{'hazard':<12} {'metric':<15} {'day-5 z':>8} {'day-5 p':>8} "
        f"{'day-1 z':>8} {'day-1 p':>8} {'sig':>6}")
    log("-" * 72)
    for row in all_results:
        if row['rel_day'] == -5:
            # Find matching day -1
            d1 = next((r for r in all_results
                       if r['hazard_type'] == row['hazard_type']
                       and r['metric'] == row['metric']
                       and r['rel_day'] == -1), None)
            z5 = row['zscore'] or 0
            p5 = row['p_value_onetail'] or 1
            z1 = d1['zscore'] if d1 and d1['zscore'] else 0
            p1 = d1['p_value_onetail'] if d1 and d1['p_value_onetail'] else 1
            sig = "***" if (p5 < BONFERRONI_ALPHA or p1 < BONFERRONI_ALPHA) else \
                  "*  " if (p5 < 0.05 or p1 < 0.05) else "   "
            log(f"  {row['hazard_type']:<12} {row['metric']:<15} "
                f"{z5:8.3f} {p5:8.4f} {z1:8.3f} {p1:8.4f} {sig}")

    write_results(all_results, args.dry_run)
    log("\n=== Analysis complete ===")


if __name__ == '__main__':
    main()
