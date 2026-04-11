#!/usr/bin/env python3
"""
HGEO-03: Merge global geomagnetic indices (Kp, Dst, F10.7) with
local H-component anomalies per fault zone, load to BigQuery.

Output table: sentinel_features.hgeo_features_daily
"""

import pandas as pd
from pathlib import Path
from google.cloud import bigquery

PROJECT_ID   = "synexis-project-sentinel"
DATASET      = "sentinel_features"
TABLE        = "hgeo_features_daily"
INDICES_CSV  = "/tmp/geo_indices_daily.csv"
GEO_DIR      = Path("/tmp/intermagnet")

BQ_SCHEMA = [
    bigquery.SchemaField("fault_id",          "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("date_val",           "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("obs_code",           "STRING",  mode="NULLABLE"),
    # Global indices
    bigquery.SchemaField("kp_max",             "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("kp_mean",            "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("ap_daily",           "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("f107",               "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("dst_min",            "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("dst_mean",           "FLOAT64", mode="NULLABLE"),
    # Local H-component
    bigquery.SchemaField("h_mean",             "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_range",            "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_std",              "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_score",          "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_lag1d",          "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_lag3d",          "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_lag5d",          "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_lag7d",          "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_3d_mean",        "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_7d_mean",        "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_z_7d_max",         "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("h_range_7d_mean",    "FLOAT64", mode="NULLABLE"),
]

FAULT_ZONES = [
    "japan_trench", "cascadia", "central_chile",
    "north_anatolian", "sumatra_andaman"
]


def load_global_indices() -> pd.DataFrame:
    df = pd.read_csv(INDICES_CSV, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    print(f"Global indices: {len(df)} rows")
    return df


def load_local_geo(fault_zone: str) -> pd.DataFrame | None:
    path = GEO_DIR / f"{fault_zone}_geo.csv"
    if not path.exists():
        print(f"  WARNING: {path} not found")
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def merge_fault_zone(fault_zone: str, df_global: pd.DataFrame) -> pd.DataFrame:
    df_local = load_local_geo(fault_zone)

    if df_local is not None:
        # Merge on date
        df = df_global.merge(df_local, on="date", how="left")
        obs_code = df_local["obs_code"].iloc[0] if "obs_code" in df_local.columns else None
    else:
        df = df_global.copy()
        obs_code = None
        # Add null local columns
        for col in ["h_mean", "h_range", "h_std", "h_z_score",
                    "h_z_lag1d", "h_z_lag3d", "h_z_lag5d", "h_z_lag7d",
                    "h_z_3d_mean", "h_z_7d_mean", "h_z_7d_max", "h_range_7d_mean"]:
            df[col] = None

    df["fault_id"] = fault_zone
    df["obs_code"] = obs_code
    df = df.rename(columns={"date": "date_val"})
    df["date_val"] = df["date_val"].astype(str)

    # Keep only schema columns
    schema_cols = [f.name for f in BQ_SCHEMA]
    for col in schema_cols:
        if col not in df.columns:
            df[col] = None
    df = df[schema_cols]

    return df


def load_to_bigquery(df_all: pd.DataFrame):
    import time
    client    = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{TABLE}"

    client.delete_table(table_ref, not_found_ok=True)
    table_obj = bigquery.Table(table_ref, schema=BQ_SCHEMA)
    client.create_table(table_obj)
    time.sleep(30)
    print(f"Created {table_ref}")

    import math
    df_all = df_all.replace({float("nan"): None})
    df_all = df_all.where(pd.notna(df_all), other=None)
    rows = df_all.to_dict(orient="records")
    # Replace any remaining float nan with None
    rows = [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k,v in row.items()} for row in rows]
    chunk_size = 500
    errors_all = []
    for i in range(0, len(rows), chunk_size):
        chunk  = rows[i:i+chunk_size]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            errors_all.extend(errors)
    if errors_all:
        print(f"  WARNING: {len(errors_all)} BQ insert errors")
    print(f"Loaded {len(rows)} rows → {table_ref}")


def main():
    df_global = load_global_indices()

    all_dfs = []
    for fault_zone in FAULT_ZONES:
        print(f"\nMerging {fault_zone} …")
        df = merge_fault_zone(fault_zone, df_global)
        print(f"  {len(df)} rows, local H: {'yes' if df['h_z_score'].notna().any() else 'NO'}")
        all_dfs.append(df)

    df_all = pd.concat(all_dfs, ignore_index=True)
    print(f"\nTotal: {len(df_all)} rows across {df_all['fault_id'].nunique()} fault zones")

    load_to_bigquery(df_all)
    print("\nHGEO-03 complete.")


if __name__ == "__main__":
    main()
