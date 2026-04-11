#!/usr/bin/env python3
"""
H2-01: Download NGL station list and identify stations within fault bounding boxes.
Outputs sentinel_features.h2_stations in BigQuery.
"""

import requests
import pandas as pd
import io
import json
from google.cloud import bigquery

PROJECT_ID = "synexis-project-sentinel"
DATASET    = "sentinel_features"
TABLE      = "h2_stations"

# Fault bounding boxes: [lon_min, lon_max, lat_min, lat_max]
FAULT_BOXES = {
    "japan_trench":      [130.0, 148.0,  30.0,  46.0],
    "cascadia":          [-130.0, -120.0, 40.0,  52.0],
    "central_chile":     [-76.0, -65.0, -40.0, -18.0],
    "north_anatolian":   [ 26.0,  42.0,  38.0,  42.5],
    "sumatra_andaman":   [ 94.0, 106.0,  -6.0,  15.0],
}

NGL_STATION_LIST_URL = "https://geodesy.unr.edu/NGLStationPages/llh.out"

BQ_SCHEMA = [
    bigquery.SchemaField("station_id",  "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("lat",         "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("lon",         "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("elev_m",      "FLOAT64", mode="NULLABLE"),
    bigquery.SchemaField("fault_zone",  "STRING",  mode="REQUIRED"),
]


def fetch_station_list() -> pd.DataFrame:
    print("Fetching NGL station list …")
    r = requests.get(NGL_STATION_LIST_URL, timeout=60)
    r.raise_for_status()
    # Format: SSSS  lat  lon  elev  (whitespace-separated, header line starts with #)
    lines = [l for l in r.text.splitlines() if l.strip() and not l.startswith("#")]
    rows = []
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            rows.append({
                "station_id": parts[0].upper(),
                "lat":  float(parts[1]),
                "lon":  float(parts[2]),
                "elev_m": float(parts[3]),
            })
        except ValueError:
            continue
    df = pd.DataFrame(rows)
    print(f"  {len(df)} stations in NGL list")
    return df


def assign_fault_zones(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in df.iterrows():
        for fault, (lon_min, lon_max, lat_min, lat_max) in FAULT_BOXES.items():
            if lon_min <= row.lon <= lon_max and lat_min <= row.lat <= lat_max:
                records.append({
                    "station_id": row.station_id,
                    "lat":        row.lat,
                    "lon":        row.lon,
                    "elev_m":     row.elev_m,
                    "fault_zone": fault,
                })
    result = pd.DataFrame(records).drop_duplicates(subset=["station_id", "fault_zone"])
    print(f"  {len(result)} station-fault assignments across {result['fault_zone'].nunique()} fault zones")
    for fz, grp in result.groupby("fault_zone"):
        print(f"    {fz}: {len(grp)} stations")
    return result


def load_to_bigquery(df: pd.DataFrame):
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET}.{TABLE}"

    # Drop + recreate for clean run
    client.delete_table(table_ref, not_found_ok=True)
    table_obj = bigquery.Table(table_ref, schema=BQ_SCHEMA)
    client.create_table(table_obj)
    print(f"  Created {table_ref}")

    rows = df.to_dict(orient="records")
    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"BQ insert errors: {errors}")
    print(f"  Loaded {len(rows)} rows → {table_ref}")


def main():
    df_all    = fetch_station_list()
    df_faults = assign_fault_zones(df_all)
    load_to_bigquery(df_faults)

    # Write station list to disk for h2_02
    out_path = "/tmp/h2_stations.csv"
    df_faults.to_csv(out_path, index=False)
    print(f"\nStation list written to {out_path}")
    print("H2-01 complete.")


if __name__ == "__main__":
    main()
