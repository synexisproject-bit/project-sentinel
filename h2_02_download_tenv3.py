#!/usr/bin/env python3
"""
H2-02: Download TENV3 time-series files from Nevada Geodetic Lab for all stations
identified by h2_01. Saves raw files to /tmp/tenv3/ for h2_03 to process.
"""

import os
import time
import requests
import pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

TENV3_BASE = "https://geodesy.unr.edu/gps_timeseries/tenv3/IGS14/{station}.tenv3"
STATION_CSV = "/tmp/h2_stations.csv"
OUT_DIR     = Path("/tmp/tenv3")
MAX_WORKERS = 8
RETRY_LIMIT = 3
DELAY_RETRY = 5  # seconds between retries


def download_one(station_id: str) -> tuple[str, bool, str]:
    url     = TENV3_BASE.format(station=station_id.upper())
    outfile = OUT_DIR / f"{station_id.upper()}.tenv3"

    if outfile.exists() and outfile.stat().st_size > 1000:
        return station_id, True, "cached"

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return station_id, False, "404 not found"
            r.raise_for_status()
            outfile.write_bytes(r.content)
            return station_id, True, f"{len(r.content)//1024} KB"
        except Exception as e:
            if attempt == RETRY_LIMIT:
                return station_id, False, str(e)
            time.sleep(DELAY_RETRY)

    return station_id, False, "max retries"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not Path(STATION_CSV).exists():
        raise FileNotFoundError(
            f"{STATION_CSV} not found — run h2_01_get_stations.py first"
        )

    df = pd.read_csv(STATION_CSV)
    stations = df["station_id"].unique().tolist()
    print(f"Downloading TENV3 for {len(stations)} stations ({MAX_WORKERS} workers) …")

    ok, fail = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(download_one, s): s for s in stations}
        for i, fut in enumerate(as_completed(futures), 1):
            sid, success, msg = fut.result()
            if success:
                ok.append(sid)
            else:
                fail.append((sid, msg))
            if i % 50 == 0 or i == len(stations):
                print(f"  [{i}/{len(stations)}] ok={len(ok)} fail={len(fail)}")

    print(f"\nDownload complete: {len(ok)} succeeded, {len(fail)} failed")
    if fail:
        print("Failed stations:")
        for sid, reason in fail[:20]:
            print(f"  {sid}: {reason}")
        if len(fail) > 20:
            print(f"  … and {len(fail)-20} more")

    # Write manifest so h2_03 knows what's available
    manifest = [{"station_id": s, "tenv3_path": str(OUT_DIR / f"{s}.tenv3")} for s in ok]
    manifest_df = pd.DataFrame(manifest)
    manifest_df.to_csv("/tmp/h2_tenv3_manifest.csv", index=False)
    print(f"\nManifest written to /tmp/h2_tenv3_manifest.csv")
    print("H2-02 complete.")


if __name__ == "__main__":
    main()
