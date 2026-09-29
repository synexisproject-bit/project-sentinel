#!/usr/bin/env python3
"""
build_geonet_roster.py

Builds a station roster for the GEONET network from GSI POS coordinate files.

Each POS file carries a +SITE/INF header block with the six-digit site ID, the
four-character RINEX code, and the station name in Japanese and English, plus a
+SOLVER/INF block declaring reference frame, software and processing version.
The first data row gives latitude, longitude and height.

This produces the mapping needed to join three GEONET products:
  site ID (6 digit)  -> maintenance_list.xlsx
  RINEX code (4 char) -> observation filenames in GRJE_3.02 etc.

Retrieval is paced and sequential, in accordance with GSI terms of service
regarding data volume and automated collection. One year of POS files is
roughly 1,300 files at about 8 KB each, so approximately 10 MB total.

Usage:
  python3 build_geonet_roster.py                  # defaults to 2020
  python3 build_geonet_roster.py --year 2022
  python3 build_geonet_roster.py --year 2020 --delay 0.5
  python3 build_geonet_roster.py --year 2020 --limit 25    # test run

Requires: paramiko
  pip3 install --break-system-packages paramiko
"""

import argparse
import csv
import gzip
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    import paramiko
except ImportError:
    sys.exit("paramiko not installed. Run: pip3 install --break-system-packages paramiko")

HOST = "terras.gsi.go.jp"
PORT = 22
USERNAME = "JosephT26"
SECRET_NAME = "geonet-sftp-password"
GCP_PROJECT = "synexis-project-sentinel"
REMOTE_BASE = "/data/coordinates_F5.1"


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def get_password():
    """Read the SFTP password from Secret Manager. Never hardcode it."""
    env = os.environ.get("GEONET_SFTP_PASSWORD")
    if env:
        return env
    try:
        out = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest",
             "--secret", SECRET_NAME, "--project", GCP_PROJECT],
            capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except subprocess.CalledProcessError as e:
        sys.exit(f"Could not read secret {SECRET_NAME}: {e.stderr.strip()}")


def classify_site(site_id):
    """
    GEONET site IDs encode installation era and operator.
    Numeric-only IDs beginning 92-99 or 00-19 are GSI stations, numbered by
    installation year. IDs containing a letter in position 3 (P, S, H, R)
    denote other categories, including partner and private networks.
    Homogeneity of receiver and antenna practice is better assured within the
    GSI set, so the two are distinguished here rather than merged.
    """
    s = str(site_id)
    if s.isdigit():
        return "GSI"
    for ch in s:
        if ch.isalpha():
            return f"OTHER_{ch.upper()}"
    return "UNKNOWN"


def parse_pos(raw_bytes):
    """Parse a gzipped GSI POS file. Returns a dict, or None if unparseable."""
    try:
        text = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
    except Exception:
        return None

    rec = {
        "site_id": "", "rinex_id": "", "name_jp": "", "name_en": "",
        "soft_name": "", "ephemeris": "", "solution_id": "", "version": "",
        "coordinate_frame": "", "ellipsoid": "", "history_id": "",
        "epoch_start": "", "epoch_end": "", "epoch_count": "",
        "first_date": "", "x_m": "", "y_m": "", "z_m": "",
        "lat_deg": "", "lon_deg": "", "height_m": "", "n_data_rows": 0,
    }

    section = None
    in_data = False

    for line in text.splitlines():
        if line.startswith("+"):
            section = line[1:].strip()
            in_data = (section == "DATA")
            continue
        if line.startswith("-"):
            section = None
            in_data = False
            continue
        if not line.strip() or line.startswith("*"):
            continue

        if section == "SITE/INF":
            parts = line.split(None, 1)
            if len(parts) == 2:
                key, val = parts[0].strip(), parts[1].strip()
                if key == "ID":
                    rec["site_id"] = val
                elif key == "RINEX":
                    rec["rinex_id"] = val
                elif key == "J_NAME":
                    rec["name_jp"] = val
                elif key == "E_NAME":
                    rec["name_en"] = val

        elif section == "SOLVER/INF":
            parts = line.split(None, 1)
            if len(parts) == 2:
                key, val = parts[0].strip(), parts[1].strip()
                mapping = {
                    "SOFT_NAME": "soft_name", "EPHEMERIS": "ephemeris",
                    "SOLUTION_ID": "solution_id", "VERSION": "version",
                    "COORDINATE": "coordinate_frame", "ELLIPSOID": "ellipsoid",
                    "HISTORY_ID": "history_id",
                }
                if key in mapping:
                    rec[mapping[key]] = val
                elif key == "EPOCH":
                    for token in val.replace("START=", "|START=") \
                                    .replace("END=", "|END=") \
                                    .replace("COUNT=", "|COUNT=").split("|"):
                        token = token.strip()
                        if token.startswith("START="):
                            rec["epoch_start"] = token[6:].strip()
                        elif token.startswith("END="):
                            rec["epoch_end"] = token[4:].strip()
                        elif token.startswith("COUNT="):
                            rec["epoch_count"] = token[6:].strip()

        elif in_data:
            f = line.split()
            if len(f) >= 10:
                rec["n_data_rows"] += 1
                if not rec["first_date"]:
                    # POS values are in scientific notation. Normalize to plain
                    # decimals so the CSV is readable and filterable.
                    def num(v, places):
                        try:
                            return f"{float(v):.{places}f}"
                        except ValueError:
                            return v
                    rec["first_date"] = f"{f[0]}-{f[1]}-{f[2]}"
                    rec["x_m"] = num(f[4], 4)
                    rec["y_m"] = num(f[5], 4)
                    rec["z_m"] = num(f[6], 4)
                    rec["lat_deg"] = num(f[7], 7)
                    rec["lon_deg"] = num(f[8], 7)
                    rec["height_m"] = num(f[9], 4)

    if not rec["site_id"] or not rec["lat_deg"]:
        return None
    rec["site_class"] = classify_site(rec["site_id"])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2020", help="Archive year to read (default 2020)")
    ap.add_argument("--delay", type=float, default=0.3,
                    help="Seconds between file requests (default 0.3)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N files. 0 means all. Use for a test run")
    ap.add_argument("--cache", default="pos_cache",
                    help="Local directory for downloaded POS files")
    ap.add_argument("--out", default="geonet_station_roster.csv")
    args = ap.parse_args()

    remote_dir = f"{REMOTE_BASE}/{args.year}"
    os.makedirs(args.cache, exist_ok=True)

    log(f"Connecting to {HOST} as {USERNAME}")
    transport = paramiko.Transport((HOST, PORT))
    transport.connect(username=USERNAME, password=get_password())
    sftp = paramiko.SFTPClient.from_transport(transport)

    log(f"Listing {remote_dir}")
    names = sorted(n for n in sftp.listdir(remote_dir) if n.endswith(".pos.gz"))
    if args.limit:
        names = names[:args.limit]
    log(f"{len(names)} POS files to process")

    records, failed, cached, fetched = [], [], 0, 0

    for i, name in enumerate(names, 1):
        local = os.path.join(args.cache, name)
        try:
            if os.path.exists(local) and os.path.getsize(local) > 0:
                with open(local, "rb") as fh:
                    raw = fh.read()
                cached += 1
            else:
                buf = io.BytesIO()
                sftp.getfo(f"{remote_dir}/{name}", buf)
                raw = buf.getvalue()
                with open(local, "wb") as fh:
                    fh.write(raw)
                fetched += 1
                time.sleep(args.delay)

            rec = parse_pos(raw)
            if rec:
                rec["source_file"] = name
                records.append(rec)
            else:
                failed.append((name, "unparseable"))
        except Exception as e:
            failed.append((name, str(e)))

        if i % 100 == 0 or i == len(names):
            log(f"  {i}/{len(names)}  ok={len(records)} failed={len(failed)}")

    sftp.close()
    transport.close()

    if not records:
        sys.exit("No records parsed. Nothing written.")

    cols = ["site_id", "rinex_id", "name_en", "name_jp", "site_class",
            "lat_deg", "lon_deg", "height_m", "x_m", "y_m", "z_m",
            "coordinate_frame", "ellipsoid", "soft_name", "ephemeris",
            "solution_id", "version", "history_id",
            "epoch_start", "epoch_end", "epoch_count",
            "first_date", "n_data_rows", "source_file"]

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(records, key=lambda r: r["site_id"]):
            w.writerow(r)

    lats = [float(r["lat_deg"]) for r in records]
    lons = [float(r["lon_deg"]) for r in records]
    classes = {}
    frames = {}
    for r in records:
        classes[r["site_class"]] = classes.get(r["site_class"], 0) + 1
        frames[r["coordinate_frame"]] = frames.get(r["coordinate_frame"], 0) + 1

    log("")
    log(f"Wrote {args.out}: {len(records)} stations")
    log(f"  fetched {fetched}, from cache {cached}, failed {len(failed)}")
    log(f"  latitude  {min(lats):.4f} to {max(lats):.4f}")
    log(f"  longitude {min(lons):.4f} to {max(lons):.4f}")
    log(f"  site class: {dict(sorted(classes.items()))}")
    log(f"  reference frame: {frames}")
    log(f"  retrieved {datetime.now(timezone.utc).isoformat()} from {remote_dir}")

    if failed:
        with open("roster_failures.txt", "w") as fh:
            for name, why in failed:
                fh.write(f"{name}\t{why}\n")
        log(f"  {len(failed)} failures written to roster_failures.txt")


if __name__ == "__main__":
    main()
