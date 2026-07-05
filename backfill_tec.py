#!/usr/bin/env python3
"""
Project Sentinel — TEC Backfill
Downloads IGS combined IONEX files from CDDIS, extracts global mean VTEC,
computes 27-day rolling anomaly z-score, and loads into env_daily in BigQuery.

Resume support: parsed results are cached to tec_cache.csv in the same directory.
If interrupted, re-running will skip already-cached days.
"""

import csv
import gzip as gzmod
import logging
import argparse
import os
import statistics
import subprocess
import tempfile
from datetime import date, timedelta

import requests
from google.cloud import bigquery, secretmanager

PROJECT       = "synexis-project-sentinel"
DATASET       = "sentinel_features"
TABLE         = "env_daily"
CDDIS_BASE    = "https://cddis.nasa.gov/archive/gnss/products/ionex"
USERNAME      = "synexisproject"
def _get_secret(project_id, secret_name):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

PASSWORD      = _get_secret(PROJECT, "cddis-password")
CACHE_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tec_cache.csv")
ROLLING_WINDOW = 27
MIN_WINDOW     = 14

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def make_session():
    s = requests.Session()
    s.auth = (USERNAME, PASSWORD)
    return s


def ionex_urls(d):
    doy  = d.timetuple().tm_yday
    yy   = d.strftime("%y")
    yr   = d.year
    base = f"{CDDIS_BASE}/{yr}/{doy:03d}"
    old_url = f"{base}/igsg{doy:03d}0.{yy}i.Z"
    new_url = f"{base}/IGS0OPSFIN_{yr}{doy:03d}0000_01D_02H_GIM.INX.gz"
    return [new_url, old_url] if yr >= 2024 else [old_url, new_url]


def download_ionex(session, d, tmpdir):
    out_file = os.path.join(tmpdir, "igsg.ionex")
    for url in ionex_urls(d):
        try:
            r = session.get(url, timeout=30)
            if r.status_code != 200:
                continue
            if b'<!DOCTYPE' in r.content[:100]:
                continue
            if url.endswith('.gz'):
                try:
                    data = gzmod.decompress(r.content)
                except Exception as e:
                    log.debug(f"{d} gzip error: {e}")
                    continue
            elif url.endswith('.Z'):
                out_z = os.path.join(tmpdir, "igsg.Z")
                with open(out_z, 'wb') as f:
                    f.write(r.content)
                result = subprocess.run(['uncompress', '-f', '-c', out_z], capture_output=True)
                if result.returncode != 0:
                    continue
                data = result.stdout
            else:
                data = r.content
            with open(out_file, 'wb') as f:
                f.write(data)
            return out_file
        except Exception as e:
            log.debug(f"{d} download error: {e}")
            continue
    return None


def parse_ionex_global_mean(filepath):
    exponent = -1
    in_tec_map = False
    values = []
    header_done = False
    try:
        with open(filepath, 'r', errors='replace') as f:
            for line in f:
                if not header_done:
                    if 'EXPONENT' in line[60:]:
                        try:
                            exponent = int(line[:6].strip())
                        except ValueError:
                            pass
                    if 'END OF HEADER' in line[60:]:
                        header_done = True
                    continue
                if 'START OF TEC MAP' in line[60:]:
                    in_tec_map = True
                    continue
                if 'END OF TEC MAP' in line[60:]:
                    in_tec_map = False
                    continue
                if in_tec_map:
                    if '/' in line or 'LAT' in line or 'LON' in line:
                        continue
                    for p in line.split():
                        try:
                            v = int(p)
                            if v != 9999:
                                values.append(v)
                        except ValueError:
                            continue
        if not values:
            return None
        return round(statistics.mean(values) * (10 ** exponent), 4)
    except Exception as e:
        log.debug(f"Parse error: {e}")
        return None


def compute_anomalies(daily_tec):
    sorted_dates = sorted(daily_tec.keys())
    anomalies = {}
    for i, d in enumerate(sorted_dates):
        window_vals = [daily_tec[sorted_dates[j]] for j in range(max(0, i - ROLLING_WINDOW), i)
                       if daily_tec.get(sorted_dates[j]) is not None]
        if len(window_vals) < MIN_WINDOW:
            anomalies[d] = None
            continue
        median = statistics.median(window_vals)
        try:
            std = statistics.stdev(window_vals)
        except statistics.StatisticsError:
            std = 0.0
        tec = daily_tec[d]
        if tec is None:
            anomalies[d] = None
        elif std < 0.01:
            anomalies[d] = 0.0
        else:
            anomalies[d] = round((tec - median) / std, 4)
    return anomalies


def ensure_columns(client):
    table_ref = f"{PROJECT}.{DATASET}.{TABLE}"
    table = client.get_table(table_ref)
    existing = {f.name for f in table.schema}
    new_fields = []
    if 'tec_global_mean' not in existing:
        new_fields.append(bigquery.SchemaField('tec_global_mean', 'FLOAT64'))
    if 'tec_anomaly_zscore' not in existing:
        new_fields.append(bigquery.SchemaField('tec_anomaly_zscore', 'FLOAT64'))
    if new_fields:
        table.schema = list(table.schema) + new_fields
        client.update_table(table, ['schema'])
        log.info(f"Added columns: {[f.name for f in new_fields]}")
    else:
        log.info("TEC columns already exist")


def load_to_bq(client, rows):
    if not rows:
        return
    tmp_table = f"{PROJECT}.{DATASET}.tec_staging"
    schema = [
        bigquery.SchemaField('day', 'DATE'),
        bigquery.SchemaField('tec_global_mean', 'FLOAT64'),
        bigquery.SchemaField('tec_anomaly_zscore', 'FLOAT64'),
    ]
    bq_rows = [{'day': r['day'].isoformat(), 'tec_global_mean': r['tec_global_mean'],
                'tec_anomaly_zscore': r['tec_anomaly_zscore']} for r in rows]
    job = client.load_table_from_json(bq_rows, tmp_table,
          job_config=bigquery.LoadJobConfig(schema=schema, write_disposition='WRITE_TRUNCATE'))
    job.result()
    client.query(f"""
    MERGE `{PROJECT}.{DATASET}.{TABLE}` T USING `{tmp_table}` S ON T.day = S.day
    WHEN MATCHED THEN UPDATE SET T.tec_global_mean=S.tec_global_mean, T.tec_anomaly_zscore=S.tec_anomaly_zscore
    """).result()
    client.delete_table(tmp_table, not_found_ok=True)
    log.info(f"MERGE complete: {len(bq_rows)} days updated.")


def load_cache():
    daily_tec = {}
    if not os.path.exists(CACHE_FILE):
        return daily_tec
    with open(CACHE_FILE, 'r', newline='') as f:
        for row in csv.DictReader(f):
            d = date.fromisoformat(row['day'])
            v = row['tec_global_mean']
            daily_tec[d] = float(v) if v else None
    log.info(f"Loaded {len(daily_tec)} cached days from {CACHE_FILE}")
    return daily_tec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-year', type=int, default=2001)
    parser.add_argument('--end-year',   type=int, default=2026)
    parser.add_argument('--dry-run',    action='store_true')
    parser.add_argument('--batch-size', type=int, default=365)
    args = parser.parse_args()

    start_date = date(args.start_year, 1, 1)
    end_date   = date(args.end_year, 12, 31)
    total_days = (end_date - start_date).days + 1
    log.info(f"TEC backfill: {start_date} to {end_date} ({total_days} days)")

    session = make_session()
    client  = None if args.dry_run else bigquery.Client(project=PROJECT)
    if not args.dry_run:
        ensure_columns(client)

    # Load cache
    daily_tec = load_cache()
    success = sum(1 for v in daily_tec.values() if v is not None)
    fail = 0

    # Open cache for appending
    is_new = not os.path.exists(CACHE_FILE) or os.path.getsize(CACHE_FILE) == 0
    cache_fh = open(CACHE_FILE, 'a', newline='')
    cache_writer = csv.writer(cache_fh)
    if is_new:
        cache_writer.writerow(['day', 'tec_global_mean'])

    with tempfile.TemporaryDirectory() as tmpdir:
        d = start_date
        while d <= end_date:
            if d in daily_tec:
                d += timedelta(days=1)
                continue
            filepath = download_ionex(session, d, tmpdir)
            if filepath:
                tec = parse_ionex_global_mean(filepath)
                daily_tec[d] = tec
                if tec is not None:
                    success += 1
                    log.info(f"{d} tec_mean={tec:.2f} TECu")
                    cache_writer.writerow([d.isoformat(), tec])
                else:
                    log.warning(f"{d} parse failed")
                    fail += 1
                    cache_writer.writerow([d.isoformat(), ''])
                cache_fh.flush()
                for fname in os.listdir(tmpdir):
                    os.remove(os.path.join(tmpdir, fname))
            else:
                daily_tec[d] = None
                fail += 1
                if d.month == 1 and d.day == 1:
                    log.warning(f"{d} download failed (year boundary)")
            d += timedelta(days=1)
            done = (d - start_date).days
            if done % 30 == 0:
                log.info(f"Progress: {done}/{total_days} | success={success} fail={fail}")

    cache_fh.close()
    log.info(f"Download complete: {success} success, {fail} fail out of {total_days} days")

    log.info("Computing 27-day rolling anomalies...")
    anomalies = compute_anomalies(daily_tec)
    log.info(f"Anomaly z-scores: {sum(1 for v in anomalies.values() if v is not None)} days")

    if args.dry_run:
        log.info("DRY RUN — skipping BQ load")
        for d in sorted(d for d in daily_tec if daily_tec[d] is not None)[:5]:
            log.info(f"  {d}: tec={daily_tec[d]:.2f}  z={anomalies.get(d)}")
        return

    rows = [{'day': d, 'tec_global_mean': tec, 'tec_anomaly_zscore': anomalies.get(d)}
            for d, tec in sorted(daily_tec.items()) if tec is not None]

    for i in range(0, len(rows), args.batch_size):
        batch = rows[i:i + args.batch_size]
        log.info(f"Batch {i//args.batch_size + 1}: {batch[0]['day']} to {batch[-1]['day']}")
        load_to_bq(client, batch)

    log.info("TEC backfill complete.")

    val_sql = f"""
    SELECT COUNT(*) as total_rows, COUNTIF(tec_global_mean IS NOT NULL) as tec_filled,
           COUNTIF(tec_anomaly_zscore IS NOT NULL) as anomaly_filled,
           ROUND(AVG(tec_global_mean),2) as avg_tec,
           ROUND(MIN(tec_global_mean),2) as min_tec,
           ROUND(MAX(tec_global_mean),2) as max_tec
    FROM `{PROJECT}.{DATASET}.{TABLE}`
    """
    for row in client.query(val_sql).result():
        log.info(f"Validation: {dict(row)}")


if __name__ == '__main__':
    main()
