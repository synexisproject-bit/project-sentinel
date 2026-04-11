#!/usr/bin/env python3
"""
HGEO-01: Download global geomagnetic indices.
  - Kp index (3-hourly → daily max/mean) from GFZ Potsdam
  - Dst index (hourly → daily min) from WDC Kyoto
  - F10.7 solar flux (daily) from GFZ — solar control variable
  - Ap index (daily) from GFZ

Sources:
  Kp/Ap/F10.7: https://kp.gfz-potsdam.de/app/files/Kp_ap_Ap_SN_F107_since_1932.txt
  Dst: https://wdc.kugi.kyoto-u.ac.jp/dst_final/YYYYMM/index.html (monthly HTML scrape)
      fallback: https://wdc.kugi.kyoto-u.ac.jp/dst_realtime/YYYYMM/index.html

Output: /tmp/geo_indices_daily.csv
  columns: date, kp_max, kp_mean, ap_daily, f107, dst_min, dst_mean
"""

import re
import time
import requests
import pandas as pd
from datetime import date, timedelta
from io import StringIO

START_DATE = date(2001, 1, 1)
END_DATE   = date(2025, 12, 31)
OUT_PATH   = "/tmp/geo_indices_daily.csv"

KP_URL = "https://kp.gfz-potsdam.de/app/files/Kp_ap_Ap_SN_F107_since_1932.txt"

# ── KP / AP / F10.7 ──────────────────────────────────────────────────────────

def download_kp_file() -> pd.DataFrame:
    """
    GFZ file format (space-separated):
    #YYY MM DD days  Kp1 Kp2 Kp3 Kp4 Kp5 Kp6 Kp7 Kp8  Ap1..Ap8  Ap  SN  F107  D
    Kp values are in thirds: 0,3,7,10,13,17,20,23,27,30,33,37,40,...
    Divide by 10 to get standard Kp (0.0–9.0)
    """
    print("Downloading Kp/Ap/F10.7 from GFZ Potsdam …")
    r = requests.get(KP_URL, timeout=120)
    r.raise_for_status()

    rows = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) < 26:
            continue
        try:
            year = int(parts[0])
            mon  = int(parts[1])
            day  = int(parts[2])
            d    = date(year, mon, day)
            if d < START_DATE or d > END_DATE:
                continue
            # Format: YYYY MM DD days days_m SN? ? Kp1-8(idx7-14) ap1-8(idx15-22) Ap(23) SN(24) F107(25)
            kp_vals  = [float(x) for x in parts[7:15]]
            ap_daily = int(parts[23])
            f107_raw = float(parts[25])
            f107     = f107_raw if f107_raw > 0 else None
            rows.append({
                "date":     d,
                "kp_max":   max(kp_vals),
                "kp_mean":  sum(kp_vals) / 8.0,
                "ap_daily": ap_daily,
                "f107":     f107,
            })
        except (ValueError, IndexError):
            continue

    df = pd.DataFrame(rows)
    print(f"  Kp/Ap/F10.7: {len(df)} daily rows ({df['date'].min()} → {df['date'].max()})")
    return df


# ── DST INDEX ─────────────────────────────────────────────────────────────────

def download_dst_month(year: int, month: int, realtime: bool = False) -> list[dict]:
    """
    Scrape WDC Kyoto monthly Dst HTML page.
    Final data available through ~2023; provisional/realtime for recent months.
    """
    base = "dst_realtime" if realtime else "dst_final"
    url  = f"https://wdc.kugi.kyoto-u.ac.jp/{base}/{year:04d}{month:02d}/index.html"

    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 404 and not realtime:
            # Try provisional
            url2 = f"https://wdc.kugi.kyoto-u.ac.jp/dst_provisional/{year:04d}{month:02d}/index.html"
            r = requests.get(url2, timeout=30)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    # Parse hourly Dst values from HTML table
    # Format: rows of 24 hourly values per day
    rows = []
    text = r.text

    # Find data lines: lines with day number followed by 24 integer values
    # Pattern: "  1  -12  -15  -8 ..."
    data_pattern = re.compile(
        r'^\s{0,3}(\d{1,2})\s+((?:[+-]?\d+\s+){23}[+-]?\d+)', re.MULTILINE
    )

    import calendar
    n_days = calendar.monthrange(year, month)[1]

    for match in data_pattern.finditer(text):
        day_num = int(match.group(1))
        if day_num < 1 or day_num > n_days:
            continue
        try:
            vals = [int(x) for x in match.group(2).split()]
            if len(vals) != 24:
                continue
            # Filter out fill values (9999, -999)
            valid = [v for v in vals if abs(v) < 500]
            if not valid:
                continue
            d = date(year, month, day_num)
            rows.append({
                "date":     d,
                "dst_min":  min(valid),
                "dst_mean": sum(valid) / len(valid),
            })
        except (ValueError, AttributeError):
            continue

    return rows


def download_dst_all() -> pd.DataFrame:
    print("Downloading Dst from WDC Kyoto …")
    all_rows = []
    cur = START_DATE.replace(day=1)
    end = END_DATE.replace(day=1)

    while cur <= end:
        rows = download_dst_month(cur.year, cur.month, realtime=False)
        if not rows:
            rows = download_dst_month(cur.year, cur.month, realtime=True)
        all_rows.extend(rows)

        # Progress every 12 months
        if cur.month == 1:
            print(f"  Dst: processed through {cur.year-1} …")

        # Advance month
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)

        time.sleep(0.3)  # be polite to WDC server

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("  WARNING: No Dst data retrieved")
        return df
    print(f"  Dst: {len(df)} daily rows ({df['date'].min()} → {df['date'].max()})")
    return df


# ── MERGE AND SAVE ────────────────────────────────────────────────────────────

def main():
    df_kp  = download_kp_file()
    df_dst = download_dst_all()

    if df_dst.empty:
        print("WARNING: Dst download failed — proceeding with Kp/F10.7 only")
        df = df_kp.copy()
        df["dst_min"]  = None
        df["dst_mean"] = None
    else:
        df = df_kp.merge(df_dst, on="date", how="left")

    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = df["date"].astype(str)

    # Fill any gaps with interpolation
    for col in ["kp_max", "kp_mean", "ap_daily", "f107", "dst_min", "dst_mean"]:
        if col in df.columns:
            df[col] = df[col].interpolate(method="linear", limit=3)

    df.to_csv(OUT_PATH, index=False)
    print(f"\nGlobal indices saved → {OUT_PATH}")
    print(f"Columns: {list(df.columns)}")
    print(f"Rows: {len(df)}")
    print(f"Date range: {df['date'].min()} → {df['date'].max()}")
    null_counts = df.isnull().sum()
    if null_counts.any():
        print(f"Nulls: {null_counts[null_counts > 0].to_dict()}")
    print("\nHGEO-01 complete.")


if __name__ == "__main__":
    main()
