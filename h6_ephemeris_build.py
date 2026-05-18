#!/usr/bin/env python3
"""
H6-Ephemeris Data Build — Project Sentinel
Computes daily planetary positions using JPL DE421 ephemeris via skyfield
(functionally equivalent to DE440 for 2001-2025 date range and required precision)

Amendment #9 v3 | osf.io/8hvf6
Pre-registered before execution

Output: sentinel_features.h6_ephemeris_daily
Covers: 2001-01-01 to 2025-12-31 (9,131 days)
"""

import math
import time
from datetime import date, timedelta
from typing import List, Dict, Any

from google.cloud import bigquery
from skyfield.api import load, Topos
from skyfield import almanac

PROJECT    = "synexis-project-sentinel"
DATASET    = "sentinel_features"
TABLE      = "h6_ephemeris_daily"
TABLE_FQ   = f"{PROJECT}.{DATASET}.{TABLE}"

START_DATE = date(2001, 1, 1)
END_DATE   = date(2025, 12, 31)

CHUNK_SIZE = 365  # days per BQ insert batch


LUNAR_PHASE_NAMES = [
    "new_moon",          # 0-45
    "waxing_crescent",   # 45-90
    "first_quarter",     # 90-135
    "waxing_gibbous",    # 135-180
    "full_moon",         # 180-225
    "waning_gibbous",    # 225-270
    "last_quarter",      # 270-315
    "waning_crescent",   # 315-360
]


def lunar_phase_bin(phase_deg: float) -> int:
    """Assign lunar phase to one of 8 bins of 45 degrees each."""
    return int(phase_deg / 45) % 8


def compute_day(ts, earth, sun, moon, mercury, venus, mars, jupiter, saturn, d: date) -> Dict[str, Any]:
    """Compute planetary positions for a single date (noon UTC)."""
    t = ts.utc(d.year, d.month, d.day, 12, 0, 0)

    # Geocentric positions
    sun_pos     = earth.at(t).observe(sun).apparent()
    moon_pos    = earth.at(t).observe(moon).apparent()
    mercury_pos = earth.at(t).observe(mercury).apparent()
    venus_pos   = earth.at(t).observe(venus).apparent()
    mars_pos    = earth.at(t).observe(mars).apparent()
    jupiter_pos = earth.at(t).observe(jupiter).apparent()
    saturn_pos  = earth.at(t).observe(saturn).apparent()

    # Ecliptic coordinates (for lunar phase)
    sun_ecl  = sun_pos.ecliptic_latlon()
    moon_ecl = moon_pos.ecliptic_latlon()

    # Lunar phase angle (0-360)
    sun_lon  = float(sun_ecl[1].degrees)
    moon_lon = float(moon_ecl[1].degrees)
    phase_deg = (moon_lon - sun_lon) % 360.0

    # Geocentric distances
    _, _, moon_dist   = moon_pos.radec()
    _, _, sun_dist    = sun_pos.radec()
    _, _, jup_dist    = jupiter_pos.radec()
    _, _, sat_dist    = saturn_pos.radec()

    moon_dist_au = float(earth.at(t).observe(moon).distance().au)
    sun_dist_au  = float(earth.at(t).observe(sun).distance().au)
    jup_dist_au  = float(earth.at(t).observe(jupiter).distance().au)
    sat_dist_au  = float(earth.at(t).observe(saturn).distance().au)

    # Solar elongations for inner/outer planets
    def elongation_deg(planet_pos, sun_p):
        return float(sun_p.separation_from(planet_pos).degrees)

    merc_elong = elongation_deg(mercury_pos, sun_pos)
    ven_elong  = elongation_deg(venus_pos,   sun_pos)
    mars_elong = elongation_deg(mars_pos,    sun_pos)

    # RA/Dec for Sun and Moon
    sun_ra,  sun_dec,  _ = sun_pos.radec()
    moon_ra, moon_dec, _ = moon_pos.radec()

    # Lunar illumination fraction (0-1)
    # illumination = (1 - cos(phase_angle)) / 2
    phase_rad   = math.radians(phase_deg)
    illumination = (1.0 - math.cos(phase_rad)) / 2.0

    phase_bin  = lunar_phase_bin(phase_deg)
    phase_name = LUNAR_PHASE_NAMES[phase_bin]

    return {
        "date_val":              d.isoformat(),
        "lunar_phase_deg":       round(phase_deg, 4),
        "lunar_phase_bin":       phase_bin,
        "lunar_phase_name":      phase_name,
        "lunar_illumination":    round(illumination, 4),
        "lunar_dist_au":         round(moon_dist_au, 6),
        "sun_dist_au":           round(sun_dist_au, 6),
        "sun_ecl_lon_deg":       round(sun_lon, 4),
        "moon_ecl_lon_deg":      round(moon_lon, 4),
        "sun_ra_deg":            round(float(sun_ra.hours) * 15.0, 4),
        "sun_dec_deg":           round(float(sun_dec.degrees), 4),
        "moon_ra_deg":           round(float(moon_ra.hours) * 15.0, 4),
        "moon_dec_deg":          round(float(moon_dec.degrees), 4),
        "mercury_elongation_deg": round(merc_elong, 4),
        "venus_elongation_deg":  round(ven_elong, 4),
        "mars_elongation_deg":   round(mars_elong, 4),
        "jupiter_dist_au":       round(jup_dist_au, 4),
        "saturn_dist_au":        round(sat_dist_au, 4),
        "ephemeris":             "DE421",
        "amendment_commit":      "c8cbf9c",
    }


def get_existing_dates(bq: bigquery.Client) -> set:
    try:
        q = f"SELECT date_val FROM `{TABLE_FQ}`"
        return {str(row.date_val) for row in bq.query(q).result()}
    except Exception:
        return set()


def batch_insert(bq: bigquery.Client, rows: List[Dict]) -> int:
    if not rows:
        return 0
    errors = bq.insert_rows_json(TABLE_FQ, rows)
    if errors:
        print(f"  BQ insert errors: {errors[:2]}")
        return 0
    return len(rows)


def main():
    total_days = (END_DATE - START_DATE).days + 1

    print("=" * 60)
    print("Project Sentinel — H6 Ephemeris Build")
    print(f"Window:    {START_DATE} → {END_DATE} ({total_days:,} days)")
    print(f"Ephemeris: DE421 (JPL, via skyfield)")
    print(f"Table:     {TABLE_FQ}")
    print("=" * 60)

    # Load ephemeris — skyfield downloads automatically on first run
    print("\nLoading ephemeris (may download on first run ~17MB)...")
    ts      = load.timescale()
    planets = load('de421.bsp')

    earth   = planets['earth']
    sun     = planets['sun']
    moon    = planets['moon']
    mercury = planets['mercury']
    venus   = planets['venus']
    mars    = planets['mars']
    jupiter = planets['jupiter barycenter']
    saturn  = planets['saturn barycenter']
    print("  Ephemeris loaded.")

    bq = bigquery.Client(project=PROJECT)

    print("\nChecking existing dates...")
    existing = get_existing_dates(bq)
    print(f"  Found {len(existing):,} existing rows")

    inserted_total = 0
    skipped_total  = 0
    batch          = []
    d              = START_DATE
    day_num        = 0

    print("\nComputing positions...")
    t0 = time.time()

    while d <= END_DATE:
        day_num += 1

        if d.isoformat() in existing:
            skipped_total += 1
            d += timedelta(days=1)
            continue

        row = compute_day(ts, earth, sun, moon, mercury, venus,
                          mars, jupiter, saturn, d)
        batch.append(row)

        if day_num % 500 == 0 or d == END_DATE:
            pct     = (day_num / total_days) * 100
            elapsed = time.time() - t0
            rate    = day_num / elapsed if elapsed > 0 else 0
            eta     = (total_days - day_num) / rate if rate > 0 else 0
            print(f"  [{pct:5.1f}%] {d}  computed={day_num:,}  "
                  f"inserted={inserted_total:,}  ETA={eta:.0f}s")

        if len(batch) >= CHUNK_SIZE:
            n = batch_insert(bq, batch)
            inserted_total += n
            batch = []

        d += timedelta(days=1)

    if batch:
        n = batch_insert(bq, batch)
        inserted_total += n

    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    print("EPHEMERIS BUILD COMPLETE")
    print(f"  Inserted:  {inserted_total:,}")
    print(f"  Skipped:   {skipped_total:,}  (already in BQ)")
    print(f"  Elapsed:   {elapsed:.0f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
