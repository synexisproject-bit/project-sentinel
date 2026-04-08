#!/usr/bin/env python3
"""
Project Sentinel — IONEX to GCS Uploader
Downloads IONEX files from CDDIS and uploads to GCS bucket.
Run from Cloud Shell where CDDIS auth works.

Resume support: checks GCS before downloading — skips existing files.

Run:
    nohup python3 ionex_to_gcs.py --start-year 2001 --end-year 2025 \
        > logs/ionex_gcs.log 2>&1 &
"""

import argparse
import logging
import os
import subprocess
import tempfile
from datetime import date, timedelta

import requests
from google.cloud import storage

PROJECT    = "synexis-project-sentinel"
BUCKET     = "sentinel-ionex-cache"
CDDIS_BASE = "https://cddis.nasa.gov/archive/gnss/products/ionex"
USERNAME   = "synexisproject"
PASSWORD   = "REDACTED"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


def make_session():
    s = requests.Session()
    s.auth = (USERNAME, PASSWORD)
    return s


def ionex_urls(d):
    doy = d.timetuple().tm_yday
    yy  = d.strftime("%y")
    yr  = d.year
    base = f"{CDDIS_BASE}/{yr}/{doy:03d}"
    old = f"{base}/igsg{doy:03d}0.{yy}i.Z"
    new = f"{base}/IGS0OPSFIN_{yr}{doy:03d}0000_01D_02H_GIM.INX.gz"
    return [old, new] if yr < 2024 else [new, old]


def gcs_path(d):
    doy = d.timetuple().tm_yday
    return f"{d.year}/{doy:03d}/igsg{doy:03d}0.ionex"


def already_uploaded(bucket, d):
    blob = bucket.blob(gcs_path(d))
    return blob.exists()


def download_and_decompress(session, d, tmpdir):
    out_file = os.path.join(tmpdir, "igsg.ionex")
    for url in ionex_urls(d):
        try:
            r = session.get(url, timeout=60)
            if r.status_code != 200 or len(r.content) < 1000:
                continue
            if b'<!DOCTYPE' in r.content[:100]:
                continue
            if url.endswith('.gz'):
                import gzip
                data = gzip.decompress(r.content)
            elif url.endswith('.Z'):
                zfile = os.path.join(tmpdir, "igsg.Z")
                with open(zfile, 'wb') as f:
                    f.write(r.content)
                result = subprocess.run(
                    ['uncompress', '-f', '-c', zfile],
                    capture_output=True
                )
                if result.returncode != 0:
                    continue
                data = result.stdout
            else:
                data = r.content

            with open(out_file, 'wb') as f:
                f.write(data)
            return out_file
        except Exception as e:
            log.debug(f"{d} error ({url}): {e}")
            continue
    return None


def upload_to_gcs(bucket, d, filepath):
    blob = bucket.blob(gcs_path(d))
    blob.upload_from_filename(filepath)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year",   type=int, default=2025)
    args = parser.parse_args()

    start = date(args.start_year, 1, 1)
    end   = date(args.end_year, 12, 31)
    total = (end - start).days + 1

    log.info(f"IONEX → GCS uploader: {start} to {end} ({total} days)")
    log.info(f"Bucket: gs://{BUCKET}")

    storage_client = storage.Client(project=PROJECT)
    bucket = storage_client.bucket(BUCKET)
    session = make_session()

    success = skip = fail = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        d = start
        while d <= end:
            if already_uploaded(bucket, d):
                skip += 1
                d += timedelta(days=1)
                continue

            filepath = download_and_decompress(session, d, tmpdir)

            if filepath:
                try:
                    upload_to_gcs(bucket, d, filepath)
                    success += 1
                    log.debug(f"{d} uploaded")
                except Exception as e:
                    log.warning(f"{d} upload failed: {e}")
                    fail += 1
                # Clean up
                for f in os.listdir(tmpdir):
                    os.remove(os.path.join(tmpdir, f))
            else:
                log.warning(f"{d} download failed")
                fail += 1

            done = (d - start).days + 1
            if done % 100 == 0:
                log.info(f"Progress: {done}/{total} | "
                         f"success={success} fail={fail} skip={skip}")

            d += timedelta(days=1)

    log.info(f"Done: {success} uploaded, {fail} failed, {skip} skipped")
    log.info(f"Files in GCS: gs://{BUCKET}/")


if __name__ == "__main__":
    main()
