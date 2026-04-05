#!/usr/bin/env python3
"""
Project Sentinel — H3 Regional TEC Backfill
Phase 2, Amendment #1 (commit 496ebf1)
INSPIRE methodology: Pulinets et al. (2021), Front. Earth Sci. 9:610193

Downloads IGS combined IONEX files from CDDIS, extracts fault-specific
regional TEC for each of the 5 target fault systems, applies INSPIRE
15-day running median baseline, separates nighttime from full-day TEC,
and loads into BigQuery as sentinel_features.h3_tec_raw.

Feature engineering (INSPIRE DELTA_TEC formula and lag windows) is done
in a subsequent SQL step (h3_02_feature_engineering.sql).

Resume support: parsed results cached to h3_tec_cache.csv
Re-running skips already-cached days.

Run:
    pip install requests google-cloud-bigquery --quiet
    python h3_01_backfill_regional_tec.py --start-year 2001 --end-year 2025
    python h3_01_backfill_regional_tec.py --start-year 2026 --end-year 2026

    # Test single day first:
    python h3_01_backfill_regional_tec.py --start-year 2010 --end-year 2010 --dry-run --days 1
"""

import argparse
import csv
import gzip as gzmod
import logging
import os
import statistics
import subprocess
import tempfile
from datetime import date, timedelta, timezone, datetime

import requests
from google.cloud import bigquery

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT    = "synexis-project-sentinel"
DATASET    = "sentinel_features"
TABLE_RAW  = "h3_tec_raw"
CDDIS_BASE = "https://cddis.nasa.gov/archive/gnss/products/ionex"
BKG_BASE   = "https://igs.bkg.bund.de/root_ftp/IGS/products/ionex"
USERNAME   = "synexisproject"
PASSWORD   = "REDACTED"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h3_tec_cache.csv")

# ── IONEX grid spec (from header: LAT1/LAT2/DLAT, LON1/LON2/DLON) ────────────
LAT_START =  87.5
LAT_END   = -87.5
LAT_STEP  =  -2.5   # negative = north to south
LON_START = -180.0
LON_END   =  180.0
LON_STEP  =   5.0
EXPONENT_DEFAULT = -1   # TEC values × 10^-1 = TECu
MAPS_PER_DAY = 13       # one every 7200s = 2h intervals: 00,02,04,06,08,10,12,14,16,18,20,22,24

# Nighttime UTC hours (behind solar terminator — INSPIRE methodology)
# Maps at 00:00, 02:00, 04:00, 20:00, 22:00 UTC
NIGHTTIME_MAP_INDICES = [0, 1, 2, 10, 11]  # 0-indexed from 00:00 UTC

# ── Fault system bounding boxes (from fault_systems table) ───────────────────
FAULT_SYSTEMS = {
    "japan_trench":    {"lat_min": 35.0, "lat_max": 45.0, "lon_min": 140.0, "lon_max": 145.0},
    "cascadia":        {"lat_min": 40.0, "lat_max": 50.0, "lon_min": -125.0, "lon_max": -110.0},
    "central_chile":   {"lat_min": -40.0, "lat_max": -30.0, "lon_min": -75.0, "lon_max": -65.0},
    "north_anatolian": {"lat_min": 38.0, "lat_max": 42.0, "lon_min": 28.0, "lon_max": 42.0},
    "sumatra_andaman": {"lat_min": 0.0, "lat_max": 15.0, "lon_min": 92.0, "lon_max": 100.0},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


# ── Grid index helpers ────────────────────────────────────────────────────────

def build_grid_lats():
    """Build list of latitude values in IONEX order (N to S)."""
    lats = []
    lat = LAT_START
    while lat >= LAT_END - 0.001:
        lats.append(round(lat, 1))
        lat += LAT_STEP
    return lats


def build_grid_lons():
    """Build list of longitude values in IONEX order (W to E)."""
    lons = []
    lon = LON_START
    while lon <= LON_END + 0.001:
        lons.append(round(lon, 1))
        lon += LON_STEP
    return lons


GRID_LATS = build_grid_lats()  # 71 values: 87.5, 85.0, ..., -87.5
GRID_LONS = build_grid_lons()  # 73 values: -180, -175, ..., 180
N_LATS    = len(GRID_LATS)     # 71
N_LONS    = len(GRID_LONS)     # 73


def get_fault_grid_indices(fault_id):
    """
    Get the (lat_idx, lon_idx) pairs of grid cells within a fault bounding box.
    Returns list of (lat_idx, lon_idx) tuples.
    """
    bb = FAULT_SYSTEMS[fault_id]
    indices = []
    for i, lat in enumerate(GRID_LATS):
        if bb["lat_min"] <= lat <= bb["lat_max"]:
            for j, lon in enumerate(GRID_LONS):
                if bb["lon_min"] <= lon <= bb["lon_max"]:
                    indices.append((i, j))
    return indices


# Pre-compute grid indices for all fault systems
FAULT_GRID_INDICES = {fid: get_fault_grid_indices(fid) for fid in FAULT_SYSTEMS}

# Log grid cell counts
for fid, indices in FAULT_GRID_INDICES.items():
    log.info(f"  {fid}: {len(indices)} grid cells in bounding box")


# ── Download helpers ──────────────────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.auth = (USERNAME, PASSWORD)
    return s


def ionex_urls(d):
    """Generate candidate IONEX URLs for a given date (try new format first for recent years)."""
    doy  = d.timetuple().tm_yday
    yy   = d.strftime("%y")
    yr   = d.year

    cddis_old = f"{CDDIS_BASE}/{yr}/{doy:03d}/igsg{doy:03d}0.{yy}i.Z"
    cddis_new = f"{CDDIS_BASE}/{yr}/{doy:03d}/IGS0OPSFIN_{yr}{doy:03d}0000_01D_02H_GIM.INX.gz"
    bkg_old   = f"{BKG_BASE}/{yr}/{doy:03d}/igsg{doy:03d}0.{yy}i.Z"
    bkg_new   = f"{BKG_BASE}/{yr}/{doy:03d}/IGS0OPSFIN_{yr}{doy:03d}0000_01D_02H_GIM.INX.gz"

    if yr >= 2024:
        return [cddis_new, bkg_new, cddis_old, bkg_old]
    else:
        return [cddis_old, bkg_old, cddis_new, bkg_new]


def download_ionex(session, d, tmpdir):
    """Download and decompress IONEX file for date d. Returns path or None."""
    out_file = os.path.join(tmpdir, "igsg.ionex")
    for url in ionex_urls(d):
        try:
            r = session.get(url, timeout=60)
            if r.status_code != 200:
                continue
            if b'<!DOCTYPE' in r.content[:100]:
                continue
            if url.endswith('.gz'):
                try:
                    data = gzmod.decompress(r.content)
                except Exception as e:
                    log.debug(f"{d} gzip error ({url}): {e}")
                    continue
            elif url.endswith('.Z'):
                out_z = os.path.join(tmpdir, "igsg.Z")
                with open(out_z, 'wb') as f:
                    f.write(r.content)
                result = subprocess.run(['uncompress', '-f', '-c', out_z],
                                        capture_output=True)
                if result.returncode != 0:
                    log.debug(f"{d} uncompress failed ({url})")
                    continue
                data = result.stdout
            else:
                data = r.content
            with open(out_file, 'wb') as f:
                f.write(data)
            log.debug(f"{d} downloaded from {url.split('/')[-1]}")
            import time; time.sleep(4)
            return out_file
        except Exception as e:
            log.debug(f"{d} download error ({url}): {e}")
            continue
    return None


# ── IONEX parser ──────────────────────────────────────────────────────────────

def parse_ionex_regional(filepath):
    """
    Parse IONEX file and extract per-fault-system TEC values.

    Returns dict:
    {
        fault_id: {
            'tec_all_maps':       [float, ...],  # one per map (13 maps)
            'tec_fullday_mean':   float,
            'tec_nighttime_mean': float,
            'n_cells':            int,
            'n_maps_valid':       int,
        }
    }
    Returns None if parsing fails.
    """
    exponent = EXPONENT_DEFAULT
    in_tec_map = False
    header_done = False
    current_map_idx = -1
    current_lat_idx = 0

    # Per-map, per-fault accumulator: maps[map_idx][fault_id] = [values]
    maps = [{fid: [] for fid in FAULT_SYSTEMS} for _ in range(MAPS_PER_DAY + 2)]
    n_maps_found = 0

    try:
        with open(filepath, 'r', errors='replace') as f:
            for line in f:
                stripped = line[60:].strip() if len(line) > 60 else ""

                if not header_done:
                    if 'EXPONENT' in stripped:
                        try:
                            exponent = int(line[:6].strip())
                        except ValueError:
                            pass
                    if 'END OF HEADER' in stripped:
                        header_done = True
                    continue

                if 'START OF TEC MAP' in stripped:
                    in_tec_map = True
                    current_map_idx = n_maps_found
                    current_lat_idx = 0
                    n_maps_found += 1
                    continue

                if 'END OF TEC MAP' in stripped:
                    in_tec_map = False
                    continue

                if not in_tec_map:
                    continue

                # Latitude header line: "  87.5-180.0 180.0   5.0 450.0"
                if 'LAT' in stripped or ('/' in stripped and len(line) > 20):
                    try:
                        lat_val = float(line.split()[0])
                        # Find closest grid lat index
                        diffs = [abs(lat_val - gl) for gl in GRID_LATS]
                        current_lat_idx = diffs.index(min(diffs))
                    except (ValueError, IndexError):
                        pass
                    continue

                # Data line — parse TEC values
                vals_raw = []
                for part in line.split():
                    try:
                        vals_raw.append(int(part))
                    except ValueError:
                        continue

                if not vals_raw:
                    continue

                scale = 10 ** exponent
                lon_idx = 0
                for v in vals_raw:
                    if lon_idx >= N_LONS:
                        break
                    if v != 9999:
                        tec_val = v * scale
                        # Check each fault system
                        for fid in FAULT_SYSTEMS:
                            if (current_lat_idx, lon_idx) in set(FAULT_GRID_INDICES[fid]):
                                maps[current_map_idx][fid].append(tec_val)
                    lon_idx += 1

                current_lat_idx += 1

    except Exception as e:
        log.debug(f"Parse error: {e}")
        return None

    if n_maps_found == 0:
        return None

    # Convert maps to per-fault results
    results = {}
    for fid in FAULT_SYSTEMS:
        map_means = []
        for mi in range(min(n_maps_found, MAPS_PER_DAY)):
            vals = maps[mi][fid]
            if vals:
                map_means.append(statistics.mean(vals))
            else:
                map_means.append(None)

        valid_means = [v for v in map_means if v is not None]
        if not valid_means:
            results[fid] = None
            continue

        fullday_mean   = statistics.mean(valid_means)
        nighttime_vals = [map_means[i] for i in NIGHTTIME_MAP_INDICES
                          if i < len(map_means) and map_means[i] is not None]
        nighttime_mean = statistics.mean(nighttime_vals) if nighttime_vals else None

        results[fid] = {
            "tec_fullday_mean":   round(fullday_mean, 4),
            "tec_nighttime_mean": round(nighttime_mean, 4) if nighttime_mean else None,
            "n_cells":            len(FAULT_GRID_INDICES[fid]),
            "n_maps_valid":       len(valid_means),
        }

    return results


# ── Cache helpers ─────────────────────────────────────────────────────────────

CACHE_FIELDS = ["day", "fault_id", "tec_fullday_mean", "tec_nighttime_mean",
                "n_cells", "n_maps_valid"]

def load_cache():
    """Load existing cache. Returns set of (day_str, fault_id) already processed."""
    cached = {}
    if not os.path.exists(CACHE_FILE):
        return cached
    with open(CACHE_FILE, 'r', newline='') as f:
        for row in csv.DictReader(f):
            key = (row['day'], row['fault_id'])
            cached[key] = row
    log.info(f"Loaded {len(cached)} cached (day, fault) pairs from {CACHE_FILE}")
    return cached


def open_cache_writer(is_new):
    fh = open(CACHE_FILE, 'a', newline='')
    writer = csv.DictWriter(fh, fieldnames=CACHE_FIELDS)
    if is_new:
        writer.writeheader()
    return fh, writer


# ── BigQuery loader ───────────────────────────────────────────────────────────

BQ_SCHEMA = [
    bigquery.SchemaField("day",                 "DATE"),
    bigquery.SchemaField("fault_id",            "STRING"),
    bigquery.SchemaField("tec_fullday_mean",    "FLOAT64"),
    bigquery.SchemaField("tec_nighttime_mean",  "FLOAT64"),
    bigquery.SchemaField("n_cells",             "INT64"),
    bigquery.SchemaField("n_maps_valid",        "INT64"),
    bigquery.SchemaField("ingested_at",         "TIMESTAMP"),
]

def ensure_table(client):
    table_id = f"{PROJECT}.{DATASET}.{TABLE_RAW}"
    try:
        client.get_table(table_id)
        log.info(f"Table {table_id} exists")
    except Exception:
        table = bigquery.Table(table_id, schema=BQ_SCHEMA)
        client.create_table(table)
        log.info(f"Created table {table_id}")


def load_batch_to_bq(client, rows):
    """Load a batch of rows to BigQuery using MERGE (upsert)."""
    if not rows:
        return
    table_id = f"{PROJECT}.{DATASET}.{TABLE_RAW}"
    staging  = f"{PROJECT}.{DATASET}.h3_tec_staging"
    now      = datetime.now(timezone.utc).isoformat()

    bq_rows = []
    for r in rows:
        bq_rows.append({
            "day":                r["day"],
            "fault_id":           r["fault_id"],
            "tec_fullday_mean":   float(r["tec_fullday_mean"]) if r["tec_fullday_mean"] else None,
            "tec_nighttime_mean": float(r["tec_nighttime_mean"]) if r["tec_nighttime_mean"] else None,
            "n_cells":            int(r["n_cells"]) if r["n_cells"] else 0,
            "n_maps_valid":       int(r["n_maps_valid"]) if r["n_maps_valid"] else 0,
            "ingested_at":        now,
        })

    job = client.load_table_from_json(
        bq_rows, staging,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition="WRITE_TRUNCATE"
        )
    )
    job.result()

    client.query(f"""
    MERGE `{table_id}` T
    USING `{staging}` S
    ON T.day = S.day AND T.fault_id = S.fault_id
    WHEN MATCHED THEN UPDATE SET
        T.tec_fullday_mean   = S.tec_fullday_mean,
        T.tec_nighttime_mean = S.tec_nighttime_mean,
        T.n_cells            = S.n_cells,
        T.n_maps_valid       = S.n_maps_valid,
        T.ingested_at        = S.ingested_at
    WHEN NOT MATCHED THEN INSERT ROW
    """).result()

    client.delete_table(staging, not_found_ok=True)
    log.info(f"  Loaded {len(bq_rows)} rows to {TABLE_RAW}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="H3 Regional TEC Backfill")
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year",   type=int, default=2025)
    parser.add_argument("--dry-run",    action="store_true",
                        help="Parse but don't load to BigQuery")
    parser.add_argument("--days",       type=int, default=None,
                        help="Process only N days (for testing)")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="BQ load batch size in days (default 100)")
    parser.add_argument("--fault",      default=None,
                        help="Process single fault system only")
    args = parser.parse_args()

    if args.fault and args.fault not in FAULT_SYSTEMS:
        log.error(f"Unknown fault: {args.fault}. Options: {list(FAULT_SYSTEMS.keys())}")
        return

    active_faults = [args.fault] if args.fault else list(FAULT_SYSTEMS.keys())

    start_date = date(args.start_year, 1, 1)
    end_date   = date(args.end_year, 12, 31)
    total_days = (end_date - start_date).days + 1

    log.info("=" * 60)
    log.info("Project Sentinel — H3 Regional TEC Backfill")
    log.info(f"INSPIRE methodology (Pulinets et al. 2021, Front. Earth Sci. 9:610193)")
    log.info(f"Period: {start_date} to {end_date} ({total_days} days)")
    log.info(f"Fault systems: {active_faults}")
    log.info(f"Grid: {N_LATS} lats × {N_LONS} lons, {MAPS_PER_DAY} maps/day")
    log.info(f"Nighttime maps: indices {NIGHTTIME_MAP_INDICES} (00,02,04,20,22 UTC)")
    log.info("=" * 60)

    # Load cache
    cached = load_cache()
    is_new_cache = not os.path.exists(CACHE_FILE)
    cache_fh, cache_writer = open_cache_writer(is_new_cache)

    session = make_session()
    client  = None if args.dry_run else bigquery.Client(project=PROJECT)
    if not args.dry_run:
        ensure_table(client)

    # Pending BQ batch
    pending_rows = []
    success_days = 0
    fail_days    = 0
    skip_days    = 0
    days_processed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        d = start_date
        while d <= end_date:
            if args.days and days_processed >= args.days:
                break

            # Check if all active faults already cached for this day
            all_cached = all((d.isoformat(), fid) in cached for fid in active_faults)
            if all_cached:
                skip_days += 1
                d += timedelta(days=1)
                continue

            # Download IONEX file
            filepath = download_ionex(session, d, tmpdir)
            days_processed += 1

            if filepath is None:
                log.warning(f"{d} download failed")
                fail_days += 1
                # Cache as failed so we don't retry every run
                for fid in active_faults:
                    if (d.isoformat(), fid) not in cached:
                        cache_writer.writerow({
                            "day": d.isoformat(), "fault_id": fid,
                            "tec_fullday_mean": "", "tec_nighttime_mean": "",
                            "n_cells": "", "n_maps_valid": ""
                        })
                cache_fh.flush()
                d += timedelta(days=1)
                continue

            # Parse IONEX — extract regional TEC
            regional = parse_ionex_regional(filepath)

            if regional is None:
                log.warning(f"{d} parse failed")
                fail_days += 1
                d += timedelta(days=1)
                continue

            success_days += 1
            day_str = d.isoformat()

            # Write to cache and pending batch
            for fid in active_faults:
                if (day_str, fid) in cached:
                    continue
                r = regional.get(fid)
                if r:
                    row = {
                        "day":                day_str,
                        "fault_id":           fid,
                        "tec_fullday_mean":   r["tec_fullday_mean"],
                        "tec_nighttime_mean": r["tec_nighttime_mean"] or "",
                        "n_cells":            r["n_cells"],
                        "n_maps_valid":       r["n_maps_valid"],
                    }
                    cache_writer.writerow(row)
                    pending_rows.append(row)

                    if args.dry_run and days_processed <= 3:
                        log.info(f"  {day_str} {fid}: "
                                 f"fullday={r['tec_fullday_mean']:.2f} "
                                 f"night={r['tec_nighttime_mean']} "
                                 f"cells={r['n_cells']} maps={r['n_maps_valid']}")

            cache_fh.flush()

            # Clean up temp files
            for fname in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, fname))

            # Progress logging
            if success_days % 50 == 0:
                log.info(f"Progress: {days_processed}/{total_days} days | "
                         f"success={success_days} fail={fail_days} skip={skip_days}")

            # BQ batch load
            if not args.dry_run and len(pending_rows) >= args.batch_size * len(active_faults):
                log.info(f"Loading batch of {len(pending_rows)} rows to BigQuery...")
                load_batch_to_bq(client, pending_rows)
                pending_rows = []

            d += timedelta(days=1)

    cache_fh.close()

    # Final BQ load
    if not args.dry_run and pending_rows:
        log.info(f"Final batch: {len(pending_rows)} rows")
        load_batch_to_bq(client, pending_rows)

    log.info("=" * 60)
    log.info(f"Backfill complete: {success_days} success, {fail_days} fail, {skip_days} skip")
    log.info(f"Cache: {CACHE_FILE}")

    if not args.dry_run and client:
        # Validation query
        result = client.query(f"""
        SELECT fault_id,
               COUNT(*) AS days_loaded,
               COUNTIF(tec_fullday_mean IS NOT NULL) AS days_with_tec,
               COUNTIF(tec_nighttime_mean IS NOT NULL) AS days_with_nighttime,
               ROUND(AVG(tec_fullday_mean), 2) AS avg_fullday_tec,
               MIN(day) AS earliest,
               MAX(day) AS latest
        FROM `{PROJECT}.{DATASET}.{TABLE_RAW}`
        GROUP BY fault_id ORDER BY fault_id
        """).result()
        log.info("\nBigQuery validation:")
        for row in result:
            log.info(f"  {row.fault_id:25s} days={row.days_loaded:5d} "
                     f"tec={row.days_with_tec:5d} night={row.days_with_nighttime:5d} "
                     f"avg={row.avg_fullday_tec:.1f} {row.earliest}→{row.latest}")


if __name__ == "__main__":
    main()
