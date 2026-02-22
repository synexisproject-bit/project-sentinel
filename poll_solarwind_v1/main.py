import os, json, time, base64
from datetime import datetime, timezone, timedelta
import requests
from google.cloud import bigquery
from flask import Flask, request

app = Flask(__name__)
PROJECT   = os.environ.get("PROJECT")
BQ_DATASET= os.environ.get("BQ_DATASET","sentinel_raw")
BQ_TABLE  = os.environ.get("BQ_TABLE")
TABLE_ID  = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
bq        = bigquery.Client()

def ensure_table(schema):
    try:
        bq.get_table(TABLE_ID)
    except Exception:
        ds = bigquery.Dataset(f"{PROJECT}.{BQ_DATASET}")
        try:
            bq.get_dataset(ds)
        except Exception:
            bq.create_dataset(ds, exists_ok=True)
        bq.create_table(bigquery.Table(TABLE_ID, schema=schema), exists_ok=True)

def insert_rows(rows):
    if not rows:
        return "NOOP"
    errors = bq.insert_rows_json(TABLE_ID, rows)
    if errors:
        raise RuntimeError(errors)
    return f"OK ({len(rows)} rows)"

@app.route("/", methods=["POST","GET"])
def run():
    try:
        return poll()
    except Exception as e:
        return (f"ERROR: {e}", 500)

# POLL FUNCTION IS DEFINED PER SERVICE BELOW

def poll():
    # NOAA SWPC DSCOVR: plasma + magnetic field (last day)
    plasma = requests.get("https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json", timeout=20).json()
    mag    = requests.get("https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json", timeout=20).json()

    # First row is header; combine by timestamp if possible
    head_p = plasma[0]; rows_p = plasma[1:]
    head_m = mag[0];    rows_m = mag[1:]
    idx_m = { r[0]: r for r in rows_m if r and r[0] }  # keyed by time

    schema = [
        bigquery.SchemaField("time","TIMESTAMP"),
        bigquery.SchemaField("density","FLOAT"),
        bigquery.SchemaField("speed","FLOAT"),
        bigquery.SchemaField("bt","FLOAT"),
        bigquery.SchemaField("bz","FLOAT"),
        bigquery.SchemaField("raw_plasma","STRING"),
        bigquery.SchemaField("raw_mag","STRING"),
        bigquery.SchemaField("ingested_at","TIMESTAMP"),
    ]
    ensure_table(schema)

    out=[]
    now = datetime.now(timezone.utc).isoformat()
    for r in rows_p:
        t = r[0]
        density = _f(r, head_p, "density")
        speed   = _f(r, head_p, "speed")
        mrow    = idx_m.get(t)
        bt = bz = None
        if mrow:
            bt = _f(mrow, head_m, "bt")
            bz = _f(mrow, head_m, "bz")
        out.append({
            "time": t,
            "density": density,
            "speed": speed,
            "bt": bt,
            "bz": bz,
            "raw_plasma": json.dumps(r, ensure_ascii=False),
            "raw_mag": json.dumps(mrow, ensure_ascii=False) if mrow else None,
            "ingested_at": now
        })
    return insert_rows(out)

def _f(row, header, name):
    try:
        idx = header.index(name)
        v = row[idx]
        return float(v) if v not in (None,"") else None
    except Exception:
        return None

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
