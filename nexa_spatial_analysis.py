#!/usr/bin/env python3
"""
nexa_spatial_analysis.py

Two-signal spatial correspondence analysis for NEXA corpus:
  Signal 1 (proximity): experiencer location -> event location distance
  Signal 2 (specificity): referred location -> event location distance

Fixes US state-level experiencer coordinates before running analysis.
"""

import math
import random
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
bq      = bigquery.Client(project=PROJECT)

def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)

# ── US State centroids ────────────────────────────────────────────────────────
STATE_CENTROIDS = {
    'Alabama':        (32.806, -86.791), 'Alaska':         (61.370, -152.404),
    'Arizona':        (33.729, -111.431),'Arkansas':       (34.969, -92.373),
    'California':     (36.778, -119.417),'Colorado':       (39.550, -105.782),
    'Connecticut':    (41.603, -73.087), 'Delaware':       (38.910, -75.527),
    'Florida':        (27.766, -81.686), 'Georgia':        (32.677, -83.223),
    'Hawaii':         (21.095, -157.498),'Idaho':          (44.240, -114.479),
    'Illinois':       (40.349, -88.986), 'Indiana':        (39.849, -86.258),
    'Iowa':           (42.011, -93.210), 'Kansas':         (38.526, -96.726),
    'Kentucky':       (37.668, -84.670), 'Louisiana':      (31.169, -91.867),
    'Maine':          (44.693, -69.381), 'Maryland':       (39.063, -76.802),
    'Massachusetts':  (42.230, -71.530), 'Michigan':       (43.327, -84.536),
    'Minnesota':      (45.694, -93.900), 'Mississippi':    (32.741, -89.678),
    'Missouri':       (38.456, -92.288), 'Montana':        (46.921, -110.454),
    'Nebraska':       (41.125, -98.268), 'Nevada':         (38.313, -117.055),
    'New Hampshire':  (43.452, -71.563), 'New Jersey':     (40.298, -74.521),
    'New Mexico':     (34.841, -106.248),'New York':       (42.165, -74.948),
    'North Carolina': (35.630, -79.806), 'North Dakota':   (47.528, -99.784),
    'Ohio':           (40.388, -82.764), 'Oklahoma':       (35.565, -96.928),
    'Oregon':         (43.804, -120.554),'Pennsylvania':   (40.590, -77.209),
    'Rhode Island':   (41.680, -71.511), 'South Carolina': (33.856, -80.945),
    'South Dakota':   (44.299, -99.438), 'Tennessee':      (35.747, -86.692),
    'Texas':          (31.054, -97.563), 'Utah':           (39.321, -111.093),
    'Vermont':        (44.045, -72.710), 'Virginia':       (37.769, -78.169),
    'Washington':     (47.400, -121.490),'West Virginia':  (38.491, -80.954),
    'Wisconsin':      (44.268, -89.616), 'Wyoming':        (42.755, -107.302),
}

def fix_us_experiencer_coords():
    """Update experiencer coords for US records using state centroids."""
    log("Fixing US experiencer coordinates by state...")
    fixed = 0
    for state, (lat, lon) in STATE_CENTROIDS.items():
        job = bq.query("""
            UPDATE `synexis-project-sentinel.hac_intake.hac_normalized`
            SET experiencer_lat_approx = @lat,
                experiencer_lon_approx = @lon
            WHERE source_type = 'archive_nexa'
              AND experiencer_location_country = 'United States of America'
              AND experiencer_location_region = @state
              AND (ABS(experiencer_lat_approx - 38.0) < 1
                   AND ABS(experiencer_lon_approx + 97.0) < 1)
        """, job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("lat",   "FLOAT64", lat),
            bigquery.ScalarQueryParameter("lon",   "FLOAT64", lon),
            bigquery.ScalarQueryParameter("state", "STRING",  state),
        ]))
        result = job.result()
        if job.num_dml_affected_rows and job.num_dml_affected_rows > 0:
            log(f"  {state}: updated {job.num_dml_affected_rows} records -> ({lat:.1f}, {lon:.1f})")
            fixed += job.num_dml_affected_rows
    log(f"Total experiencer coords fixed: {fixed}")


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def load_nexa_records():
    """Load NEXA records with spatial data and hazard classification."""
    rows = list(bq.query("""
        SELECT
          n.submission_id,
          DATE(n.experience_date) AS dream_date,
          n.referred_location_text,
          n.referred_location_type,
          n.referred_lat_approx   AS ref_lat,
          n.referred_lon_approx   AS ref_lon,
          n.experiencer_lat_approx AS exp_lat,
          n.experiencer_lon_approx AS exp_lon,
          n.experiencer_location_country AS exp_country,
          n.experiencer_location_region  AS exp_region,
          e.hazard_type,
          LEFT(n.narrative_text, 150) AS narrative_preview
        FROM `synexis-project-sentinel.hac_intake.hac_normalized` n
        JOIN `synexis-project-sentinel.hac_intake.hac_enrichment` e
          USING (submission_id)
        WHERE n.source_type = 'archive_nexa'
          AND n.referred_lat_approx IS NOT NULL
          AND e.hazard_type NOT IN ('none')
          AND n.experience_date IS NOT NULL
        ORDER BY n.experience_date
    """).result())
    log(f"Loaded {len(rows)} NEXA records with spatial data")
    return rows


def load_events(hazard, window_days=30):
    """Load events for a hazard type with coordinates."""
    rows = list(bq.query("""
        SELECT event_id, DATE(start_ts) AS event_date, lat, lon, region, mag
        FROM `synexis-project-sentinel.sentinel_groundtruth.events`
        WHERE hazard = @hazard
          AND lat IS NOT NULL AND lon IS NOT NULL
          AND DATE(start_ts) BETWEEN '2000-01-01' AND '2026-12-31'
        ORDER BY start_ts
    """, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("hazard", "STRING", hazard)
    ])).result())
    return rows


def find_nearest_event(lat, lon, dream_date, events, min_days=0, max_days=30):
    """Find nearest event within time window. Returns (min_km, event) or (None, None)."""
    candidates = [
        e for e in events
        if min_days <= (e.event_date - dream_date).days <= max_days
        and e.lat is not None and e.lon is not None
    ]
    if not candidates:
        return None, None
    distances = [(haversine(lat, lon, e.lat, e.lon), e) for e in candidates]
    return min(distances, key=lambda x: x[0])


def run_spatial_analysis(records, all_events_by_hazard, window_days=30, n_perms=1000):
    """
    For each NEXA record, compute:
      - ref_km: referred location -> nearest event distance
      - exp_km: experiencer location -> nearest event distance
    Then permutation test: shuffle event dates, recompute distances,
    compare observed mean distance vs permuted mean distance.
    """
    log(f"\n=== Dual-Signal Spatial Correspondence Analysis ===")
    log(f"Window: {window_days} days | Permutations: {n_perms}")

    results = []

    for row in records:
        hazard = row.hazard_type
        if hazard == 'multiple':
            hazards = ['earthquake', 'tsunami', 'flood', 'volcanic', 'landslide']
        else:
            hazards = [hazard]

        best_ref_km = None
        best_exp_km = None
        best_event  = None

        for h in hazards:
            events = all_events_by_hazard.get(h, [])
            if not events:
                continue

            # Signal 2: referred location -> event
            if row.ref_lat and row.ref_lon:
                ref_km, ev = find_nearest_event(
                    row.ref_lat, row.ref_lon, row.dream_date, events,
                    min_days=0, max_days=window_days
                )
                if ref_km is not None:
                    if best_ref_km is None or ref_km < best_ref_km:
                        best_ref_km = ref_km
                        best_event  = ev

            # Signal 1: experiencer location -> event
            if row.exp_lat and row.exp_lon:
                exp_km, _ = find_nearest_event(
                    row.exp_lat, row.exp_lon, row.dream_date, events,
                    min_days=0, max_days=window_days
                )
                if exp_km is not None:
                    if best_exp_km is None or exp_km < best_exp_km:
                        best_exp_km = exp_km

        results.append({
            'submission_id':    row.submission_id,
            'dream_date':       row.dream_date,
            'hazard_type':      row.hazard_type,
            'ref_location':     row.referred_location_text,
            'exp_country':      row.exp_country,
            'exp_region':       row.exp_region,
            'ref_lat':          row.ref_lat,
            'ref_lon':          row.ref_lon,
            'exp_lat':          row.exp_lat,
            'exp_lon':          row.exp_lon,
            'ref_km':           best_ref_km,
            'exp_km':           best_exp_km,
            'nearest_event':    best_event.region if best_event else None,
            'nearest_event_date': str(best_event.event_date) if best_event else None,
            'narrative':        row.narrative_preview,
        })

    # Filter to records with valid distances
    ref_valid = [r for r in results if r['ref_km'] is not None]
    exp_valid = [r for r in results if r['exp_km'] is not None]

    log(f"\nRecords with valid referred distance:    {len(ref_valid)}")
    log(f"Records with valid experiencer distance: {len(exp_valid)}")

    if ref_valid:
        mean_ref = sum(r['ref_km'] for r in ref_valid) / len(ref_valid)
        median_ref = sorted(r['ref_km'] for r in ref_valid)[len(ref_valid)//2]
        log(f"\nSignal 2 (referred -> event):")
        log(f"  Mean distance:   {mean_ref:.0f} km")
        log(f"  Median distance: {median_ref:.0f} km")

        # Print individual records sorted by distance
        log(f"\n  Individual records (sorted by ref_km):")
        for r in sorted(ref_valid, key=lambda x: x['ref_km']):
            log(f"    {str(r['dream_date']):<12} {r['hazard_type']:<12} "
                f"{str(r['ref_location'] or ''):<20} "
                f"ref={r['ref_km']:6.0f}km  "
                f"exp={r['exp_km']:6.0f}km  "
                f"event={r['nearest_event_date']} {str(r['nearest_event'] or '')[:35]}")

    # Permutation test for referred distances
    if len(ref_valid) >= 5:
        log(f"\nPermutation test (Signal 2 — referred distances)...")
        obs_mean_ref = sum(r['ref_km'] for r in ref_valid) / len(ref_valid)

        all_dates = []
        for h_events in all_events_by_hazard.values():
            all_dates.extend([e.event_date for e in h_events])
        all_dates = sorted(set(all_dates))

        perm_means = []
        rng = random.Random(42)
        for _ in range(n_perms):
            perm_dists = []
            for r in ref_valid:
                hazard = r['hazard_type']
                hazards = (['earthquake','tsunami','flood','volcanic','landslide']
                           if hazard == 'multiple' else [hazard])
                best_perm_km = None
                for h in hazards:
                    events = all_events_by_hazard.get(h, [])
                    if not events:
                        continue
                    # Shuffle by random offset
                    offset = rng.randint(-365, 365)
                    from datetime import date
                    fake_date = r['dream_date'] + timedelta(days=offset)
                    km, _ = find_nearest_event(
                        r['ref_lat'], r['ref_lon'], fake_date, events,
                        min_days=0, max_days=window_days
                    )
                    if km is not None:
                        if best_perm_km is None or km < best_perm_km:
                            best_perm_km = km
                if best_perm_km is not None:
                    perm_dists.append(best_perm_km)
            if perm_dists:
                perm_means.append(sum(perm_dists) / len(perm_dists))

        if perm_means:
            mean_perm = sum(perm_means) / len(perm_means)
            std_perm  = (sum((x - mean_perm)**2 for x in perm_means) / len(perm_means))**0.5
            z = (obs_mean_ref - mean_perm) / std_perm if std_perm > 0 else 0
            p = sum(1 for pm in perm_means if pm <= obs_mean_ref) / len(perm_means)

            log(f"  Observed mean ref distance: {obs_mean_ref:.0f} km")
            log(f"  Permuted mean ref distance: {mean_perm:.0f} km")
            log(f"  Z-score: {z:.3f}  (negative = observed closer than chance)")
            log(f"  P-value (one-tail, smaller=better): {p:.4f}")

            if p < 0.05:
                log(f"  *** SIGNIFICANT: dream reference locations are closer to events "
                    f"than expected by chance (p={p:.4f})")
            else:
                log(f"  Not significant at p<0.05")

    return results


def main():
    # Step 1: Fix US state coordinates
    fix_us_experiencer_coords()

    # Step 2: Load NEXA records
    records = load_nexa_records()

    # Step 3: Load all event catalogs
    log("\nLoading event catalogs...")
    hazards = ['earthquake', 'tsunami', 'flood', 'volcanic', 'landslide']
    all_events = {}
    for h in hazards:
        evs = load_events(h)
        all_events[h] = evs
        log(f"  {h}: {len(evs)} events with coordinates")

    # Step 4: Run spatial analysis
    results = run_spatial_analysis(records, all_events, window_days=30, n_perms=1000)

    log(f"\n=== Done ===")


if __name__ == "__main__":
    main()
