import os, json, re
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Response
from google.cloud import bigquery

PROJECT = os.environ.get("PROJECT", "synexis-project-sentinel")
BQ_DATASET = os.environ.get("BQ_DATASET", "sentinel_raw")
BQ_TABLE = os.environ.get("BQ_TABLE", "geomag_indices")
SOURCE_URL = os.environ.get("SOURCE_URL", "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json")
SRC_TAG = os.environ.get("SRC_TAG", "geomag-kp")

app = FastAPI()

@app.on_event("startup")
def _startup():
    # Print all registered routes at startup (helps confirm what code is actually running)
    for r in app.router.routes:
        try:
            print("ROUTE", getattr(r, "path", None), getattr(r, "methods", None))
        except Exception:
            pass

@app.get("/routes")
def routes():
    out = []
    for r in app.router.routes:
        out.append({"path": getattr(r, "path", None), "methods": sorted(list(getattr(r, "methods", []) or []))})
    return {"routes": out}

@app.get("/healthz")
def healthz():
    return {"ok": True}



@app.get("/__health")
def __health():
    return {"ok": True}
def parse_kp(val):
    """
    NOAA Kp 1-minute feed sometimes uses values like '4P' or '1P'.
    Treat trailing letters as qualifiers and parse the numeric part.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    m = re.match(r'^-?\d+(\.\d+)?', s)  # '4P' -> '4'
    if not m:
        return None
    return float(m.group(0))

@app.get("/")
def poll():
    r = requests.get(SOURCE_URL, timeout=30, headers={"User-Agent": "synexis-project-sentinel/1.0"})
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, list) or not data:
        return Response(content="OK (0 rows)\n", media_type="text/plain", status_code=200)

    last = data[-1]
    t = last.get("time_tag") or last.get("time") or last.get("timestamp")
    kp_raw = last.get("kp") or last.get("kp_index") or last.get("value")

    obs_time = str(t) if t is not None else datetime.now(timezone.utc).isoformat()
    kp = parse_kp(kp_raw)
    now = datetime.now(timezone.utc).isoformat()

    client = bigquery.Client(project=PROJECT)
    table_id = f"{PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

    row = {
        "time": obs_time,  # BigQuery TIMESTAMP accepts RFC3339 string; if this breaks we'll cast later
        "kp": kp,
        "raw": json.dumps(last, separators=(",", ":"), ensure_ascii=False),
        "ingested_at": now,
    }

    errors = client.insert_rows_json(table_id, [row])
    if errors:
        return Response(content=f"ERROR: {errors}\n", media_type="text/plain", status_code=500)

    return Response(content="OK (1 row)\n", media_type="text/plain", status_code=200)
