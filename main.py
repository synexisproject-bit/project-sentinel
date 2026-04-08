import os, requests, json
from datetime import datetime, timezone
from google.cloud import bigquery
from google.auth import default as google_auth_default

def _resolve_project_id():
    # 1) env var
    p = os.environ.get("PROJECT_ID") or os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if p: return p
    # 2) ADC
    creds, proj = google_auth_default()
    if proj: return proj
    # 3) fallback: try client
    try:
        return bigquery.Client().project
    except Exception:
        return None

PROJECT = _resolve_project_id()
DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
TABLE   = os.environ.get("BQ_TABLE",   "usgs_quakes_raw")

# Construct a client with explicit project to avoid 'None'
bq = bigquery.Client(project=PROJECT)

USGS_URL = os.environ.get("USGS_URL",
  "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
)

def _ts(ms):
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc) if ms else None

def poll_usgs_quakes(request=None):
    # Log what project/table we think we're using
    print(json.dumps({"stage":"start", "project":PROJECT, "dataset":DATASET, "table":TABLE}))

    if not PROJECT:
        print(json.dumps({"stage":"error", "reason":"No project resolved"}))
        return ("project resolution failed", 500)

    # Fetch
    r = requests.get(USGS_URL, timeout=20)
    r.raise_for_status()
    data = r.json()

    # Map rows
    rows = []
    for f in data.get("features", []):
        props = f.get("properties", {}) or {}
        geom  = f.get("geometry", {}) or {}
        coords = (geom.get("coordinates") or [None, None, None])
        rows.append({
            "id": f.get("id"),
            "event_time": _ts(props.get("time")),
            "magnitude": props.get("mag"),
            "place": props.get("place"),
            "longitude": coords[0],
            "latitude":  coords[1],
            "depth_km":  coords[2] if len(coords) > 2 else None,
            "url": props.get("url"),
            "src": "usgs",
        })

    # Fully qualified table path with explicit default project
    table_ref = bigquery.TableReference.from_string(
        f"{DATASET}.{TABLE}",
        default_project=PROJECT
    )

    if rows:
        # Append
        bq.load_table_from_json(rows, table_ref).result()
        # De-dupe on id
        bq.query(f"""
          CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.{TABLE}` AS
          SELECT AS VALUE t FROM (
            SELECT t.*, ROW_NUMBER() OVER (PARTITION BY id ORDER BY _ingested_at DESC) rn
            FROM `{PROJECT}.{DATASET}.{TABLE}` t
          ) WHERE rn = 1
        """).result()

    print(json.dumps({"stage":"done", "inserted":len(rows)}))
    return ("ok", 200)
