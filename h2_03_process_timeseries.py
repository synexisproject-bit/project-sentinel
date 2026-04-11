#!/usr/bin/env python3
"""
H2-03: Process TENV3 time series.
  - Parse TENV3 files (IGS14 reference frame)
  - Fit secular + seasonal model (linear + annual + semi-annual sinusoids)
  - Compute residuals in fault-perpendicular direction
  - Network-stack residuals per fault zone per day (Rousset et al. 2019 approach)
  - Stream to BigQuery: h2_features_daily
"""

import math
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, date
import warnings
warnings.filterwarnings("ignore")

from scipy.linalg import lstsq
from google.cloud import bigquery

PROJECT_ID = "synexis-project-sentinel"
DATASET    = "sentinel_features"
TABLE_DAILY = "h2_features_daily"

STATION_CSV   = "/tmp/h2_stations.csv"
MANIFEST_CSV  = "/tmp/h2_tenv3_manifest.csv"

# Fault-perpendicular azimuths (degrees from North, clockwise)
# Residuals are projected onto the fault-perpendicular direction
FAULT_AZIMUTH = {
    "japan_trench":    280.0,   # ~N80W (roughly trench-normal)
    "cascadia":        100.0,   # ~S80E
    "central_chile":    80.0,   # ~S80E
    "north_anatolian":  20.0,   # ~N20E
    "sumatra_andaman":  50.0,   # ~N50E
}

BQ_SCHEMA_DAILY = [
    bigquery.SchemaField("fault_zone",        "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("date_val",           "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("stack_fp_mm",        "FLOAT64", mode="NULLABLE"),  # fault-perp stack
    bigquery.SchemaField("stack_fp_std",       "FLOAT64", mode="NULLABLE"),  # network std
    bigquery.SchemaField("n_stations",         "INT64",   mode="NULLABLE"),
    bigquery.SchemaField("mean_east_resid_mm", "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("mean_north_resid_mm","FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("mean_up_resid_mm",   "FLOAT64", mode="NULLABLE"),
]

# ─── TENV3 PARSER ────────────────────────────────────────────────────────────

def parse_tenv3(filepath: str) -> pd.DataFrame | None:
    """
    Parse NGL TENV3 file.
    Columns (IGS14): SSSS YYMMMDD decimal_year MJD  e_ref n_ref u_ref
                      e_obs n_obs u_obs sig_e sig_n sig_u  Cor_EN Cor_EU Cor_NU
    We need: decimal_year, e_obs, n_obs, u_obs (in meters → convert to mm)
    """
    rows = []
    try:
        with open(filepath, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("*"):
                    continue
                parts = line.split()
                if len(parts) < 12:
                    continue
                try:
                    dec_year = float(parts[2])
                    # positions in IGS14 reference frame (meters)
                    e_m = float(parts[8])
                    n_m = float(parts[9])
                    u_m = float(parts[10])
                    rows.append({
                        "dec_year": dec_year,
                        "e_mm": e_m * 1000.0,
                        "n_mm": n_m * 1000.0,
                        "u_mm": u_m * 1000.0,
                    })
                except (ValueError, IndexError):
                    continue
    except Exception:
        return None

    if len(rows) < 365:   # need at least 1 year of data
        return None

    df = pd.DataFrame(rows).sort_values("dec_year").reset_index(drop=True)
    return df


def decimal_year_to_date(dy: float) -> date:
    year = int(dy)
    remainder = dy - year
    start = datetime(year, 1, 1)
    end   = datetime(year + 1, 1, 1)
    days  = (end - start).days
    d = start + pd.Timedelta(days=remainder * days)
    return d.date()


# ─── SECULAR + SEASONAL MODEL ────────────────────────────────────────────────

def fit_secular_seasonal(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    """
    Fit: y = a + b*t + c1*cos(2pi*t) + s1*sin(2pi*t) + c2*cos(4pi*t) + s2*sin(4pi*t)
    Returns residuals.
    """
    omega = 2.0 * math.pi
    A = np.column_stack([
        np.ones(len(t)),
        t,
        np.cos(omega * t),   np.sin(omega * t),
        np.cos(2*omega * t), np.sin(2*omega * t),
    ])
    coef, _, _, _ = lstsq(A, y)
    y_fit = A @ coef
    return y - y_fit


# ─── FAULT-PERPENDICULAR PROJECTION ──────────────────────────────────────────

def project_fault_perp(e_resid: np.ndarray, n_resid: np.ndarray,
                       azimuth_deg: float) -> np.ndarray:
    """
    Project (east, north) residual vector onto fault-perpendicular direction.
    azimuth_deg: fault-perpendicular azimuth, measured CW from North.
    """
    az_rad  = math.radians(azimuth_deg)
    # Unit vector in fault-perp direction (east component, north component)
    fp_east  =  math.sin(az_rad)
    fp_north =  math.cos(az_rad)
    return e_resid * fp_east + n_resid * fp_north


# ─── PER-STATION PROCESSING ──────────────────────────────────────────────────

def process_station(station_id: str, tenv3_path: str, fault_zone: str
                    ) -> pd.DataFrame | None:
    df = parse_tenv3(tenv3_path)
    if df is None:
        return None

    t = df["dec_year"].values

    try:
        resid_e = fit_secular_seasonal(t, df["e_mm"].values)
        resid_n = fit_secular_seasonal(t, df["n_mm"].values)
        resid_u = fit_secular_seasonal(t, df["u_mm"].values)
    except Exception:
        return None

    az = FAULT_AZIMUTH.get(fault_zone, 0.0)
    fp = project_fault_perp(resid_e, resid_n, az)

    dates = [decimal_year_to_date(dy) for dy in t]

    return pd.DataFrame({
        "date_val":   dates,
        "fp_mm":      fp,
        "e_resid_mm": resid_e,
        "n_resid_mm": resid_n,
        "u_resid_mm": resid_u,
        "station_id": station_id,
        "fault_zone": fault_zone,
    })


# ─── NETWORK STACKING (Rousset et al. 2019) ──────────────────────────────────

def network_stack(station_dfs: list[pd.DataFrame], fault_zone: str
                  ) -> pd.DataFrame:
    """
    Combine per-station residuals into daily fault-zone stack.
    Simple inverse-variance weighting; std across stations used as uncertainty.
    """
    combined = pd.concat(station_dfs, ignore_index=True)
    combined["date_val"] = pd.to_datetime(combined["date_val"])

    daily = (combined.groupby("date_val")
             .agg(
                 stack_fp_mm        =("fp_mm",      "median"),
                 stack_fp_std       =("fp_mm",      "std"),
                 n_stations         =("station_id", "nunique"),
                 mean_east_resid_mm =("e_resid_mm", "median"),
                 mean_north_resid_mm=("n_resid_mm", "median"),
                 mean_up_resid_mm   =("u_resid_mm", "median"),
             )
             .reset_index())

    # Only keep days with ≥3 contributing stations (network requirement)
    daily = daily[daily["n_stations"] >= 3].copy()
    daily["fault_zone"] = fault_zone
    daily["date_val"]   = daily["date_val"].dt.date.astype(str)
    return daily


# ─── BIGQUERY LOAD ────────────────────────────────────────────────────────────

def init_bq_table(client: bigquery.Client, table_ref: str, schema):
    client.delete_table(table_ref, not_found_ok=True)
    table_obj = bigquery.Table(table_ref, schema=schema)
    client.create_table(table_obj)
    print(f"  Created {table_ref}")


def stream_to_bq(client: bigquery.Client, table_ref: str,
                 df: pd.DataFrame, chunk_size: int = 500):
    rows = df.to_dict(orient="records")
    errors_all = []
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i+chunk_size]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            errors_all.extend(errors)
    if errors_all:
        print(f"  WARNING: {len(errors_all)} BQ insert errors (first: {errors_all[0]})")
    return len(rows)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    df_stations = pd.read_csv(STATION_CSV)
    df_manifest = pd.read_csv(MANIFEST_CSV)

    # Join so we know which stations have files
    df = df_stations.merge(df_manifest, on="station_id", how="inner")
    print(f"Processing {len(df)} station-fault assignments with TENV3 files …")

    client    = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{TABLE_DAILY}"
    init_bq_table(client, table_ref, BQ_SCHEMA_DAILY)

    total_rows = 0

    for fault_zone, group in df.groupby("fault_zone"):
        az = FAULT_AZIMUTH.get(fault_zone, 0.0)
        print(f"\n[{fault_zone}] {len(group)} stations | fault-perp azimuth={az}°")

        station_dfs = []
        for _, row in group.iterrows():
            result = process_station(row.station_id, row.tenv3_path, fault_zone)
            if result is not None and len(result) > 0:
                station_dfs.append(result)

        if not station_dfs:
            print(f"  No valid stations for {fault_zone} — skipping")
            continue

        print(f"  {len(station_dfs)} stations processed successfully")

        stack_df = network_stack(station_dfs, fault_zone)
        print(f"  Stack: {len(stack_df)} daily rows (date range: "
              f"{stack_df['date_val'].min()} → {stack_df['date_val'].max()})")

        n = stream_to_bq(client, table_ref, stack_df)
        total_rows += n
        print(f"  Loaded {n} rows → BQ")

    print(f"\nH2-03 complete. Total rows loaded: {total_rows}")


if __name__ == "__main__":
    main()
