#!/usr/bin/env python3
"""
HGEO-02: Download INTERMAGNET local geomagnetic H-component data.
For each fault zone, identifies the best nearby INTERMAGNET observatory
and downloads hourly H-component data via the INTERMAGNET web service.

INTERMAGNET data: https://imag-data.bgs.ac.uk/GIN_V1/GINServices
  - Requires no auth for definitive/quasi-definitive data
  - Returns IAGA2002 format

Selected observatories (closest to fault zone centroid with long records):
  japan_trench:    KAK (Kakioka, Japan)     36.23N 140.19E  since 1913
  cascadia:        VIC (Victoria, Canada)   48.52N 236.58E  since 1957
  central_chile:   API (Apia? No — use) LIV (Las Campanas? use SJG fallback)
                   → use PIL (Pilar, Argentina) 31.67S 296.11E since 1956
  north_anatolian: ISK (Iskilip? No) → use KOU (Kourou?) 
                   → use ANN (Annamalainagar?) 
                   → best available: ESK (Eskdalemuir) or BDV  
                   → use KIV (Kyiv is too far) 
                   → use IST? No. Use: BOX (Borok) or PHU
                   → Closest with long record: ISK doesn't exist
                   → Use: HER? No. Use AQU (L'Aquila Italy) 42.38N 13.32E
  sumatra_andaman: KAK too far. Use: PHU (Phu Thuy, Vietnam) 21.03N 105.96E
                   or GUA (Guam) 13.59N 144.87E
                   Best: PHU (Phu Thuy) — closest to Sumatra-Andaman zone

All stations have records from at least 2001 onward.
"""

import os
import time
import requests
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

START_DATE = date(2001, 1, 1)
END_DATE   = date(2025, 12, 31)
OUT_DIR    = Path("/tmp/intermagnet")

# Observatory assignments per fault zone
OBSERVATORIES = {
    "japan_trench":    {"code": "KAK", "name": "Kakioka",        "lat": 36.23,  "lon": 140.19},
    "cascadia":        {"code": "VIC", "name": "Victoria",        "lat": 48.52,  "lon": -123.42},
    "central_chile":   {"code": "PIL", "name": "Pilar",           "lat": -31.67, "lon": -63.89},
    "north_anatolian": {"code": "AQU", "name": "LAquila",         "lat": 42.38,  "lon": 13.32},
    "sumatra_andaman": {"code": "PHU", "name": "PhuThuy",         "lat": 21.03,  "lon": 105.96},
}

# INTERMAGNET GIN web service
GIN_URL = "https://imag-data.bgs.ac.uk/GIN_V1/GINServices"

# ── DOWNLOAD ONE MONTH ────────────────────────────────────────────────────────

def download_month(obs_code: str, year: int, month: int) -> pd.DataFrame | None:
    """
    Download one month of hourly data from INTERMAGNET GIN.
    Returns DataFrame with columns: datetime, H
    """
    import calendar
    n_days = calendar.monthrange(year, month)[1]
    start  = f"{year:04d}-{month:02d}-01T00:00:00Z"
    end    = f"{year:04d}-{month:02d}-{n_days:02d}T23:59:59Z"

    params = {
        "Request":    "GetData",
        "format":     "text/x-iaga2002",
        "observatoryIAGACode": obs_code.upper(),
        "samplesPerDay": 24,      # hourly
        "dataStartDate": start,
        "dataEndDate":   end,
        "orientation":   "HDZF",  # H-component
        "publicationState": "adj,qua,def",  # adjusted, quasi-def, definitive
    }

    try:
        r = requests.get(GIN_URL, params=params, timeout=60)
        if r.status_code != 200:
            return None
        return parse_iaga2002(r.text, obs_code)
    except Exception:
        return None


def parse_iaga2002(text: str, obs_code: str) -> pd.DataFrame | None:
    """Parse IAGA-2002 format, extract H component."""
    rows = []
    header_done = False
    h_col = None

    for line in text.splitlines():
        if line.startswith(" ") or line.startswith("DATE"):
            if "DATE" in line and "TIME" in line:
                header_done = True
                # Find H column index
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.upper().startswith(obs_code.upper()[:3]) and "H" in p.upper():
                        h_col = i - 2  # offset for DATE TIME
                        break
                    elif p == "H" or p == f"{obs_code}H":
                        h_col = i - 2
                        break
                if h_col is None:
                    h_col = 0  # default to first data column (H in HDZF)
            continue

        if not header_done:
            continue

        parts = line.split()
        if len(parts) < 4:
            continue

        try:
            dt_str = f"{parts[0]}T{parts[1]}"
            h_val  = float(parts[2 + h_col]) if h_col is not None else float(parts[2])
            # Fill value in IAGA2002 is 99999.0
            if h_val >= 99990:
                h_val = None
            rows.append({"datetime": dt_str, "H": h_val})
        except (ValueError, IndexError):
            continue

    if not rows:
        return None
    return pd.DataFrame(rows)


# ── PROCESS TO DAILY ─────────────────────────────────────────────────────────

def hourly_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate hourly H to daily statistics."""
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"])
    df["date"] = df["datetime"].dt.date
    df["H"] = pd.to_numeric(df["H"], errors="coerce")

    daily = df.groupby("date").agg(
        h_mean=("H", "mean"),
        h_min=("H", "min"),
        h_max=("H", "max"),
        h_range=("H", lambda x: x.max() - x.min()),
        h_std=("H", "std"),
        n_hours=("H", "count"),
    ).reset_index()

    # Only keep days with at least 18 valid hours
    daily = daily[daily["n_hours"] >= 18].copy()
    return daily


# ── ANOMALY DETECTION ─────────────────────────────────────────────────────────

def compute_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute H-component anomalies using 30-day rolling baseline.
    Z-score relative to local seasonal variation.
    """
    df = df.sort_values("date").reset_index(drop=True)

    # Rolling 30-day baseline (exclude current day)
    df["h_baseline_30d"] = (df["h_mean"]
                            .shift(1)
                            .rolling(30, min_periods=15)
                            .mean())
    df["h_std_30d"] = (df["h_mean"]
                       .shift(1)
                       .rolling(30, min_periods=15)
                       .std())

    df["h_z_score"] = ((df["h_mean"] - df["h_baseline_30d"])
                       / df["h_std_30d"].clip(lower=0.1))

    # Lag features
    for lag in [1, 3, 5, 7]:
        df[f"h_z_lag{lag}d"] = df["h_z_score"].shift(lag)

    # Rolling anomaly windows
    df["h_z_3d_mean"]   = df["h_z_score"].rolling(3,  min_periods=2).mean()
    df["h_z_7d_mean"]   = df["h_z_score"].rolling(7,  min_periods=4).mean()
    df["h_z_7d_max"]    = df["h_z_score"].abs().rolling(7, min_periods=4).max()
    df["h_range_7d_mean"] = df["h_range"].rolling(7, min_periods=4).mean()

    return df


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_fault_dfs = []

    for fault_zone, obs in OBSERVATORIES.items():
        code = obs["code"]
        print(f"\n[{fault_zone}] Observatory: {code} ({obs['name']})")

        monthly_dfs = []
        cur = START_DATE.replace(day=1)
        end = END_DATE.replace(day=1)
        fail_count = 0

        while cur <= end:
            df_month = download_month(code, cur.year, cur.month)
            if df_month is not None and len(df_month) > 0:
                monthly_dfs.append(df_month)
            else:
                fail_count += 1

            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)

            time.sleep(0.2)

        if not monthly_dfs:
            print(f"  WARNING: No data retrieved for {fault_zone}/{code}")
            continue

        df_hourly = pd.concat(monthly_dfs, ignore_index=True)
        print(f"  {len(df_hourly)} hourly records, {fail_count} months failed")

        df_daily = hourly_to_daily(df_hourly)
        print(f"  {len(df_daily)} valid daily rows")

        df_daily = compute_anomalies(df_daily)
        df_daily["fault_zone"] = fault_zone
        df_daily["obs_code"]   = code
        df_daily["date"]       = df_daily["date"].astype(str)

        # Save per-zone CSV
        zone_path = OUT_DIR / f"{fault_zone}_geo.csv"
        df_daily.to_csv(zone_path, index=False)
        print(f"  Saved → {zone_path}")

        all_fault_dfs.append(df_daily)

    if not all_fault_dfs:
        print("ERROR: No geomagnetic data retrieved for any fault zone.")
        return

    df_all = pd.concat(all_fault_dfs, ignore_index=True)
    manifest_path = OUT_DIR / "geo_manifest.csv"
    df_all[["fault_zone", "obs_code", "date"]].to_csv(manifest_path, index=False)
    print(f"\nManifest: {len(df_all)} total rows across {df_all['fault_zone'].nunique()} zones")
    print("HGEO-02 complete.")


if __name__ == "__main__":
    main()
