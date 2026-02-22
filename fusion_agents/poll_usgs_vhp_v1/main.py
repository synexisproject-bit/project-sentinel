import os, json, requests
from datetime import datetime, timezone
from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
TABLE   = os.environ.get("BQ_TABLE",   "usgs_volcano_raw")
URL     = os.environ.get("SOURCE_URL")
bq = bigquery.Client(project=PROJECT)

def _ts(val):
    if val is None: return None
    try:
        if isinstance(val, (int, float)):
            if val > 1e12: val = val / 1000.0
            return datetime.fromtimestamp(val, tz=timezone.utc).isoformat().replace("+00:00","Z")
        if isinstance(val, str):
            return datetime.fromisoformat(val.replace("Z","+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except Exception:
        return None

def handler(request=None):
    r = requests.get(URL, headers={"User-Agent":"Synexis-Project-Sentinel"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    rows = []
    for f in (data.get("features") or []):
        p = f.get("properties", {}) or {}
        g = f.get("geometry", {}) or {}
        coords = g.get("coordinates") or [None, None]
        rows.append({
            "id": p.get("id") or f.get("id"),
            "volcano": p.get("volcano") or p.get("place") or p.get("title"),
            "status": p.get("status") or p.get("alert") or p.get("color"),
            "alert_level": p.get("alert") or p.get("level"),
            "event_time": _ts(p.get("time") or p.get("updated") or p.get("event_time")),
            "longitude": float(coords[0]) if coords and coords[0] is not None else None,
            "latitude":  float(coords[1]) if len(coords)>1 and coords[1] is not None else None,
            "url": p.get("url") or p.get("detail"),
            "src": "usgs_vhp",
            "raw": json.dumps(f, ensure_ascii=False),
        })
    if not rows: return ("ok", 200)
    bq.load_table_from_json(rows, f"{PROJECT}.{DATASET}.{TABLE}").result()
    return ("ok", 200)
