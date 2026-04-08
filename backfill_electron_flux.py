#!/usr/bin/env python3
"""
backfill_electron_flux.py  (v2 - corrected URLs and parser)
============================================================
Backfills sentinel_features.env_daily.electron_flux_max
with daily >2 MeV electron fluence (electrons/cm2/day/sr).

Sources:
  2001-2025: NOAA NCEI dayind.txt files
             URL: .../space_weather_indices/{YYYY}/{MM}/{YYYYMMDD}dayind.txt
             Particle_Data section, >2 MeV column (5th value on data line)
             Missing/bad values coded as -1.00e+00

  Recent gaps: SWPC JSON integral-electrons endpoint
               Aggregated to daily max flux
"""

import sys
import time
import argparse
import requests
from datetime import date, timedelta
from collections import defaultdict
from google.cloud import bigquery

PROJECT    = "synexis-project-sentinel"
TABLE      = f"{PROJECT}.sentinel_features.env_daily"
START_DATE = date(2011, 1, 1)
END_DATE   = date(2026, 3, 6)

DAYIND_BASE = (
    "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/"
    "daily_reports/space_weather_indices"
)
SWPC_JSON = (
    "https://services.swpc.noaa.gov/json/goes/primary/"
    "integral-electrons-7-day.json"
)
HEADERS = {"User-Agent": "SentinelProject/1.0 research@synexisproject.com"}


def parse_dayind(text):
    """
    Extract >2 MeV electron fluence from dayind.txt content.
    
    Relevant section:
        :Particle_Data: 2024 Jan 01
        #  ->1 MeV   >10 MeV  >100 MeV     >0.8 MeV     >2 MeV
          2.85e+07  8.11e+04 -1.00e+00    -1.00e+00   2.66e+06
    
    The >2 MeV value is the 5th number on the data line.
    Returns float or None (-1 = missing/invalid).
    """
    in_particle = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith(":Particle_Data:"):
            in_particle = True
            continue

        if in_particle:
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.startswith(":"):
                break  # next section

            parts = stripped.split()
            if len(parts) >= 5:
                try:
                    val = float(parts[4])  # 5th column = >2 MeV
                    return val if val > 0 else None
                except (ValueError, IndexError):
                    pass
            break  # only one data line expected

    return None


def fetch_dayind(d):
    yyyy = d.strftime("%Y")
    mm   = d.strftime("%m")
    ds   = d.strftime("%Y%m%d")
    url  = f"{DAYIND_BASE}/{yyyy}/{mm}/{ds}dayind.txt"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200 and ":Particle_Data:" in r.text:
            return r.text
        return None
    except Exception:
        return None


def fetch_swpc_recent():
    """Fetch last 7 days from SWPC JSON, aggregate to daily max."""
    result = defaultdict(list)
    try:
        r = requests.get(SWPC_JSON, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return {}
        for entry in r.json():
            if "2" not in entry.get("energy", ""):
                continue
            flux = entry.get("flux")
            tt   = entry.get("time_tag", "")[:10]
            if flux and float(flux) > 0:
                try:
                    result[date.fromisoformat(tt)].append(float(flux))
                except ValueError:
                    pass
        return {d: max(vals) for d, vals in result.items()}
    except Exception:
        return {}


def build_flux_map(start, end):
    flux_map = {}
    d       = start
    total   = (end - start).days + 1
    found   = 0
    errors  = 0
    count   = 0

    print(f"\nFetching {total} daily files ({start} to {end})...")

    while d <= end:
        text = fetch_dayind(d)
        if text:
            val = parse_dayind(text)
            if val is not None:
                flux_map[d] = val
                found += 1
        else:
            errors += 1

        count += 1
        if count % 100 == 0:
            pct = 100 * count / total
            print(f"  [{pct:5.1f}%] {d}  found={found}  no_data={errors}")

        d += timedelta(days=1)
        time.sleep(0.05)

    # Fill recent gaps from SWPC live JSON
    print("\nChecking SWPC JSON for recent gaps...")
    for rd, flux in fetch_swpc_recent().items():
        if rd not in flux_map and start <= rd <= end:
            flux_map[rd] = flux
            print(f"  SWPC supplement: {rd} = {flux:.2e}")

    print(f"\n── Fetch complete ──")
    print(f"  Days with data: {len(flux_map)} / {total} ({100*len(flux_map)/total:.1f}%)")

    # Spot checks on known big solar events
    for sd, label in [
        (date(2003, 10, 28), "Halloween 2003"),
        (date(2012, 3,  7),  "Mar 2012 SEP"),
        (date(2024, 5, 10),  "May 2024 storm"),
    ]:
        if start <= sd <= end:
            v = flux_map.get(sd)
            print(f"  {label} ({sd}): {v:.3e}" if v else f"  {label} ({sd}): NULL")

    return flux_map


def update_bigquery(flux_map, dry_run=False):
    rows = [{"day": d.isoformat(), "electron_flux_max": v}
            for d, v in sorted(flux_map.items())]

    print(f"\n── {'DRY RUN — ' if dry_run else ''}Writing {len(rows)} rows ──")

    if dry_run:
        for row in rows[:8]:
            print(f"  {row}")
        print(f"  ... ({len(rows)} total)")
        return

    client    = bigquery.Client(project=PROJECT)
    tmp_table = f"{PROJECT}.sentinel_features._electron_tmp"

    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("day",               "DATE"),
            bigquery.SchemaField("electron_flux_max", "FLOAT64"),
        ],
        write_disposition="WRITE_TRUNCATE",
    )
    client.load_table_from_json(rows, tmp_table, job_config=job_config).result()
    print("  Temp table loaded.")

    client.query(f"""
        MERGE `{TABLE}` T
        USING `{tmp_table}` S
        ON T.day = S.day
        WHEN MATCHED THEN
          UPDATE SET T.electron_flux_max = S.electron_flux_max
    """).result()
    print("  MERGE complete.")
    client.delete_table(tmp_table, not_found_ok=True)

    for row in client.query(f"""
        SELECT
          COUNTIF(electron_flux_max IS NOT NULL) as filled,
          COUNTIF(electron_flux_max IS NULL)     as empty,
          MIN(electron_flux_max) as min_val,
          MAX(electron_flux_max) as max_val
        FROM `{TABLE}`
    """).result():
        total = row.filled + row.empty
        print(f"\n── BQ Validation ──")
        print(f"  Filled: {row.filled} / {total} ({100*row.filled/total:.1f}%)")
        print(f"  Min:    {row.min_val:.3e}")
        print(f"  Max:    {row.max_val:.3e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample",  action="store_true",
                        help="Fetch only Jan 2024 as a format check")
    args = parser.parse_args()

    start = date(2024, 1, 1) if args.sample else START_DATE
    end   = date(2024, 1, 31) if args.sample else END_DATE

    print("=" * 60)
    print("  SENTINEL: electron_flux_max backfill (v2)")
    print(f"  Range: {start} → {end}")
    print(f"  Mode:  {'SAMPLE' if args.sample else 'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    flux_map = build_flux_map(start, end)
    update_bigquery(flux_map, dry_run=(args.dry_run or args.sample))
    print("\nDone.")


if __name__ == "__main__":
    main()
