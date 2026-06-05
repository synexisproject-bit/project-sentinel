#!/usr/bin/env python3
"""
H2-05: GNSS Strain Triangulation Feature Engineering
Amendment #9 | osf.io/8hvf6 | Pre-registered before execution

Computes dilatation strain and maximum shear strain from Delaunay
triangulation of NGL TENV3 station networks per fault zone.

Method:
  1. Re-parse TENV3 files (same as h2_03)
  2. Fit secular + seasonal model, extract residuals per station
  3. Build Delaunay triangulation across stations per fault zone
  4. For each triangle, each date: compute 2D strain tensor
     from 3-vertex east/north displacement residuals
  5. Extract dilatation (e_xx + e_yy) and max shear strain
  6. Area-weighted aggregation across triangles per day
  7. Z-score normalization (rolling 365-day baseline)
  8. Write to sentinel_features.h2_strain_features_daily

Strain computation (constant strain triangle, CST element):
  u(x,y) = a1 + a2*x + a3*y  =>  e_xx = a2, e_xy_u = a3
  v(x,y) = b1 + b2*x + b3*y  =>  e_yy = b3, e_xy_v = b2
  e_xy = 0.5 * (a3 + b2)
  dilatation = e_xx + e_yy
  max_shear  = sqrt(((e_xx - e_yy)/2)^2 + e_xy^2)

Units: displacement in mm, positions in km => strain in microstrain (mm/km)
"""

import os
import math
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from scipy.linalg import lstsq
from scipy.spatial import Delaunay
from google.cloud import bigquery

warnings.filterwarnings("ignore")

PROJECT_ID  = "synexis-project-sentinel"
DATASET     = "sentinel_features"
TABLE       = "h2_strain_features_daily"
STATION_CSV = "/tmp/h2_stations.csv"
TENV3_DIR   = Path("/tmp/tenv3")
MANIFEST_CSV = "/tmp/h2_tenv3_manifest.csv"

FAULT_AZIMUTH = {
    "japan_trench":    280.0,
    "cascadia":        100.0,
    "central_chile":    80.0,
    "north_anatolian":  20.0,
    "sumatra_andaman":  50.0,
}

# Local projection center per fault zone (lon0, lat0)
FAULT_CENTER = {
    "japan_trench":    (141.0, 38.0),
    "cascadia":        (-125.0, 46.0),
    "central_chile":   (-71.0, -33.0),
    "north_anatolian": (34.0, 40.0),
    "sumatra_andaman": (98.0, 5.0),
}

R_EARTH_KM = 6371.0

# Max triangle edge length (km) — filter degenerate triangles
MAX_EDGE_KM = 300.0
# Min stations to attempt triangulation
MIN_STATIONS = 3

BQ_SCHEMA = [
    bigquery.SchemaField("fault_zone",          "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("date_val",             "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("dilatation_z",         "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("shear_z",              "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("dilatation_max_z",     "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("shear_max_z",          "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("dilatation_raw",       "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("shear_raw",            "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("dilatation_7d_mean",   "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("dilatation_14d_mean",  "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("shear_7d_mean",        "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("shear_7d_max",         "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("n_triangles",          "INT64",   mode="NULLABLE"),
    bigquery.SchemaField("n_stations",           "INT64",   mode="NULLABLE"),
]


def log(msg):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── TENV3 PARSER (same as h2_03) ─────────────────────────────────────────────

def parse_tenv3(filepath):
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
                    e_m = float(parts[8])
                    n_m = float(parts[9])
                    rows.append({
                        "dec_year": dec_year,
                        "e_mm": e_m * 1000.0,
                        "n_mm": n_m * 1000.0,
                    })
                except (ValueError, IndexError):
                    continue
    except Exception:
        return None
    if len(rows) < 365:
        return None
    df = pd.DataFrame(rows).sort_values("dec_year").reset_index(drop=True)
    return df


def decimal_year_to_date(dy):
    year = int(dy)
    remainder = dy - year
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    days = (end - start).days
    d = start + pd.Timedelta(days=remainder * days)
    return d.date()


def fit_secular_seasonal(t, y):
    omega = 2.0 * math.pi
    A = np.column_stack([
        np.ones(len(t)), t,
        np.cos(omega * t), np.sin(omega * t),
        np.cos(2 * omega * t), np.sin(2 * omega * t),
    ])
    coef, _, _, _ = lstsq(A, y)
    return y - A @ coef


# ── LOCAL PROJECTION ─────────────────────────────────────────────────────────

def latlon_to_local_km(lat, lon, lat0, lon0):
    """Convert lat/lon to local Cartesian (km) centered at (lat0, lon0)."""
    x = (lon - lon0) * math.cos(math.radians(lat0)) * R_EARTH_KM * math.pi / 180.0
    y = (lat - lat0) * R_EARTH_KM * math.pi / 180.0
    return x, y


def triangle_area_km2(x1, y1, x2, y2, x3, y3):
    return abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0


def max_edge_km(x1, y1, x2, y2, x3, y3):
    d12 = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    d23 = math.sqrt((x3 - x2) ** 2 + (y3 - y2) ** 2)
    d13 = math.sqrt((x3 - x1) ** 2 + (y3 - y1) ** 2)
    return max(d12, d23, d13)


# ── STRAIN TENSOR COMPUTATION ─────────────────────────────────────────────────

def compute_strain(x1, y1, x2, y2, x3, y3, u1, u2, u3, v1, v2, v3):
    """
    Compute 2D strain tensor for a constant strain triangle (CST).
    Positions (x,y) in km, displacements (u east, v north) in mm.
    Returns (e_xx, e_yy, e_xy) in microstrain (mm/km).
    Returns None if system is singular.
    """
    A = np.array([
        [1.0, x1, y1],
        [1.0, x2, y2],
        [1.0, x3, y3],
    ])
    det = np.linalg.det(A)
    if abs(det) < 1e-10:
        return None
    A_inv = np.linalg.inv(A)
    # u = a1 + a2*x + a3*y
    a = A_inv @ np.array([u1, u2, u3])
    # v = b1 + b2*x + b3*y
    b = A_inv @ np.array([v1, v2, v3])
    e_xx = a[1]          # du/dx
    e_yy = b[2]          # dv/dy
    e_xy = 0.5 * (a[2] + b[1])  # 0.5*(du/dy + dv/dx)
    return e_xx, e_yy, e_xy


# ── PER-STATION PROCESSING ────────────────────────────────────────────────────

def process_station_residuals(station_id, tenv3_path):
    """Returns DataFrame with columns: date_val, e_resid_mm, n_resid_mm"""
    df = parse_tenv3(tenv3_path)
    if df is None:
        return None
    t = df["dec_year"].values
    try:
        resid_e = fit_secular_seasonal(t, df["e_mm"].values)
        resid_n = fit_secular_seasonal(t, df["n_mm"].values)
    except Exception:
        return None
    dates = [decimal_year_to_date(dy) for dy in t]
    return pd.DataFrame({
        "date_val":   dates,
        "e_resid_mm": resid_e,
        "n_resid_mm": resid_n,
        "station_id": station_id,
    })


# ── STRAIN FEATURES PER FAULT ZONE ───────────────────────────────────────────

def build_strain_features(fault_zone, station_df, station_residuals, lat0, lon0):
    """
    Build daily strain features for a fault zone.
    station_df: DataFrame with station_id, lat, lon
    station_residuals: dict of station_id -> DataFrame(date_val, e_resid_mm, n_resid_mm)
    Returns daily DataFrame with strain features.
    """
    # Convert station positions to local Cartesian
    stations = []
    for _, row in station_df.iterrows():
        sid = row["station_id"]
        if sid not in station_residuals:
            continue
        x, y = latlon_to_local_km(row["lat"], row["lon"], lat0, lon0)
        stations.append({
            "station_id": sid,
            "x_km": x,
            "y_km": y,
        })

    if len(stations) < MIN_STATIONS:
        log(f"  {fault_zone}: only {len(stations)} stations with data — skipping")
        return None

    stations_df = pd.DataFrame(stations)
    coords = stations_df[["x_km", "y_km"]].values
    log(f"  {fault_zone}: {len(stations)} stations, building Delaunay triangulation")

    tri = Delaunay(coords)
    simplices = tri.simplices

    # Filter degenerate triangles
    valid_simplices = []
    triangle_areas = []
    for s in simplices:
        i, j, k = s
        x1, y1 = coords[i]
        x2, y2 = coords[j]
        x3, y3 = coords[k]
        edge = max_edge_km(x1, y1, x2, y2, x3, y3)
        if edge > MAX_EDGE_KM:
            continue
        area = triangle_area_km2(x1, y1, x2, y2, x3, y3)
        if area < 1.0:  # degenerate
            continue
        valid_simplices.append(s)
        triangle_areas.append(area)

    if not valid_simplices:
        log(f"  {fault_zone}: no valid triangles after filtering")
        return None

    log(f"  {fault_zone}: {len(valid_simplices)} valid triangles "
        f"(from {len(simplices)} total)")

    # Build date-indexed residual lookup per station
    residual_lookup = {}
    for sid, df_r in station_residuals.items():
        if sid not in stations_df["station_id"].values:
            continue
        residual_lookup[sid] = df_r.set_index("date_val")

    # Get all dates across all stations
    all_dates = set()
    for sid, df_r in residual_lookup.items():
        all_dates.update(df_r.index.tolist())
    all_dates = sorted(all_dates)

    log(f"  {fault_zone}: computing strain over {len(all_dates)} dates...")

    daily_rows = []
    total_area = sum(triangle_areas)

    for d in all_dates:
        dilatations = []
        shears = []
        weights = []

        for idx_t, (s, area) in enumerate(zip(valid_simplices, triangle_areas)):
            i, j, k = s
            sid_i = stations_df.iloc[i]["station_id"]
            sid_j = stations_df.iloc[j]["station_id"]
            sid_k = stations_df.iloc[k]["station_id"]

            # Check all three vertices have data on this date
            try:
                row_i = residual_lookup[sid_i].loc[d]
                row_j = residual_lookup[sid_j].loc[d]
                row_k = residual_lookup[sid_k].loc[d]
            except KeyError:
                continue

            u1, v1 = row_i["e_resid_mm"], row_i["n_resid_mm"]
            u2, v2 = row_j["e_resid_mm"], row_j["n_resid_mm"]
            u3, v3 = row_k["e_resid_mm"], row_k["n_resid_mm"]

            x1, y1 = coords[i]
            x2, y2 = coords[j]
            x3, y3 = coords[k]

            result = compute_strain(x1, y1, x2, y2, x3, y3,
                                    u1, u2, u3, v1, v2, v3)
            if result is None:
                continue

            e_xx, e_yy, e_xy = result
            dilatation = e_xx + e_yy
            shear = math.sqrt(((e_xx - e_yy) / 2) ** 2 + e_xy ** 2)

            dilatations.append(dilatation)
            shears.append(shear)
            weights.append(area)

        if len(dilatations) < 1:
            continue

        weights = np.array(weights)
        weights_norm = weights / weights.sum()
        dilatations = np.array(dilatations)
        shears = np.array(shears)

        daily_rows.append({
            "fault_zone":     fault_zone,
            "date_val":       str(d),
            "dilatation_raw": float(np.average(dilatations, weights=weights_norm)),
            "shear_raw":      float(np.average(shears, weights=weights_norm)),
            "dilatation_max": float(np.max(dilatations)),
            "shear_max":      float(np.max(shears)),
            "n_triangles":    len(dilatations),
            "n_stations":     len(stations),
        })

    if not daily_rows:
        log(f"  {fault_zone}: no daily strain rows computed")
        return None

    df_daily = pd.DataFrame(daily_rows)
    df_daily["date_val"] = pd.to_datetime(df_daily["date_val"])
    df_daily = df_daily.sort_values("date_val").reset_index(drop=True)

    # Filter to >=3 triangles contributing
    df_daily = df_daily[df_daily["n_triangles"] >= 3].copy()

    log(f"  {fault_zone}: {len(df_daily)} daily rows "
        f"({df_daily['date_val'].min()} to {df_daily['date_val'].max()})")

    return df_daily


# ── Z-SCORE NORMALIZATION (rolling 365-day baseline) ─────────────────────────

def add_zscores_and_windows(df):
    df = df.sort_values("date_val").reset_index(drop=True)
    for col, zcol in [("dilatation_raw", "dilatation_z"),
                       ("shear_raw", "shear_z"),
                       ("dilatation_max", "dilatation_max_z"),
                       ("shear_max", "shear_max_z")]:
        rolling = df[col].rolling(window=365, min_periods=90)
        mean = rolling.mean()
        std  = rolling.std()
        df[zcol] = (df[col] - mean) / std.replace(0, np.nan)

    df["dilatation_7d_mean"]  = df["dilatation_z"].rolling(7,  min_periods=3).mean()
    df["dilatation_14d_mean"] = df["dilatation_z"].rolling(14, min_periods=7).mean()
    df["shear_7d_mean"]       = df["shear_z"].rolling(7, min_periods=3).mean()
    df["shear_7d_max"]        = df["shear_z"].rolling(7, min_periods=3).max()
    return df


# ── BIGQUERY LOAD ─────────────────────────────────────────────────────────────

def init_bq_table(client, table_ref):
    client.delete_table(table_ref, not_found_ok=True)
    table_obj = bigquery.Table(table_ref, schema=BQ_SCHEMA)
    client.create_table(table_obj)
    log(f"Created BQ table: {table_ref}")


def stream_to_bq(client, table_ref, df):
    keep_cols = [f.name for f in BQ_SCHEMA]
    df_out = df[[c for c in keep_cols if c in df.columns]].copy()
    df_out["date_val"] = df_out["date_val"].astype(str)
    rows = df_out.to_dict(orient="records")
    errors_all = []
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            errors_all.extend(errors)
    if errors_all:
        log(f"  WARNING: {len(errors_all)} BQ insert errors")
    return len(rows)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    log("=== H2-05: Strain Triangulation Feature Engineering ===")
    log("Amendment #9 | osf.io/8hvf6")

    df_stations = pd.read_csv(STATION_CSV)
    df_manifest = pd.read_csv(MANIFEST_CSV)
    df = df_stations.merge(df_manifest, on="station_id", how="inner")
    log(f"Loaded {len(df)} station-fault assignments with TENV3 files")

    client    = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{TABLE}"
    init_bq_table(client, table_ref)

    total_rows = 0

    for fault_zone, group in df.groupby("fault_zone"):
        log(f"\n[{fault_zone}] Processing {len(group)} stations...")

        # Load per-station residuals
        station_residuals = {}
        for _, row in group.iterrows():
            tenv3_path = row["tenv3_path"]
            if not Path(tenv3_path).exists():
                continue
            result = process_station_residuals(row["station_id"], tenv3_path)
            if result is not None and len(result) > 100:
                station_residuals[row["station_id"]] = result

        log(f"  {len(station_residuals)} stations processed successfully")

        if len(station_residuals) < MIN_STATIONS:
            log(f"  Insufficient stations for {fault_zone} — skipping")
            continue

        lon0, lat0 = FAULT_CENTER[fault_zone]
        df_strain = build_strain_features(
            fault_zone, group, station_residuals, lat0, lon0
        )

        if df_strain is None or len(df_strain) == 0:
            continue

        df_strain = add_zscores_and_windows(df_strain)

        n = stream_to_bq(client, table_ref, df_strain)
        total_rows += n
        log(f"  Loaded {n} rows to BQ")

    log(f"\n=== H2-05 complete. Total rows: {total_rows} ===")


if __name__ == "__main__":
    main()
