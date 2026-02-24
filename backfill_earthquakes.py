import requests, json
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery

PROJECT = "synexis-project-sentinel"
DATASET = "sentinel_groundtruth"
TABLE = "master_earthquakes"
TABLE_ID = f"{PROJECT}.{DATASET}.{TABLE}"

client = bigquery.Client(project=PROJECT)
now = datetime.now(timezone.utc).isoformat()

def fetch_year(start, end):
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {
        "format": "geojson",
        "starttime": start,
        "endtime": end,
        "minmagnitude": 4.0,
        "orderby": "time-asc",
        "limit": 20000,
    }
    r = requests.get(url, params=params, timeout=60,
                    headers={"User-Agent": "synexis-project-sentinel/1.0"})
    r.raise_for_status()
    return r.json().get("features", [])

def features_to_rows(features):
    rows = []
    for f in features:
        p = f.get("properties", {}) or {}
        g = f.get("geometry", {}) or {}
        coords = g.get("coordinates", [None, None, None])
        ts = p.get("time")
        updated = p.get("updated")
        rows.append({
            "event_id": f.get("id"),
            "time": datetime.fromtimestamp(ts/1000, tz=timezone.utc).isoformat() if ts else None,
            "latitude": coords[1],
            "longitude": coords[0],
            "depth_km": coords[2],
            "magnitude": p.get("mag"),
            "magnitude_type": p.get("magType"),
            "place": p.get("place"),
            "status": p.get("status"),
            "tsunami": p.get("tsunami"),
            "sig": p.get("sig"),
            "net": p.get("net"),
            "updated": datetime.fromtimestamp(updated/1000, tz=timezone.utc).isoformat() if updated else None,
            "url": p.get("url"),
            "src": "usgs-comcat",
            "ingested_at": now,
        })
    return rows

def insert_rows(rows):
    if not rows:
        return 0
    errors = client.insert_rows_json(TABLE_ID, rows)
    if errors:
        print(f"  BQ errors: {errors[:2]}")
        return 0
    return len(rows)

# Backfill 25 years in yearly chunks
current_year = datetime.now().year
total_inserted = 0

for year in range(current_year - 25, current_year + 1):
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    print(f"Fetching {year}...", end=" ", flush=True)
    try:
        features = fetch_year(start, end)
        rows = features_to_rows(features)
        inserted = insert_rows(rows)
        total_inserted += inserted
        print(f"{inserted} events inserted.")
    except Exception as e:
        print(f"ERROR: {e}")

print(f"\nDone. Total inserted: {total_inserted}")
