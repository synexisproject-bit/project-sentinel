#!/usr/bin/env python3
"""
Project Sentinel — H3 Regional TEC: Parse from GCS → BigQuery
Reads IONEX files from GCS bucket, extracts fault-specific regional TEC,
applies INSPIRE methodology, loads to BigQuery.

Run on VM after ionex_to_gcs.py completes:
    pip3 install google-cloud-bigquery google-cloud-storage --break-system-packages
    nohup python3 h3_parse_from_gcs.py --start-year 2001 --end-year 2025 \
        > logs/h3_parse.log 2>&1 &
"""

import argparse
import json
import logging
import os
import statistics
import tempfile
from datetime import date, timedelta, datetime, timezone

from google.cloud import bigquery, storage

PROJECT   = "synexis-project-sentinel"
BUCKET    = "sentinel-ionex-cache"
DATASET   = "sentinel_features"
TABLE_RAW = "h3_tec_raw"

# IONEX grid spec
LAT_START, LAT_END, LAT_STEP = 87.5, -87.5, -2.5
LON_START, LON_END, LON_STEP = -180.0, 180.0, 5.0
MAPS_PER_DAY = 13
NIGHTTIME_MAP_INDICES = [0, 1, 2, 10, 11]
EXPONENT_DEFAULT = -1

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


def build_grid():
    lats, lons = [], []
    lat = LAT_START
    while lat >= LAT_END - 0.001:
        lats.append(round(lat, 1))
        lat += LAT_STEP
    lon = LON_START
    while lon <= LON_END + 0.001:
        lons.append(round(lon, 1))
        lon += LON_STEP
    return lats, lons


GRID_LATS, GRID_LONS = build_grid()
N_LATS, N_LONS = len(GRID_LATS), len(GRID_LONS)

FAULT_GRID_INDICES = {}
for fid, bb in FAULT_SYSTEMS.items():
    indices = set()
    for i, lat in enumerate(GRID_LATS):
        if bb["lat_min"] <= lat <= bb["lat_max"]:
            for j, lon in enumerate(GRID_LONS):
                if bb["lon_min"] <= lon <= bb["lon_max"]:
                    indices.add((i, j))
    FAULT_GRID_INDICES[fid] = indices
    log.info(f"  {fid}: {len(indices)} grid cells")


def gcs_path(d):
    doy = d.timetuple().tm_yday
    return f"{d.year}/{doy:03d}/igsg{doy:03d}0.ionex"


def parse_ionex_regional(filepath):
    exponent = EXPONENT_DEFAULT
    in_tec_map = False
    header_done = False
    current_map_idx = -1
    current_lat_idx = 0
    n_maps_found = 0
    maps = [{fid: [] for fid in FAULT_SYSTEMS} for _ in range(MAPS_PER_DAY + 2)]

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

                if 'LAT' in stripped or ('/' in stripped and len(line) > 20):
                    try:
                        lat_val = float(line.split()[0])
                        diffs = [abs(lat_val - gl) for gl in GRID_LATS]
                        current_lat_idx = diffs.index(min(diffs))
                    except (ValueError, IndexError):
                        pass
                    continue

                vals_raw = []
                for part in line.split():
                    try:
                        vals_raw.append(int(part))
                    except ValueError:
                        continue

                if not vals_raw:
                    continue

                scale = 10 ** exponent
                for lon_idx, v in enumerate(vals_raw):
                    if lon_idx >= N_LONS:
                        break
                    if v != 9999:
                        tec_val = v * scale
                        for fid in FAULT_SYSTEMS:
                            if (current_lat_idx, lon_idx) in FAULT_GRID_INDICES[fid]:
                                maps[current_map_idx][fid].append(tec_val)

                current_lat_idx += 1

    except Exception as e:
        log.debug(f"Parse error: {e}")
        return None

    if n_maps_found == 0:
        return None

    results = {}
    for fid in FAULT_SYSTEMS:
        map_means = []
        for mi in range(min(n_maps_found, MAPS_PER_DAY)):
            vals = maps[mi][fid]
            map_means.append(statistics.mean(vals) if vals else None)

        valid = [v for v in map_means if v is not None]
        if not valid:
            results[fid] = None
            continue

        nighttime_vals = [map_means[i] for i in NIGHTTIME_MAP_INDICES
                          if i < len(map_means) and map_means[i] is not None]

        results[fid] = {
            "tec_fullday_mean":   round(statistics.mean(valid), 4),
            "tec_nighttime_mean": round(statistics.mean(nighttime_vals), 4) if nighttime_vals else None,
            "n_cells":            len(FAULT_GRID_INDICES[fid]),
            "n_maps_valid":       len(valid),
        }
    return results


BQ_SCHEMA = [
    bigquery.SchemaField("day",                 "DATE"),
    bigquery.SchemaField("fault_id",            "STRING"),
    bigquery.SchemaField("tec_fullday_mean",    "FLOAT64"),
    bigquery.SchemaField("tec_nighttime_mean",  "FLOAT64"),
    bigquery.SchemaField("n_cells",             "INT64"),
    bigquery.SchemaField("n_maps_valid",        "INT64"),
    bigquery.SchemaField("ingested_at",         "TIMESTAMP"),
]


def get_already_loaded(bq_client):
    """Get set of (day_str, fault_id) already in BigQuery."""
    try:
        rows = bq_client.query(f"""
            SELECT CAST(day AS STRING) AS day_str, fault_id
            FROM `{PROJECT}.{DATASET}.{TABLE_RAW}`
        """).result()
        return {(row.day_str, row.fault_id) for row in rows}
    except Exception:
        return set()


def load_batch_to_bq(bq_client, rows):
    if not rows:
        return
    table_id = f"{PROJECT}.{DATASET}.{TABLE_RAW}"
    staging  = f"{PROJECT}.{DATASET}.h3_tec_staging"
    now = datetime.now(timezone.utc).isoformat()

    bq_rows = [{
        "day":                r["day"],
        "fault_id":           r["fault_id"],
        "tec_fullday_mean":   r["tec_fullday_mean"],
        "tec_nighttime_mean": r["tec_nighttime_mean"],
        "n_cells":            r["n_cells"],
        "n_maps_valid":       r["n_maps_valid"],
        "ingested_at":        now,
    } for r in rows]

    job = bq_client.load_table_from_json(
        bq_rows, staging,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition="WRITE_TRUNCATE"
        )
    )
    job.result()

    bq_client.query(f"""
    MERGE `{table_id}` T USING `{staging}` S
    ON T.day = S.day AND T.fault_id = S.fault_id
    WHEN MATCHED THEN UPDATE SET
        T.tec_fullday_mean=S.tec_fullday_mean,
        T.tec_nighttime_mean=S.tec_nighttime_mean,
        T.n_cells=S.n_cells, T.n_maps_valid=S.n_maps_valid,
        T.ingested_at=S.ingested_at
    WHEN NOT MATCHED THEN INSERT ROW
    """).result()
    bq_client.delete_table(staging, not_found_ok=True)
    log.info(f"  Loaded {len(bq_rows)} rows to BigQuery")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year",   type=int, default=2025)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    start = date(args.start_year, 1, 1)
    end   = date(args.end_year, 12, 31)
    total = (end - start).days + 1

    log.info(f"H3 Parse GCS → BigQuery: {start} to {end} ({total} days)")

    gcs_client = storage.Client(project=PROJECT)
    bq_client  = bigquery.Client(project=PROJECT)
    bucket     = gcs_client.bucket(BUCKET)

    # Ensure table exists
    table_id = f"{PROJECT}.{DATASET}.{TABLE_RAW}"
    try:
        bq_client.get_table(table_id)
    except Exception:
        bq_client.create_table(bigquery.Table(table_id, schema=BQ_SCHEMA))
        log.info(f"Created table {table_id}")

    log.info("Loading already-processed days from BigQuery...")
    already_loaded = get_already_loaded(bq_client)
    log.info(f"Already in BigQuery: {len(already_loaded)} (day, fault) pairs")

    pending = []
    success = skip = fail = missing = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        d = start
        while d <= end:
            day_str = d.isoformat()

            # Check if all faults already loaded for this day
            if all((day_str, fid) in already_loaded for fid in FAULT_SYSTEMS):
                skip += 1
                d += timedelta(days=1)
                continue

            # Download from GCS
            blob = bucket.blob(gcs_path(d))
            if not blob.exists():
                missing += 1
                d += timedelta(days=1)
                continue

            local_path = os.path.join(tmpdir, "igsg.ionex")
            try:
                blob.download_to_filename(local_path)
            except Exception as e:
                log.warning(f"{d} GCS download error: {e}")
                fail += 1
                d += timedelta(days=1)
                continue

            # Parse
            regional = parse_ionex_regional(local_path)
            if regional is None:
                log.warning(f"{d} parse failed")
                fail += 1
                d += timedelta(days=1)
                continue

            success += 1
            for fid, r in regional.items():
                if (day_str, fid) in already_loaded:
                    continue
                if r:
                    pending.append({
                        "day":                day_str,
                        "fault_id":           fid,
                        "tec_fullday_mean":   r["tec_fullday_mean"],
                        "tec_nighttime_mean": r["tec_nighttime_mean"],
                        "n_cells":            r["n_cells"],
                        "n_maps_valid":       r["n_maps_valid"],
                    })

            # Clean up
            if os.path.exists(local_path):
                os.remove(local_path)

            done = (d - start).days + 1
            if done % 50 == 0:
                log.info(f"Progress: {done}/{total} | "
                         f"parsed={success} skip={skip} missing={missing} fail={fail}")

            # Batch load
            if len(pending) >= args.batch_size * len(FAULT_SYSTEMS):
                load_batch_to_bq(bq_client, pending)
                pending = []

            d += timedelta(days=1)

    # Final batch
    if pending:
        load_batch_to_bq(bq_client, pending)

    log.info(f"Complete: {success} parsed, {skip} skipped, "
             f"{missing} missing from GCS, {fail} failed")

    # Validation
    for row in bq_client.query(f"""
        SELECT fault_id, COUNT(*) AS days,
               ROUND(AVG(tec_fullday_mean),2) AS avg_tec,
               MIN(day) AS earliest, MAX(day) AS latest
        FROM `{PROJECT}.{DATASET}.{TABLE_RAW}`
        GROUP BY fault_id ORDER BY fault_id
    """).result():
        log.info(f"  {row.fault_id:25s} days={row.days} "
                 f"avg={row.avg_tec} {row.earliest}→{row.latest}")


if __name__ == "__main__":
    main()
