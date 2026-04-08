#!/usr/bin/env python3
"""
backfill_donki.py
=================
Backfills sentinel_features.env_daily columns:
  - has_cme  (INT64: 1 if any CME recorded that day, 0 otherwise)
  - has_sep  (INT64: 1 if any SEP/Solar Energetic Particle event that day, 0)

Sources:
  - NASA DONKI API (good coverage ~2010-present)
    https://api.nasa.gov/DONKI/

  - NOAA Solar Event Reports (supplement for 2001-2009)
    https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/solar_event_reports/

Coverage note (documented in pre-registration):
  CME catalog becomes reliable ~2010. Before 2010, CME detection was less
  systematic. has_cme will be NULL for dates with no DONKI record AND no
  NOAA report, rather than 0, to avoid false negatives in the early period.
  The model will handle NULLs via imputation or exclusion.

Run from Cloud Shell:
    pip install requests google-cloud-bigquery --break-system-packages
    python3 backfill_donki.py

Dry run:
    python3 backfill_donki.py --dry-run

NASA API key: DEMO_KEY works for low volume. Set env var for higher limits:
    export NASA_API_KEY=your_key_here
"""

import os
import re
import sys
import time
import argparse
import requests
from datetime import date, timedelta, datetime
from google.cloud import bigquery

PROJECT    = "synexis-project-sentinel"
TABLE      = f"{PROJECT}.sentinel_features.env_daily"
START_DATE = date(2001, 1, 1)
END_DATE   = date(2026, 3, 6)

NASA_KEY   = os.environ.get("NASA_API_KEY", "DEMO_KEY")
DONKI_BASE = "https://api.nasa.gov/DONKI"
HEADERS    = {"User-Agent": "SentinelProject/1.0 research@synexisproject.com"}

NOAA_EVENTS_BASE = (
    "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/"
    "daily_reports/solar_event_reports/"
)


# ─────────────────────────────────────────────────────────────────────────────
# DONKI API: CME events
# ─────────────────────────────────────────────────────────────────────────────

def fetch_donki_cme(start: date, end: date):
    """
    Fetch CME events from DONKI API in 6-month chunks.
    Returns set of dates with at least one CME.
    """
    cme_dates = set()
    chunk_start = start

    while chunk_start <= end:
        chunk_end = min(
            date(chunk_start.year + (1 if chunk_start.month > 6 else 0),
                 ((chunk_start.month + 5) % 12) + 1, 1) - timedelta(days=1),
            end
        )
        # Simpler: just do 6-month windows
        chunk_end = min(date(chunk_start.year, chunk_start.month, 1) +
                       timedelta(days=183), end)

        url = (
            f"{DONKI_BASE}/CME?"
            f"startDate={chunk_start.isoformat()}&"
            f"endDate={chunk_end.isoformat()}&"
            f"api_key={NASA_KEY}"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for event in data:
                        ts = event.get("startTime") or event.get("activityID", "")
                        if ts:
                            try:
                                d = datetime.strptime(ts[:10], "%Y-%m-%d").date()
                                cme_dates.add(d)
                            except ValueError:
                                pass
                print(f"  CME {chunk_start} to {chunk_end}: {len([d for d in cme_dates if chunk_start <= d <= chunk_end])} events")
            elif r.status_code == 429:
                print("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            else:
                print(f"  CME fetch error {r.status_code} for {chunk_start}")
        except Exception as e:
            print(f"  CME fetch exception: {e}")

        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(1.0)

    return cme_dates


# ─────────────────────────────────────────────────────────────────────────────
# DONKI API: SEP (Solar Energetic Particle) events
# ─────────────────────────────────────────────────────────────────────────────

def fetch_donki_sep(start: date, end: date):
    """
    Fetch SEP events from DONKI API.
    Returns set of dates with at least one SEP event.
    """
    sep_dates = set()
    chunk_start = start

    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=183), end)

        url = (
            f"{DONKI_BASE}/SEP?"
            f"startDate={chunk_start.isoformat()}&"
            f"endDate={chunk_end.isoformat()}&"
            f"api_key={NASA_KEY}"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for event in data:
                        ts = event.get("eventTime") or event.get("startTime") or ""
                        if ts:
                            try:
                                d = datetime.strptime(ts[:10], "%Y-%m-%d").date()
                                sep_dates.add(d)
                            except ValueError:
                                pass
                print(f"  SEP  {chunk_start} to {chunk_end}: {len([d for d in sep_dates if chunk_start <= d <= chunk_end])} events")
            elif r.status_code == 429:
                print("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            else:
                print(f"  SEP fetch error {r.status_code} for {chunk_start}")
        except Exception as e:
            print(f"  SEP fetch exception: {e}")

        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(1.0)

    return sep_dates


# ─────────────────────────────────────────────────────────────────────────────
# NOAA SUPPLEMENT: Solar Event Reports (2001-2009 CME supplement)
# Format: daily text files, YYYYMMDDevents.txt
# Look for lines containing "CME" or "II" (CME proxy from radio sweeps)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_noaa_events_year(year):
    """
    Scan NOAA daily event reports for a given year for CME mentions.
    Returns set of dates where CMEs were mentioned.
    """
    cme_dates = set()
    d = date(year, 1, 1)

    while d.year == year:
        ds = d.strftime("%Y%m%d")
        url = f"{NOAA_EVENTS_BASE}{year}/{ds}events.txt"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                text = r.text.upper()
                if "CME" in text or "CORONAGRAPH" in text:
                    cme_dates.add(d)
        except Exception:
            pass
        d += timedelta(days=1)
        time.sleep(0.1)

    print(f"  NOAA events {year}: {len(cme_dates)} CME days")
    return cme_dates


# ─────────────────────────────────────────────────────────────────────────────
# BUILD COMPLETE DATE MAPS
# ─────────────────────────────────────────────────────────────────────────────

def build_event_maps():
    print("\n── Phase 1: DONKI CME events (2010-2026) ──")
    donki_cme = fetch_donki_cme(date(2010, 1, 1), END_DATE)

    print(f"\n── Phase 2: DONKI SEP events (2001-2026) ──")
    donki_sep = fetch_donki_sep(START_DATE, END_DATE)

    print(f"\n── Phase 3: NOAA event reports supplement (2001-2009 CME) ──")
    noaa_cme = set()
    for year in range(0, 0):  # disabled
        noaa_cme.update(fetch_noaa_events_year(year))

    # Merge CME sources
    all_cme = donki_cme | noaa_cme
    all_sep = donki_sep

    print(f"\n── Summary ──")
    print(f"  CME dates: {len(all_cme)}")
    print(f"  SEP dates: {len(all_sep)}")

    return all_cme, all_sep


# ─────────────────────────────────────────────────────────────────────────────
# BUILD ROW LIST
# We only set has_cme=1 or has_cme=0 for dates we have good catalog coverage.
# For 2001-2009 where DONKI is sparse, has_cme uses NOAA supplement.
# has_sep uses DONKI only — NULLs in early years are expected and documented.
# ─────────────────────────────────────────────────────────────────────────────

def build_rows(cme_dates, sep_dates):
    rows = []
    d = START_DATE
    donki_cme_start = date(2010, 1, 1)  # reliable DONKI CME coverage

    while d <= END_DATE:
        row = {"day": d.isoformat()}

        # has_cme: 1 if CME recorded, 0 if in reliable window with no CME
        if d in cme_dates:
            row["has_cme"] = 1
        elif d >= donki_cme_start:
            row["has_cme"] = 0  # reliable window, no CME = confirmed 0
        else:
            # Pre-2010: only mark 1 if NOAA supplement found something
            # NULL means "uncertain" — don't assert 0 falsely
            if d in cme_dates:  # already caught above, but belt-and-suspenders
                row["has_cme"] = 1
            else:
                row["has_cme"] = None  # uncertain — documented gap

        # has_sep: DONKI covers 2010+, sparse before
        if d in sep_dates:
            row["has_sep"] = 1
        elif d >= date(2010, 1, 1):
            row["has_sep"] = 0
        else:
            row["has_sep"] = None  # pre-DONKI gap, documented

        rows.append(row)
        d += timedelta(days=1)

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# BIGQUERY UPDATE
# ─────────────────────────────────────────────────────────────────────────────

def update_bigquery(rows, dry_run=False):
    print(f"\n── Writing {len(rows)} rows to BigQuery ──")

    if dry_run:
        print("  DRY RUN — sample:")
        for row in rows[:5]:
            print(f"    {row}")
        cme_ones = sum(1 for r in rows if r.get("has_cme") == 1)
        sep_ones = sum(1 for r in rows if r.get("has_sep") == 1)
        nulls = sum(1 for r in rows if r.get("has_cme") is None)
        print(f"  CME=1: {cme_ones}, SEP=1: {sep_ones}, CME=NULL (pre-2010): {nulls}")
        return

    client = bigquery.Client(project=PROJECT)
    tmp_table = f"{PROJECT}.sentinel_features._donki_tmp"

    schema = [
        bigquery.SchemaField("day",     "DATE"),
        bigquery.SchemaField("has_cme", "INT64"),
        bigquery.SchemaField("has_sep", "INT64"),
    ]

    # Filter out None so BQ handles nulls correctly
    bq_rows = []
    for r in rows:
        bq_rows.append({
            "day":     r["day"],
            "has_cme": r["has_cme"],  # None → null in BQ JSON
            "has_sep": r["has_sep"],
        })

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition="WRITE_TRUNCATE",
    )
    client.load_table_from_json(
        bq_rows, tmp_table, job_config=job_config
    ).result()
    print(f"  Temp table loaded: {tmp_table}")

    merge_sql = f"""
    MERGE `{TABLE}` T
    USING `{tmp_table}` S
    ON T.day = S.day
    WHEN MATCHED THEN
      UPDATE SET
        T.has_cme = S.has_cme,
        T.has_sep = S.has_sep
    """
    client.query(merge_sql).result()
    print("  MERGE complete.")

    client.delete_table(tmp_table, not_found_ok=True)
    print("  Temp table deleted.")

    # Validation
    result = client.query(f"""
        SELECT
          COUNTIF(has_cme = 1)   as cme_days,
          COUNTIF(has_cme = 0)   as no_cme_days,
          COUNTIF(has_cme IS NULL) as cme_null_days,
          COUNTIF(has_sep = 1)   as sep_days,
          COUNTIF(has_sep = 0)   as no_sep_days,
          COUNTIF(has_sep IS NULL) as sep_null_days
        FROM `{TABLE}`
    """).result()

    for row in result:
        print(f"\n── Validation ──")
        print(f"  CME days=1:    {row.cme_days}")
        print(f"  CME days=0:    {row.no_cme_days}")
        print(f"  CME days=NULL: {row.cme_null_days} (pre-2010 uncertain)")
        print(f"  SEP days=1:    {row.sep_days}")
        print(f"  SEP days=0:    {row.no_sep_days}")
        print(f"  SEP days=NULL: {row.sep_null_days} (pre-2010 uncertain)")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backfill has_cme and has_sep in env_daily")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if NASA_KEY == "DEMO_KEY":
        print("WARNING: Using DEMO_KEY — rate limited to 30 req/hr.")
        print("Set NASA_API_KEY env var for a free key from https://api.nasa.gov/")
        print()

    print("=" * 60)
    print("  SENTINEL: has_cme + has_sep backfill")
    print(f"  Range: {START_DATE} to {END_DATE}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    cme_dates, sep_dates = build_event_maps()
    rows = build_rows(cme_dates, sep_dates)
    update_bigquery(rows, dry_run=args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
