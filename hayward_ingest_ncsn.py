import requests
import csv
import io
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
DATASET = "sentinel_groundtruth"
TABLE = "hayward_ncsn_earthquakes"

PARAMS = {
    "format": "csv",
    "minmagnitude": 2.5,
    "minlatitude": 37.2,
    "maxlatitude": 38.1,
    "minlongitude": -122.4,
    "maxlongitude": -121.6,
    "starttime": "2001-01-01",
    "endtime": "2025-12-31",
    "orderby": "time-asc"
}

SCHEMA = [
    bigquery.SchemaField("time", "TIMESTAMP"),
    bigquery.SchemaField("latitude", "FLOAT64"),
    bigquery.SchemaField("longitude", "FLOAT64"),
    bigquery.SchemaField("depth", "FLOAT64"),
    bigquery.SchemaField("mag", "FLOAT64"),
    bigquery.SchemaField("magType", "STRING"),
    bigquery.SchemaField("nst", "INT64"),
    bigquery.SchemaField("gap", "FLOAT64"),
    bigquery.SchemaField("dmin", "FLOAT64"),
    bigquery.SchemaField("rms", "FLOAT64"),
    bigquery.SchemaField("net", "STRING"),
    bigquery.SchemaField("id", "STRING"),
    bigquery.SchemaField("updated", "TIMESTAMP"),
    bigquery.SchemaField("place", "STRING"),
    bigquery.SchemaField("type", "STRING"),
    bigquery.SchemaField("horizontalError", "FLOAT64"),
    bigquery.SchemaField("depthError", "FLOAT64"),
    bigquery.SchemaField("magError", "FLOAT64"),
    bigquery.SchemaField("magNst", "INT64"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("locationSource", "STRING"),
    bigquery.SchemaField("magSource", "STRING"),
]

def fetch_comcat():
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    print(f"Fetching ComCat...")
    r = requests.get(url, params=PARAMS, timeout=120)
    r.raise_for_status()
    print(f"Response: {r.status_code}, size: {len(r.content)} bytes")
    return r.text

def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        def safe_float(v):
            try: return float(v) if v.strip() else None
            except: return None
        def safe_int(v):
            try: return int(v) if v.strip() else None
            except: return None
        rows.append({
            "time": row.get("time", "").strip() or None,
            "latitude": safe_float(row.get("latitude")),
            "longitude": safe_float(row.get("longitude")),
            "depth": safe_float(row.get("depth")),
            "mag": safe_float(row.get("mag")),
            "magType": row.get("magType", "").strip() or None,
            "nst": safe_int(row.get("nst")),
            "gap": safe_float(row.get("gap")),
            "dmin": safe_float(row.get("dmin")),
            "rms": safe_float(row.get("rms")),
            "net": row.get("net", "").strip() or None,
            "id": row.get("id", "").strip() or None,
            "updated": row.get("updated", "").strip() or None,
            "place": row.get("place", "").strip() or None,
            "type": row.get("type", "").strip() or None,
            "horizontalError": safe_float(row.get("horizontalError")),
            "depthError": safe_float(row.get("depthError")),
            "magError": safe_float(row.get("magError")),
            "magNst": safe_int(row.get("magNst")),
            "status": row.get("status", "").strip() or None,
            "locationSource": row.get("locationSource", "").strip() or None,
            "magSource": row.get("magSource", "").strip() or None,
        })
    print(f"Parsed {len(rows)} events")
    return rows

def load_to_bq(rows):
    client = bigquery.Client(project=PROJECT)
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"
    table = bigquery.Table(table_id, schema=SCHEMA)
    table = client.create_table(table, exists_ok=True)
    print(f"Table ready: {table_id}")
    chunk_size = 5000
    total_loaded = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i+chunk_size]
        errors = client.insert_rows_json(table, chunk)
        if errors:
            print(f"Errors in chunk {i//chunk_size}: {errors[:3]}")
        else:
            total_loaded += len(chunk)
            print(f"Loaded chunk {i//chunk_size + 1}: {total_loaded}/{len(rows)} rows")
    print(f"Done. Total loaded: {total_loaded}")

if __name__ == "__main__":
    text = fetch_comcat()
    rows = parse_csv(text)
    m55 = sum(1 for r in rows if r["mag"] and r["mag"] >= 5.5)
    m50 = sum(1 for r in rows if r["mag"] and r["mag"] >= 5.0)
    print(f"Sanity check — M5.5+: {m55}, M5.0+: {m50}, total: {len(rows)}")
    load_to_bq(rows)
