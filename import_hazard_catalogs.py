#!/usr/bin/env python3
"""
import_hazard_catalogs.py

Imports tsunami and volcanic event catalogs into
sentinel_groundtruth.events table.

Sources:
  Tsunami: NOAA/NCEI Global Historical Tsunami Database (already downloaded)
  Volcanic: Smithsonian GVP via alternative API endpoint

Usage:
  python3 import_hazard_catalogs.py --source tsunami
  python3 import_hazard_catalogs.py --source volcanic
  python3 import_hazard_catalogs.py --source all
  python3 import_hazard_catalogs.py --source all --dry-run
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT_ID   = "synexis-project-sentinel"
EVENTS_TABLE = f"{PROJECT_ID}.sentinel_groundtruth.events"

bq = bigquery.Client(project=PROJECT_ID)


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


# ── Tsunami ───────────────────────────────────────────────────────────────────

def load_tsunami_from_file(filepath):
    """Parse NOAA NCEI tsunami JSON file."""
    with open(filepath) as f:
        data = json.load(f)

    items = data.get('items', [])
    log(f"Loaded {len(items)} tsunami events from file")

    rows = []
    for item in items:
        year  = item.get('year')
        month = item.get('month', 1) or 1
        day   = item.get('day', 1) or 1

        if not year:
            continue

        try:
            hour   = item.get('hour', 0) or 0
            minute = item.get('minute', 0) or 0
            second = int(item.get('second', 0) or 0)
            ts = datetime(int(year), int(month), int(day),
                         int(hour), int(minute), int(second),
                         tzinfo=timezone.utc)
        except (ValueError, TypeError):
            try:
                ts = datetime(int(year), int(month), int(day),
                             tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

        lat = item.get('latitude')
        lon = item.get('longitude')
        mag = item.get('eqMagnitude')

        country  = item.get('country', '')
        location = item.get('locationName', '')
        region   = f"{country} - {location}".strip(' -')

        rows.append({
            'event_id': f"NOAA_TSUNAMI_{item['id']}",
            'hazard':   'tsunami',
            'start_ts': ts.isoformat(),
            'end_ts':   None,
            'mag':      float(mag) if mag is not None else None,
            'lat':      float(lat) if lat is not None else None,
            'lon':      float(lon) if lon is not None else None,
            'region':   region,
            'source':   'NOAA_NCEI_Tsunami_Database',
            'notes':    f"max_water_height_m={item.get('maxWaterHeight', '')} "
                        f"deaths={item.get('deathsTotal', '')} "
                        f"validity={item.get('eventValidity', '')}",
        })

    log(f"Parsed {len(rows)} valid tsunami events")
    return rows


def fetch_tsunami_all_pages():
    """Fetch all pages from NOAA tsunami API."""
    all_items = []
    page = 1
    while True:
        url = (f"https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/"
               f"tsunamis/events?minYear=2000&maxYear=2026"
               f"&itemsPerPage=200&page={page}")
        log(f"  Fetching page {page}...")
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read())
            items = data.get('items', [])
            if not items:
                break
            all_items.extend(items)
            total_pages = data.get('totalPages', 1)
            log(f"  Page {page}/{total_pages}: {len(items)} items")
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            log(f"  Error on page {page}: {e}")
            break

    return all_items


# ── Volcanic ──────────────────────────────────────────────────────────────────

def fetch_volcanic_events():
    """
    Fetch volcanic eruption data from Smithsonian GVP.
    Uses the GVP API which doesn't require browser/JS.
    Falls back to a compiled list if API is unavailable.
    """
    log("Fetching volcanic events from GVP API...")

    # Try GVP's JSON API endpoint
    try:
        url = ("https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/"
               "volcanoes/events?minYear=2000&maxYear=2026&itemsPerPage=500")
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
        items = data.get('items', [])
        if items:
            log(f"  Got {len(items)} volcanic events from NGDC API")
            return parse_ngdc_volcanic(items)
    except Exception as e:
        log(f"  NGDC volcanic API unavailable: {e}")

    # Try alternative: USGS Volcano Hazards Program
    try:
        url = ("https://volcanoes.usgs.gov/vsc/api/volcanoApi/"
               "eruptions?startDate=2000-01-01&endDate=2026-12-31")
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
        if data:
            log(f"  Got {len(data)} volcanic events from USGS VHP API")
            return parse_usgs_volcanic(data)
    except Exception as e:
        log(f"  USGS VHP API unavailable: {e}")

    log("  Both volcanic APIs unavailable — returning empty list")
    log("  Manual download required from: https://volcano.si.edu/volcanolist_eruptions.cfm")
    return []


def parse_ngdc_volcanic(items):
    rows = []
    for item in items:
        year  = item.get('year')
        month = item.get('month', 1) or 1
        day   = item.get('day', 1) or 1
        if not year:
            continue
        try:
            ts = datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        rows.append({
            'event_id': f"NGDC_VOLCANO_{item.get('id', '')}",
            'hazard':   'volcanic',
            'start_ts': ts.isoformat(),
            'end_ts':   None,
            'mag':      float(item['vei']) if item.get('vei') else None,
            'lat':      float(item['latitude']) if item.get('latitude') else None,
            'lon':      float(item['longitude']) if item.get('longitude') else None,
            'region':   item.get('locationName', ''),
            'source':   'NGDC_Volcanic_Database',
            'notes':    f"volcano={item.get('volcanoName','')} "
                        f"vei={item.get('vei','')}",
        })
    return rows


def parse_usgs_volcanic(items):
    rows = []
    for item in items:
        start = item.get('StartDate') or item.get('start_date', '')
        if not start:
            continue
        try:
            ts = datetime.fromisoformat(start.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            try:
                ts = datetime.strptime(start[:10], '%Y-%m-%d').replace(
                    tzinfo=timezone.utc)
            except ValueError:
                continue

        rows.append({
            'event_id': f"USGS_VOLCANO_{item.get('VolcanoNumber','')}_{start[:10]}",
            'hazard':   'volcanic',
            'start_ts': ts.isoformat(),
            'end_ts':   None,
            'mag':      float(item['VEI']) if item.get('VEI') else None,
            'lat':      float(item['Latitude']) if item.get('Latitude') else None,
            'lon':      float(item['Longitude']) if item.get('Longitude') else None,
            'region':   item.get('VolcanoName', ''),
            'source':   'USGS_VHP',
            'notes':    f"volcano={item.get('VolcanoName','')} "
                        f"vei={item.get('VEI','')}",
        })
    return rows


# ── BigQuery writer ───────────────────────────────────────────────────────────

def deduplicate_against_existing(rows, hazard):
    """Remove rows already in the events table."""
    query = f"""
    SELECT event_id FROM `{EVENTS_TABLE}`
    WHERE hazard = '{hazard}'
    """
    existing_ids = set(
        r.event_id for r in bq.query(query).result()
    )
    before = len(rows)
    rows = [r for r in rows if r['event_id'] not in existing_ids]
    log(f"  Dedup: {before} → {len(rows)} rows "
        f"({before - len(rows)} already exist)")
    return rows


def write_to_bq(rows, dry_run=False):
    if not rows:
        log("  No rows to write")
        return

    if dry_run:
        log(f"  DRY RUN — would write {len(rows)} rows")
        for r in rows[:3]:
            log(f"    {r}")
        return

    # Write in batches of 500
    batch_size = 500
    total_written = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        errors = bq.insert_rows_json(EVENTS_TABLE, batch)
        if errors:
            log(f"  BQ errors in batch {i//batch_size + 1}: {errors[:2]}")
        else:
            total_written += len(batch)
            log(f"  Written batch {i//batch_size + 1}: "
                f"{total_written}/{len(rows)} rows")

    log(f"  Total written: {total_written} rows")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default='all',
                    choices=['tsunami', 'volcanic', 'all'])
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--tsunami-file', default='tsunami_events.tsv',
                    help='Path to downloaded NOAA tsunami JSON file')
    args = ap.parse_args()

    log(f"=== Hazard Catalog Import ===")
    log(f"Source: {args.source} | Dry run: {args.dry_run}")

    if args.source in ('tsunami', 'all'):
        log("\n--- TSUNAMI ---")
        tsunami_file = args.tsunami_file

        if os.path.exists(tsunami_file):
            log(f"Loading from local file: {tsunami_file}")
            # File may be JSON despite .tsv extension
            try:
                rows = load_tsunami_from_file(tsunami_file)
            except json.JSONDecodeError:
                log("  File is not JSON, fetching from API...")
                items = fetch_tsunami_all_pages()
                with open(tsunami_file, 'w') as f:
                    json.dump({'items': items}, f)
                rows = load_tsunami_from_file(tsunami_file)
        else:
            log("No local file found, fetching all pages from NOAA API...")
            items = fetch_tsunami_all_pages()
            with open(tsunami_file, 'w') as f:
                json.dump({'items': items}, f)
            rows = load_tsunami_from_file(tsunami_file)

        rows = deduplicate_against_existing(rows, 'tsunami')
        write_to_bq(rows, args.dry_run)

    if args.source in ('volcanic', 'all'):
        log("\n--- VOLCANIC ---")
        rows = fetch_volcanic_events()
        if rows:
            rows = deduplicate_against_existing(rows, 'volcanic')
            write_to_bq(rows, args.dry_run)
        else:
            log("  No volcanic events fetched — manual download may be needed")

    log("\n=== Import complete ===")

    # Summary
    if not args.dry_run:
        log("\nCurrent events table:")
        result = bq.query(f"""
        SELECT hazard, COUNT(*) AS cnt,
               MIN(DATE(start_ts)) AS earliest,
               MAX(DATE(start_ts)) AS latest
        FROM `{EVENTS_TABLE}`
        GROUP BY hazard ORDER BY cnt DESC
        """).result()
        for r in result:
            log(f"  {r.hazard}: {r.cnt} events "
                f"({r.earliest} to {r.latest})")


if __name__ == '__main__':
    main()
